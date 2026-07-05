// Copyright the ImgEdge contributors.
// SPDX-License-Identifier: Apache-2.0
// Verifies the WebExtension i18n wiring is complete and self-consistent:
//  - every message has a non-empty string,
//  - every key referenced by the scripts / popup / manifest is defined,
//  - every defined message is actually referenced (no dead strings).
// This guards against drift when strings are added, renamed, or removed.

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const EXT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "extension");
const read = (rel) => fs.readFileSync(path.join(EXT, rel), "utf8");

const messages = JSON.parse(read("_locales/en/messages.json"));
const defined = new Set(Object.keys(messages));

function keysFrom(text, re) {
  const out = new Set();
  let m;
  while ((m = re.exec(text)) !== null) out.add(m[1]);
  return out;
}

const referenced = new Set();
// Literal getMessage("key") calls (the trailing ) or , skips concatenated keys
// like getMessage("preset" + name), which are covered via the popup markup).
for (const f of ["popup.js", "background.js", "content.js"]) {
  for (const k of keysFrom(read(f), /getMessage\(\s*["']([A-Za-z0-9_]+)["']\s*[),]/g)) referenced.add(k);
}
// background.js resolves context-menu titles indirectly via `titleKey`.
for (const k of keysFrom(read("background.js"), /titleKey:\s*["']([A-Za-z0-9_]+)["']/g)) referenced.add(k);
// popup.html hooks: data-i18n / data-i18n-placeholder / data-i18n-title.
for (const k of keysFrom(read("popup.html"), /data-i18n(?:-[a-z]+)?="([A-Za-z0-9_]+)"/g)) referenced.add(k);
// manifest __MSG_key__ substitutions (name, description, title).
for (const k of keysFrom(read("manifest.json"), /__MSG_([A-Za-z0-9_]+)__/g)) referenced.add(k);

test("every message has a non-empty string 'message'", () => {
  for (const [k, v] of Object.entries(messages)) {
    assert.equal(typeof v.message, "string", `${k}.message must be a string`);
    assert.ok(v.message.length > 0, `${k}.message must be non-empty`);
  }
});

test("every referenced i18n key is defined in messages.json", () => {
  const missing = [...referenced].filter((k) => !defined.has(k)).sort();
  assert.deepEqual(missing, [], `missing message keys: ${missing.join(", ")}`);
});

test("every defined message is referenced (no dead strings)", () => {
  const unused = [...defined].filter((k) => !referenced.has(k)).sort();
  assert.deepEqual(unused, [], `unused message keys: ${unused.join(", ")}`);
});
