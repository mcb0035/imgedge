// Copyright the ImgEdge contributors.
// SPDX-License-Identifier: Apache-2.0
// Test harness for the extension's classic scripts (background.js, popup.js).
//
// They run in the browser as non-module scripts that touch WebExtension + DOM
// globals at load, so we can't just `import` them. Instead we evaluate each file
// in a `node:vm` context with those globals mocked; top-level `function`
// declarations then become properties of the context, which the tests call
// directly. This exercises the real shipping code with zero changes to it.

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

// Back the chrome.i18n stub with the real default-locale messages so the scripts
// produce the same text they ship with, and tests can assert on it. Mirrors the
// browser's positional $1..$9 substitution (and $$ -> $).
const MESSAGES = JSON.parse(
  fs.readFileSync(path.join(ROOT, "extension", "_locales", "en", "messages.json"), "utf8"),
);
function i18nGetMessage(key, subs) {
  const entry = MESSAGES[key];
  if (!entry) return "";
  const arr = Array.isArray(subs) ? subs : subs != null ? [subs] : [];
  return entry.message.replace(/\$(\$|\d)/g, (_, t) => (t === "$" ? "$" : arr[Number(t) - 1] ?? ""));
}

// A permissive stand-in for a DOM element: reads return benign defaults and every
// method is a no-op, so the scripts' top-level DOM wiring runs without throwing.
function makeElement() {
  return {
    style: {},
    classList: { add() {}, remove() {}, toggle() {} },
    addEventListener() {},
    appendChild() {},
    setAttribute() {},
    checked: false,
    value: "",
    textContent: "",
    className: "",
    type: "",
    title: "",
  };
}

// A resolved, inert fetch response so health/network calls fail closed quietly
// (ok:false) rather than rejecting and producing unhandled rejections.
function inertResponse() {
  return {
    ok: false,
    status: 503,
    headers: { get: () => null },
    json: async () => ({}),
    arrayBuffer: async () => new ArrayBuffer(0),
  };
}

/**
 * Evaluate an extension script in a sandbox and return its context plus any
 * captured runtime listeners.
 * @param {string} file repo-relative path, e.g. "background.js"
 */
export function loadExtensionScript(file) {
  const code = fs.readFileSync(path.join(ROOT, "extension", file), "utf8");
  const captured = {};

  const context = {
    console,
    crypto: globalThis.crypto,
    TextEncoder,
    TextDecoder,
    URL,
    URLSearchParams,
    AbortController,
    setTimeout,
    clearTimeout,
    btoa: (s) => Buffer.from(s, "binary").toString("base64"),
    atob: (s) => Buffer.from(s, "base64").toString("binary"),
    fetch: async () => inertResponse(),
    document: {
      getElementById: () => makeElement(),
      createElement: () => makeElement(),
      querySelector: () => null,
      querySelectorAll: () => [],
      addEventListener() {},
    },
    chrome: {
      i18n: {
        getMessage: i18nGetMessage,
        getUILanguage: () => "en",
      },
      runtime: {
        id: "imgedge-test-id",
        getManifest: () => ({ version: "0.0.0-test" }),
        getURL: (p) => p,
        onInstalled: { addListener() {} },
        onStartup: { addListener() {} },
        onMessage: {
          addListener: (fn) => {
            captured.onMessage = fn;
          },
        },
        sendMessage: async () => ({}),
      },
      storage: { local: { get: async () => ({}), set: async () => {} } },
      tabs: {
        query: async () => [],
        sendMessage: async () => {},
        onUpdated: { addListener() {} },
        onRemoved: { addListener() {} },
      },
      action: {
        setBadgeText() {},
        setBadgeBackgroundColor() {},
        setBadgeTextColor() {},
        setTitle() {},
        setIcon() {},
      },
      contextMenus: {
        create() {},
        removeAll: (cb) => {
          if (cb) cb();
        },
        onClicked: { addListener() {} },
      },
    },
  };
  context.self = context;
  context.window = context;
  context.globalThis = context;

  vm.createContext(context);
  vm.runInContext(code, context, { filename: file });
  return { context, captured };
}
