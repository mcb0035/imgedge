# In-browser "Fast" mode

The client-side classifier for the [in-browser Fast mode](../../docs/roadmap.md):
it runs the small voters (iNat + timm, plus an optional deit3 third voter) **in
the extension** so images are filtered with **zero install**, keeping the local
server optional for the heavier tiers. It mirrors the server's **Fast** preset
(iNat + timm) via
[ONNX Runtime Web](https://onnxruntime.ai/docs/tutorials/web/) in an offscreen
document.

| File | Purpose |
| --- | --- |
| [`inat.mjs`](inat.mjs) | Pure iNat preprocess / score functions, in numeric parity with `imgedge.inat.inat_filter`. No DOM / ONNX — unit-testable in Node. |
| [`timm.mjs`](timm.mjs) | Pure timm (ImageNet) voter: ImageNet-normalized NCHW input, softmax, and signed arachnid evidence. Mirrors `imgedge.voters.timm_voter`. |
| [`ensemble.mjs`](ensemble.mjs) | Pure evidence combiner (`combineEvidence`): weighted signed evidence + the iNat-confidence override. Mirrors `imgedge.voters.base` (salience deferred). |
| [`classify.mjs`](classify.mjs) | Browser glue: decode + resize (canvas) → run each model (ORT injected, not imported) → combine. `classifyBlobEnsemble` runs iNat + timm + the optional deit3 voter; validated end-to-end in a real browser. |
| [`inat_web.json`](inat_web.json) / [`timm_web.json`](timm_web.json) / [`deit3_web.json`](deit3_web.json) | Generated metadata (input config + class indices) so the extension never ships the taxonomy or ImageNet labels. `deit3_web.json` configures the optional third voter. |
| [`offscreen.mjs`](offscreen.mjs) + [`offscreen.html`](offscreen.html) | The offscreen document: hosts the ORT sessions (WASM, multi-threaded when cross-origin isolated) and answers classify requests from the service worker. MV3 workers can't keep a model warm; this does. |
| `vendor/` | The bundled `inat.onnx` + `timm.onnx` (+ optional `deit3.onnx`) + ONNX Runtime Web, populated by `tools/bundle_inbrowser.py`. Git-ignored — not committed. |

**How it's wired:** when the server is unreachable (`inBrowserFallback`, on by
default) or `inBrowserOnly` is set, `background.js` creates the
[offscreen document](https://developer.chrome.com/docs/extensions/reference/api/offscreen)
and delegates classification to it — deduped and cached per URL, and serialized
so a busy session isn't mistaken for a hung one. `manifest.json` grants the
`offscreen` permission, a `'wasm-unsafe-eval'` CSP, and the COOP/COEP keys that
make the offscreen document cross-origin isolated so WASM threads engage.

**Building the bundle** (models are git-ignored, not committed):

```
python src/imgedge/inat/convert_to_onnx.py   # iNat -> ONNX
python tools/convert_timm_to_onnx.py         # timm -> int8 ONNX (needs timm + torch)
python tools/convert_timm_to_onnx.py --model deit3_small_patch16_224 --out src/imgedge/voters/models/deit3.onnx  # optional 3rd voter
python tools/bundle_inbrowser.py             # copy models + ORT Web into vendor/
```

**Deferred** (see the [roadmap follow-ups](../../docs/roadmap.md)): the salience
multiplier (currently `1.0` in `ensemble.mjs`) and timm center-crop parity
(currently a 224² stretch).

## Parity

The pure modules re-implement the Python pre/post-processing, so the two sides
must stay in lock-step. Node tests and pytest assert against committed fixtures:

- iNat: [`tests/js/inbrowser_parity.test.mjs`](../../tests/js/inbrowser_parity.test.mjs) + [`tests/test_inbrowser_parity.py`](../../tests/test_inbrowser_parity.py) (fixture [`inat_parity.json`](../../tests/js/fixtures/inat_parity.json))
- timm + ensemble: [`tests/js/timm_parity.test.mjs`](../../tests/js/timm_parity.test.mjs) + [`tests/test_timm_parity.py`](../../tests/test_timm_parity.py) (fixture [`timm_parity.json`](../../tests/js/fixtures/timm_parity.json))

Run with `npm test` (Node) and `pytest` (Python).

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
