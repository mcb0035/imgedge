// Tests for the background service worker's helpers: URL host extraction, base64
// encoding of image bytes, the HMAC proof (F2), and the message-sender guard that
// ignores messages from other extensions / pages (threat-model F7).

import { test } from "node:test";
import assert from "node:assert/strict";
import crypto from "node:crypto";

import { loadExtensionScript } from "./_harness.mjs";

test("hostOf returns the hostname, or empty string on a bad URL", () => {
  const { context } = loadExtensionScript("background.js");
  assert.equal(context.hostOf("https://example.com/a/b.jpg?q=1"), "example.com");
  assert.equal(context.hostOf("http://sub.host.example:8080/x"), "sub.host.example");
  assert.equal(context.hostOf("not a url"), "");
});

test("bufferToBase64 encodes image bytes like Buffer", () => {
  const { context } = loadExtensionScript("background.js");
  const bytes = Uint8Array.from([104, 105, 33]); // "hi!"
  assert.equal(context.bufferToBase64(bytes.buffer), Buffer.from("hi!").toString("base64"));
});

test("hmacHex matches node crypto HMAC-SHA256 (F2 proof)", async () => {
  const { context } = loadExtensionScript("background.js");
  const got = await context.hmacHex("token-xyz", "challenge-42");
  const want = crypto.createHmac("sha256", "token-xyz").update("challenge-42").digest("hex");
  assert.equal(got, want);
});

test("onMessage ignores messages from a foreign sender id (F7)", () => {
  const { captured } = loadExtensionScript("background.js");
  assert.equal(typeof captured.onMessage, "function", "onMessage listener registered");

  let responded = false;
  const ret = captured.onMessage({ type: "getConfig" }, { id: "some-other-extension" }, () => {
    responded = true;
  });

  assert.equal(ret, false); // rejected: no async channel kept open
  assert.equal(responded, false); // and never responds to the impostor
});

test("onMessage accepts messages from the extension's own id (F7)", () => {
  const { captured } = loadExtensionScript("background.js");
  const ret = captured.onMessage({ type: "getConfig" }, { id: "imgedge-test-id" }, () => {});
  assert.equal(ret, true); // keeps the channel open for the async response
});

test("classify sends the selected preset profile in the request body", async () => {
  const { context } = loadExtensionScript("background.js");
  let sent = null;
  context.fetch = async (url, opts) => {
    sent = JSON.parse(opts.body);
    return { ok: true, json: async () => ({ block: false, reason: "ok", score: 0 }) };
  };
  const res = await context.classify("http://example.com/a.jpg", null, null);
  assert.equal(res.allow, true);
  assert.equal(sent.url, "http://example.com/a.jpg");
  assert.equal(sent.profile, "balanced"); // the DEFAULTS preset
});
