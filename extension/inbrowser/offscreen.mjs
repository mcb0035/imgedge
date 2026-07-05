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
import { classifyBlob } from "./classify.mjs";

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
      const meta = await (await fetch(resource("inat_web.json"))).json();
      // WASM only: a headless offscreen document can't reliably get a WebGPU
      // context, and the WebGPU EP can crash/hang the document while loading.
      const session = await ort.InferenceSession.create(resource("vendor/inat.onnx"), {
        executionProviders: ["wasm"],
      });
      return { ort, session, meta };
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
  const { ort, session, meta } = await ensureReady();
  return classifyBlob(ort, session, meta, blob, threshold);
}

// Wire the background <-> offscreen message channel (only in the extension).
const runtime = globalThis.chrome && globalThis.chrome.runtime;
if (runtime && runtime.onMessage) {
  runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (!msg || msg.target !== "offscreen" || msg.type !== "inbrowser-classify") return false;
    classifyDataUrl(msg.dataUrl, msg.threshold)
      .then((r) => sendResponse({ ok: true, score: r.score, blocked: r.blocked }))
      .catch((e) => {
        console.error("[imgedge] offscreen classify failed:", e);
        sendResponse({ ok: false, error: String(e) });
      });
    return true; // keep the channel open for the async response
  });
}
