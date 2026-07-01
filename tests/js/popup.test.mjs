// Tests for the popup's security-relevant helpers: the local-endpoint allowlist
// (threat-model F6), the constant-time hex compare, and the HMAC proof used to
// verify the server's identity before the token is sent (F2).

import { test } from "node:test";
import assert from "node:assert/strict";
import crypto from "node:crypto";

import { loadExtensionScript } from "./_harness.mjs";

const { context } = loadExtensionScript("popup.js");

test("isLocalEndpoint accepts loopback http(s) endpoints", () => {
  const ok = [
    "http://localhost:8723/classify",
    "http://127.0.0.1:8723",
    "http://[::1]:8723/classify",
    "https://localhost:8723",
  ];
  for (const url of ok) assert.equal(context.isLocalEndpoint(url), true, url);
});

test("isLocalEndpoint rejects remote hosts, non-http schemes, and junk (F6)", () => {
  const bad = [
    "http://evil.com/classify",
    "http://192.168.1.5:8723",
    "http://localhost.evil.com",
    "https://127.0.0.1.evil.com",
    "ftp://localhost:8723",
    "file:///etc/passwd",
    "not a url",
    "",
  ];
  for (const url of bad) assert.equal(context.isLocalEndpoint(url), false, url);
});

test("eqHex is a length-checked constant-time compare", () => {
  assert.equal(context.eqHex("abcd1234", "abcd1234"), true);
  assert.equal(context.eqHex("abcd1234", "abcd1235"), false);
  assert.equal(context.eqHex("abcd", "abcd1234"), false); // length mismatch
  assert.equal(context.eqHex(null, "abcd"), false); // non-string
  assert.equal(context.eqHex(undefined, undefined), false);
});

test("hmacHex matches a known HMAC-SHA256 vector (F2 proof)", async () => {
  const got = await context.hmacHex("shared-secret", "nonce-abc123");
  const want = crypto.createHmac("sha256", "shared-secret").update("nonce-abc123").digest("hex");
  assert.equal(got, want);
});
