# In-browser "Fast" mode

The client-side classifier for the [in-browser Fast mode](../../docs/roadmap.md)
(Phase 1). Goal: run the iNat model **in the extension** so images are filtered
with **zero install**, keeping the local server optional for the heavier tiers.

This directory is being built up in reviewable increments. **What's here now:**

| File | Purpose |
| --- | --- |
| [`inat.mjs`](inat.mjs) | Pure preprocess / score functions, in numeric parity with the Python pipeline (`imgedge.inat.inat_filter`). No DOM / ONNX — safe to unit-test in Node and reuse in the offscreen document. |
| [`classify.mjs`](classify.mjs) | Browser glue on top of `inat.mjs`: decode image bytes + resize (canvas) → run the model (ONNX Runtime is injected, not imported) → `{ score, blocked }`. Validated end-to-end in a real browser. |
| [`inat_web.json`](inat_web.json) | Generated metadata: input size + float scaling, and the **Arachnida leaf-index mask** (14 of the model's 507 outputs). Lets the extension avoid shipping/parsing the full taxonomy. |
| [`offscreen.mjs`](offscreen.mjs) + [`offscreen.html`](offscreen.html) | The offscreen document: hosts one ORT session for the bundled model and answers classify requests from the service worker (reusing `classify.mjs`). MV3 service workers can't keep a model warm, so this does. |
| `vendor/` | The bundled `inat.onnx` + ONNX Runtime Web, populated by `tools/bundle_inbrowser.py`. Git-ignored — not committed. |

**How it's wired:** when the local server is unreachable (and the
`inBrowserFallback` setting is on — the default), `background.js` creates the
[offscreen document](https://developer.chrome.com/docs/extensions/reference/api/offscreen)
and delegates classification to it, so filtering keeps working with **no server**.
`manifest.json` grants the `offscreen` permission and a `'wasm-unsafe-eval'` CSP
(for ONNX Runtime's WebAssembly).

**Not here yet** (Phase 3 polish): an explicit "Fast (in-browser)" preset in the
popup, and a resize that matches Pillow's `BILINEAR` exactly if Fast-mode recall
needs it.

## Parity

`inat.mjs` re-implements the Python pre/post-processing, so the two must stay in
lock-step. Both a Node test and a pytest assert against one committed fixture:

- [`tests/js/inbrowser_parity.test.mjs`](../../tests/js/inbrowser_parity.test.mjs) — `npm test`
- [`tests/test_inbrowser_parity.py`](../../tests/test_inbrowser_parity.py) — `pytest`
- Fixture: [`tests/js/fixtures/inat_parity.json`](../../tests/js/fixtures/inat_parity.json)

## Regenerating `inat_web.json`

Re-run whenever the model or taxonomy changes (needs the taxonomy from
`python -m imgedge.inat.download_models`):

```powershell
python tools/export_inat_web.py
```

## Bundling the model + runtime

The offscreen document loads `inat.onnx` + ONNX Runtime Web from `vendor/`
(git-ignored). Populate it before loading or packaging the extension:

```powershell
python src/imgedge/inat/convert_to_onnx.py   # once: produce the ONNX model
npm install onnxruntime-web                  # once: fetch the ORT Web dist
python tools/bundle_inbrowser.py             # copy model + runtime into vendor/
```

By default this copies a **lean** ORT set (the WebGPU + WASM builds — ~70 MB with
the model). Pass `--all` to include every wasm variant (~130 MB) for maximum
browser compatibility.

The pre/post-processing math is validated in Phase 0's spike
([`spike/inbrowser-fast/`](../../spike/inbrowser-fast/)), which confirmed the
quantized iNat ONNX runs under ONNX Runtime Web (~8.5 ms p50 on WebGPU, ~447 ms
on the WASM fallback).
