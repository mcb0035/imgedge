import js from "@eslint/js";
import globals from "globals";

export default [
  { ignores: ["dist/", "node_modules/", "training/", "extension/icons/", ".venv/", "**/site-packages/**"] },
  js.configs.recommended,
  {
    // The extension front-end runs as classic scripts with the WebExtension +
    // browser globals (no bundler, no modules).
    files: ["extension/background.js", "extension/content.js", "extension/popup.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: { ...globals.browser, ...globals.webextensions },
    },
    rules: {
      "no-empty": ["error", { allowEmptyCatch: true }],
      "no-unused-vars": ["warn", { args: "none", varsIgnorePattern: "^_" }],
    },
  },
  {
    // Node-based unit tests for the extension scripts (node:test + a vm sandbox).
    files: ["tests/js/**/*.mjs"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.node, ...globals.browser },
    },
  },
];
