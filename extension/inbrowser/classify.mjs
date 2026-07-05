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
 * Run a prepared NHWC float32 input through the session and return the raw
 * output vector.
 *
 * @param {object} ort - the ONNX Runtime namespace (provides `Tensor`)
 * @param {object} session - an ORT InferenceSession
 * @param {object} meta - parsed inat_web.json
 * @param {Float32Array} input - NHWC data, length height*width*3
 * @returns {Promise<Float32Array>}
 */
export async function runModel(ort, session, meta, input) {
  const { height, width } = meta.input;
  const name = session.inputNames[0];
  const tensor = new ort.Tensor("float32", input, [1, height, width, 3]);
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
