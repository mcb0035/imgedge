// Copyright the ImgEdge contributors.
// SPDX-License-Identifier: Apache-2.0
// Tests for the in-browser fallback wiring in the background worker: the
// offscreen-document lifecycle, the classify delegation, and the message guard.

import { test } from "node:test";
import assert from "node:assert/strict";

import { loadExtensionScript } from "./_harness.mjs";

// Install a chrome.offscreen mock + a sendMessage stub that answers the offscreen
// classify request; returns a getter for how many times createDocument was called.
function withOffscreen(context, respond) {
  let created = 0;
  context.chrome.offscreen = {
    createDocument: async () => {
      created += 1;
    },
  };
  context.chrome.runtime.sendMessage = async (msg) => respond(msg);
  return () => created;
}

test("onMessage leaves offscreen-targeted messages for the offscreen document", () => {
  const { captured } = loadExtensionScript("background.js");
  let responded = false;
  const ret = captured.onMessage(
    { target: "offscreen", type: "inbrowser-classify" },
    { id: "imgedge-test-id" },
    () => {
      responded = true;
    },
  );
  assert.equal(ret, false); // not handled here
  assert.equal(responded, false);
});

test("classifyInBrowser creates the offscreen doc and returns its verdict", async () => {
  const { context } = loadExtensionScript("background.js");
  const created = withOffscreen(context, (msg) => {
    assert.equal(msg.target, "offscreen");
    assert.equal(msg.type, "inbrowser-classify");
    assert.equal(msg.dataUrl, "data:image/png;base64,AAAA");
    assert.equal(msg.threshold, 0.5);
    return { ok: true, blocked: true, score: 0.87 };
  });
  const r = await context.classifyInBrowser("http://x/a.png", "data:image/png;base64,AAAA", 0.5);
  assert.deepEqual(r, { ok: true, blocked: true, score: 0.87 });
  assert.equal(created(), 1);
});

test("ensureOffscreen creates the document only once", async () => {
  const { context } = loadExtensionScript("background.js");
  const created = withOffscreen(context, () => ({ ok: true }));
  await context.ensureOffscreen();
  await context.ensureOffscreen();
  assert.equal(created(), 1);
});

test("classify falls back to in-browser when the server is unreachable", async () => {
  const { context } = loadExtensionScript("background.js");
  withOffscreen(context, () => ({ ok: true, blocked: true, score: 0.91 }));
  context.fetch = async () => {
    throw new Error("connection refused");
  };
  const res = await context.classify("http://example.com/a.jpg", "data:image/png;base64,AAAA", null);
  assert.equal(res.reason, "inbrowser");
  assert.equal(res.allow, false); // blocked in-browser
  assert.equal(res.score, 0.91);
});

test("classify fails open (per failClosed) when no offscreen support is available", async () => {
  const { context } = loadExtensionScript("background.js");
  // No chrome.offscreen -> classifyInBrowser can't run -> honor failClosed (default false).
  context.fetch = async () => {
    throw new Error("refused");
  };
  const res = await context.classify("http://example.com/a.jpg", "data:image/png;base64,AAAA", null);
  assert.equal(res.reason, "classifier-error");
  assert.equal(res.allow, true);
});
