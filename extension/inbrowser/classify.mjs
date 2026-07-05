// Copyright the ImgEdge contributors.
// SPDX-License-Identifier: Apache-2.0
/**
 * Browser-side glue that turns image bytes into an iNat "Fast" verdict, built on
 * the pure functions in inat.mjs. Designed to run in the extension's offscreen
 * document (or any worker/window with OffscreenCanvas + createImageBitmap).
 *
 * ONNX Runtime and the session are *injected* rather than imported, so this
 * module has no hard dependency on a global `ort` and the tensor/score
 * composition (runModel) stays unit-testable in Node. Only decodeToRgba needs a
 * browser (image decode + canvas), so it is validated end-to-end in a browser.
 */
import { toModelInput, targetScore, isBlocked } from "./inat.mjs";
import { toTimmInput, evidenceFromLogits } from "./timm.mjs";
import { combineEvidence } from "./ensemble.mjs";

// Images smaller than this on either side (1x1 lazy-load placeholders, tracking
// pixels, tiny sprites) can't meaningfully depict the target -- and running the
// model on every one of them floods the machine. Skip them (treat as allow).
export const MIN_CLASSIFY_DIM = 32;

/** True when a decoded image is too small to be worth classifying. */
export function tooSmallToClassify(width, height) {
  return width < MIN_CLASSIFY_DIM || height < MIN_CLASSIFY_DIM;
}

/**
 * Decode image bytes and resize to the model input, returning RGBA pixels.
 * Uses the canvas resampler (a later phase may swap in a resize that matches
 * Pillow's BILINEAR exactly if Fast-mode accuracy needs it).
 *
 * @param {Blob} blob
 * @param {number} width
 * @param {number} height
 * @returns {Promise<Uint8ClampedArray>} RGBA, length width*height*4
 */
export async function decodeToRgba(blob, width, height) {
  const bitmap = await createImageBitmap(blob);
  try {
    return bitmapToRgba(bitmap, width, height);
  } finally {
    bitmap.close();
  }
}

/** Draw an already-decoded ImageBitmap into a width*height canvas -> RGBA pixels. */
function bitmapToRgba(bitmap, width, height) {
  const canvas = new OffscreenCanvas(width, height);
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(bitmap, 0, 0, width, height);
  return ctx.getImageData(0, 0, width, height).data;
}

/**
 * Run a prepared float32 input through the session and return the raw output
 * vector. The tensor layout follows `meta.input.layout` ("NCHW" for the timm
 * model, otherwise NHWC as the iNat model expects).
 *
 * @param {object} ort - the ONNX Runtime namespace (provides `Tensor`)
 * @param {object} session - an ORT InferenceSession
 * @param {object} meta - parsed model metadata (inat_web.json / timm_web.json)
 * @param {Float32Array} input - data laid out to match the model, length height*width*3
 * @returns {Promise<Float32Array>}
 */
export async function runModel(ort, session, meta, input) {
  const { height, width, layout } = meta.input;
  const dims = layout === "NCHW" ? [1, 3, height, width] : [1, height, width, 3];
  const name = session.inputNames[0];
  const tensor = new ort.Tensor("float32", input, dims);
  const result = await session.run({ [name]: tensor });
  return result[session.outputNames[0]].data;
}

/**
 * Full pipeline: image bytes -> { score, blocked }.
 *
 * @param {object} ort - the ONNX Runtime namespace
 * @param {object} session - an ORT InferenceSession for the iNat model
 * @param {object} meta - parsed inat_web.json
 * @param {Blob} blob - the image bytes
 * @param {number} threshold - block threshold in [0, 1]
 * @returns {Promise<{score: number, blocked: boolean}>}
 */
export async function classifyBlob(ort, session, meta, blob, threshold) {
  const { width, height, divisor, offset } = meta.input;
  let bitmap;
  try {
    bitmap = await createImageBitmap(blob);
  } catch {
    // The browser can't decode it (e.g. an SVG, or a corrupt / unsupported
    // format). The model only handles raster images, so treat it as allowed --
    // this mirrors the server's JPEG/PNG/WEBP/GIF/BMP format allow-list.
    return { score: 0, blocked: false, skipped: true };
  }
  try {
    // Skip trivially small images (placeholders / tracking pixels): they can't
    // depict the target, and classifying every one would flood the machine.
    if (tooSmallToClassify(bitmap.width, bitmap.height)) {
      return { score: 0, blocked: false, skipped: true };
    }
    const rgba = bitmapToRgba(bitmap, width, height);
    const input = toModelInput(rgba, width, height, { divisor, offset });
    const output = await runModel(ort, session, meta, input);
    const score = targetScore(output, meta.arachnida_leaf_indices);
    return { score, blocked: isBlocked(score, threshold) };
  } finally {
    bitmap.close();
  }
}

/**
 * Ensemble pipeline: image bytes -> { score, blocked } from the iNat voter plus
 * the optional timm voter, combined by the evidence policy (ensemble.mjs). The
 * image is decoded once and resized per model. Mirrors the server's two-voter
 * Fast tier (salience deferred; see ensemble.mjs).
 *
 * @param {object} ort - the ONNX Runtime namespace
 * @param {{inat: {session: object, meta: object}, timm: ?{session: object, meta: object}}} models
 * @param {Blob} blob - the image bytes
 * @param {number} threshold - block threshold in [0, 1]
 * @returns {Promise<{score: number, blocked: boolean, skipped?: boolean}>}
 */
export async function classifyBlobEnsemble(ort, models, blob, threshold) {
  let bitmap;
  try {
    bitmap = await createImageBitmap(blob);
  } catch {
    // Undecodable (SVG / corrupt / unsupported) -> allow, mirroring the
    // server's raster-only format allow-list.
    return { score: 0, blocked: false, skipped: true };
  }
  try {
    if (tooSmallToClassify(bitmap.width, bitmap.height)) {
      return { score: 0, blocked: false, skipped: true };
    }

    // iNat voter: its evidence is its target-taxon score (always >= 0).
    const im = models.inat.meta.input;
    const inatInput = toModelInput(bitmapToRgba(bitmap, im.width, im.height), im.width, im.height, {
      divisor: im.divisor,
      offset: im.offset,
    });
    const inatOut = await runModel(ort, models.inat.session, models.inat.meta, inatInput);
    const inatScore = targetScore(inatOut, models.inat.meta.arachnida_leaf_indices);
    const rows = [{ weight: 1.0, evidence: inatScore, isInat: true, score: inatScore }];

    // timm voter: signed evidence over ImageNet arachnid/look-alike classes.
    if (models.timm) {
      const tm = models.timm.meta.input;
      const timmInput = toTimmInput(bitmapToRgba(bitmap, tm.width, tm.height), tm.width, tm.height, {
        mean: tm.mean,
        std: tm.std,
      });
      const logits = await runModel(ort, models.timm.session, models.timm.meta, timmInput);
      const evidence = evidenceFromLogits(
        logits,
        models.timm.meta.block_indices,
        models.timm.meta.contrast_indices,
        models.timm.meta.contrast_weight,
      );
      const weight = typeof models.timm.meta.weight === "number" ? models.timm.meta.weight : 0.5;
      rows.push({ weight, evidence });
    }

    const { score, block } = combineEvidence(rows, { threshold });
    return { score, blocked: block };
  } finally {
    bitmap.close();
  }
}
