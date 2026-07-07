// Copyright the ImgEdge contributors.
// SPDX-License-Identifier: Apache-2.0
/**
 * ImgEdge offscreen classifier document.
 *
 * The MV3 service worker is short-lived and can't keep a model warm, so the
 * in-browser "Fast" path lives here: this document hosts a single ONNX Runtime
 * session for the bundled iNat model and answers classify requests from the
 * background worker. It is created on demand (chrome.offscreen) and reuses the
 * pure/glue logic in classify.mjs, so nothing model-specific is duplicated.
 *
 * Protocol: background sends
 *   { target: "offscreen", type: "inbrowser-classify", dataUrl, threshold }
 * and gets back { ok: true, score, blocked } or { ok: false, error }.
 */
import { classifyBlobEnsemble } from "./classify.mjs";

/** Resolve a bundled resource to an absolute URL (extension origin at runtime, page-relative in a harness). */
function resource(path) {
  const rt = globalThis.chrome && globalThis.chrome.runtime;
  if (rt && rt.getURL) return rt.getURL("inbrowser/" + path);
  const base = globalThis.location ? globalThis.location.href : "./";
  return new URL(path, base).href;
}

let ready = null;

/** Load the ONNX session + metadata once; subsequent calls reuse them. */
function ensureReady() {
  if (!ready) {
    ready = (async () => {
      const ort = globalThis.ort;
      ort.env.wasm.wasmPaths = resource("vendor/");
      // Multi-threaded WASM is ~2-4x faster than single-threaded, but it needs
      // SharedArrayBuffer (cross-origin isolation). Guard on it so we quietly
      // fall back to one thread where it isn't available instead of erroring.
      if (typeof SharedArrayBuffer !== "undefined") {
        const cores = (globalThis.navigator && globalThis.navigator.hardwareConcurrency) || 1;
        ort.env.wasm.numThreads = Math.min(4, cores);
      }
      console.info(
        "[imgedge] offscreen: crossOriginIsolated=" +
          globalThis.crossOriginIsolated +
          " wasmThreads=" +
          ort.env.wasm.numThreads,
      );
      // WASM only: a headless offscreen document can't reliably get a WebGPU
      // context, and the WebGPU EP can crash/hang the document while loading.
      const providers = { executionProviders: ["wasm"] };
      const inatMeta = await (await fetch(resource("inat_web.json"))).json();
      const inatSession = await ort.InferenceSession.create(resource("vendor/inat.onnx"), providers);
      const inat = { session: inatSession, meta: inatMeta };
      // Second voter (timm ImageNet model). Optional: if it isn't bundled, fall
      // back to iNat-only so the classifier still works.
      let timm = null;
      try {
        const timmMeta = await (await fetch(resource("timm_web.json"))).json();
        const timmSession = await ort.InferenceSession.create(resource("vendor/timm.onnx"), providers);
        timm = { session: timmSession, meta: timmMeta };
      } catch (e) {
        console.warn("[imgedge] offscreen: timm voter unavailable, using iNat only:", String(e));
      }
      // Optional third voter (deit3 ImageNet model). Same story as timm: if it
      // isn't bundled, the ensemble simply runs without it.
      let deit3 = null;
      try {
        const deit3Meta = await (await fetch(resource("deit3_web.json"))).json();
        const deit3Session = await ort.InferenceSession.create(resource("vendor/deit3.onnx"), providers);
        deit3 = { session: deit3Session, meta: deit3Meta };
      } catch (e) {
        console.warn("[imgedge] offscreen: deit3 voter unavailable, skipping it:", String(e));
      }
      return { ort, inat, timm, deit3 };
    })().catch((e) => {
      ready = null; // let a later request retry a failed load
      throw e;
    });
  }
  return ready;
}

/** Classify an image given as a data URL; returns { score, blocked }. */
export async function classifyDataUrl(dataUrl, threshold = 0.5) {
  const blob = await (await fetch(dataUrl)).blob();
  const { ort, inat, timm, deit3 } = await ensureReady();
  return classifyBlobEnsemble(ort, { inat, timm, deit3 }, blob, threshold);
}

// Wire the background <-> offscreen message channel (only in the extension).
const runtime = globalThis.chrome && globalThis.chrome.runtime;
if (runtime && runtime.onMessage) {
  runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (!msg || msg.target !== "offscreen" || msg.type !== "inbrowser-classify") return false;
    // Only our own service worker may drive the classifier -- reject other
    // extensions and any tab / content-script sender (defense-in-depth).
    if (!sender || sender.id !== runtime.id || sender.tab) return false;
    classifyDataUrl(msg.dataUrl, msg.threshold)
      .then((r) => sendResponse({ ok: true, score: r.score, blocked: r.blocked }))
      .catch((e) => {
        console.error("[imgedge] offscreen classify failed:", e);
        sendResponse({ ok: false, error: String(e) });
      });
    return true; // keep the channel open for the async response
  });
  // Start loading the model as soon as the document exists so the first
  // classify doesn't pay the ~0.4s session-create cost on top of inference.
  ensureReady().catch(() => {});
}
