// Copyright the ImgEdge contributors.
// SPDX-License-Identifier: Apache-2.0
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

test("applyProfiles greys out unavailable presets and falls back to the best available", () => {
  const radios = [
    { value: "fast", checked: false, disabled: false },
    { value: "balanced", checked: true, disabled: false },
    { value: "accurate", checked: false, disabled: false },
  ];
  const hint = { textContent: "" };
  const doc = context.document;
  doc.querySelectorAll = () => radios;
  doc.querySelector = (sel) => {
    if (sel.includes(":checked")) return radios.find((r) => r.checked) || null;
    const m = sel.match(/value="([a-z]+)"/);
    return m ? radios.find((r) => r.value === m[1]) || null : null;
  };
  const origGet = doc.getElementById;
  doc.getElementById = (id) => (id === "presethint" ? hint : origGet(id));

  // MobileCLIP not loaded -> "balanced" unavailable; the current (balanced)
  // choice falls back to the best available preset (accurate).
  context.applyProfiles({ fast: true, balanced: false, accurate: true });

  assert.equal(radios.find((r) => r.value === "balanced").disabled, true);
  assert.equal(radios.find((r) => r.value === "fast").disabled, false);
  assert.equal(radios.find((r) => r.value === "accurate").checked, true); // fell back
  assert.match(hint.textContent, /Balanced/);
});

test("buildExport includes only non-secret settings (no token, no lists)", () => {
  const s = {
    enabled: true, endpoint: "http://localhost:8723/classify", token: "SECRET-TOKEN",
    sendData: false, failClosed: true, strict: false, scanBackgrounds: true,
    threshold: 0.3, salience: 0.8, profile: "accurate",
  };
  const out = context.buildExport(s);
  assert.equal(out.app, "imgedge");
  assert.equal(out.kind, "settings");
  assert.ok(!("token" in out.settings), "token must never be exported");
  assert.equal(JSON.stringify(out).includes("SECRET-TOKEN"), false);
  assert.deepEqual(Object.keys(out.settings).sort(), [
    "enabled", "endpoint", "failClosed", "profile", "salience",
    "scanBackgrounds", "sendData", "strict", "threshold",
  ]);
  assert.equal(out.settings.profile, "accurate");
});

test("sanitizeImport applies whitelisted keys but never imports a token or unknown keys", () => {
  const current = { token: "KEEP-ME", endpoint: "http://localhost:8723/classify", profile: "fast" };
  const incoming = {
    settings: {
      token: "EVIL", enabled: false, threshold: 0.42, salience: 0.5,
      profile: "accurate", scanBackgrounds: false, bogus: "ignored",
    },
  };
  const s = context.sanitizeImport(incoming, current);
  assert.equal(s.token, "KEEP-ME"); // file's token ignored, current kept
  assert.equal(s.enabled, false);
  assert.equal(s.threshold, 0.42);
  assert.equal(s.salience, 0.5);
  assert.equal(s.profile, "accurate");
  assert.equal(s.scanBackgrounds, false);
  assert.ok(!("bogus" in s)); // unknown keys dropped
});

test("sanitizeImport rejects a non-local endpoint and clamps/validates values", () => {
  const current = { token: "", endpoint: "http://localhost:8723/classify" };
  const incoming = {
    settings: { endpoint: "http://evil.example.com/classify", threshold: 9, salience: -3, profile: "nope" },
  };
  const s = context.sanitizeImport(incoming, current);
  assert.equal(s.endpoint, "http://localhost:8723/classify"); // off-localhost ignored
  assert.equal(s.threshold, 0.95); // clamped to max
  assert.equal(s.salience, 0); // clamped to min
  assert.equal(s.profile, "balanced"); // invalid preset -> default kept
});

test("sanitizeImport tolerates a bare settings object and junk input", () => {
  const current = { token: "T" };
  assert.equal(context.sanitizeImport({ threshold: 0.2 }, current).threshold, 0.2); // no wrapper
  assert.equal(context.sanitizeImport(null, current).token, "T"); // junk -> keeps token
  assert.equal(context.sanitizeImport("nope", current).token, "T");
});
