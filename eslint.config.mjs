import js from "@eslint/js";
import globals from "globals";

export default [
  { ignores: ["dist/", "node_modules/", "training/", "icons/", ".venv/", "**/site-packages/**"] },
  js.configs.recommended,
  {
    // The extension front-end runs as classic scripts with the WebExtension +
    // browser globals (no bundler, no modules).
    files: ["background.js", "content.js", "popup.js"],
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
];
