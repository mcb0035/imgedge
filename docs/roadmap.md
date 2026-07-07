# Roadmap

Aspirational, **non-binding** direction for ImgEdge (current release: 0.4.0).
These are ideas and plans, not commitments or dates — [CHANGELOG.md](../CHANGELOG.md)
is the record of what has actually shipped. Discussion and PRs welcome; see
[CONTRIBUTING.md](../CONTRIBUTING.md).

## In-browser "Fast" mode (no local server)

**Goal:** run the small, permissively-licensed models **inside the extension** so
users get filtering with **zero install** — no Python server. The local
classifier stays optional, powering the heavier Balanced / Accurate tiers.

**Why it's feasible:** ImgEdge already exports the iNat model to ONNX
(`convert_to_onnx.py`, `onnx_filter.py`), and the two small voters are
redistributable and bundle-able:

| Model | License | Bundle in the package? |
| --- | --- | --- |
| iNat vision (primary) | MIT | ✅ ~21 MB |
| timm `mobilenetv3_large_100.ra_in1k` | Apache-2.0 | ✅ ~6 MB (int8) |
| SigLIP 2 base | Apache-2.0 | ⚠️ ~400 MB — server only |
| MobileCLIP2-S0 | `apple-amlr` (restricted) | ❌ server only |

**Runtime:** [ONNX Runtime Web](https://onnxruntime.ai/docs/tutorials/web/) (WASM
+ WebGPU); models and `.wasm` are bundled in the package (MV3 forbids fetching
executable code at runtime). Inference runs in an **offscreen document** because
the MV3 service worker has no DOM/canvas.

### Phases

- **Phase 0 — feasibility spike ✅ GO** ([`spike/inbrowser-fast/`](../spike/inbrowser-fast/)):
  confirmed the quantized iNat ONNX loads and runs under ORT Web with **no
  unsupported operators**. Measured (2026-07-05, ORT Web 1.27, input NHWC
  `[1, 299, 299, 3]` → output `[1, 507]`): **~8.5 ms p50 on WebGPU** and
  **~447 ms p50 on the WASM fallback**.
- **Phase 1 — iNat-only Fast ✅ shipped:** a single model in an offscreen
  document; verdict = iNat score vs. threshold; `background.js` falls back to
  in-browser when no server is reachable, and an `inBrowserOnly` toggle skips the
  server entirely. Zero-install filtering.
- **Phase 2 — timm voter ✅ shipped:** two-model Fast (iNat + timm) using the
  evidence policy ([`ensemble.mjs`](../extension/inbrowser/ensemble.mjs)) ported
  to JS and parity-tested against the Python pipeline. timm is exported and
  int8-quantized to ~5.4 MB by
  [`tools/convert_timm_to_onnx.py`](../tools/convert_timm_to_onnx.py) and runs
  ~43 ms/image (WASM, 4 threads); the block threshold default is tuned for this
  2-model combo via `tools/tune_inbrowser.py`.
- **Phase 3 — polish (mostly shipped):** ✅ WASM multithreading via cross-origin
  isolation (~140 ms/image), ✅ per-URL verdict cache + in-flight dedup, ✅
  offscreen stability (WASM-only — the headless WebGPU path crashed the
  document), ✅ lean vendor bundle. Remaining: an explicit "Fast (in-browser)"
  preset label in the popup, `NOTICE` attribution for the bundled models, and the
  follow-ups below.

### Key risks

- ~~Quantized-operator support in ORT Web WASM~~ — **cleared in Phase 0** (the
  model runs cleanly on both the WASM and WebGPU execution providers).
- ~~WASM threading needs cross-origin isolation~~ — **resolved:** the extension
  opts in with the `cross_origin_embedder_policy` / `cross_origin_opener_policy`
  manifest keys, so the offscreen document is cross-origin isolated and runs
  multi-threaded WASM. The service worker stays non-isolated, so remote image
  fetches are unaffected.
- Preprocessing / normalization parity between JS and Python — guarded by parity
  tests on synthetic images (iNat, timm, and the ensemble).
- Maintaining the ensemble in two languages — mitigated by shared constants
  (`inat_web.json` / `timm_web.json`) + parity tests.

### Follow-ups (in-browser)

- **Salience (measured — not worth porting yet).** The server scales positive
  evidence by image salience (size / surface kind / photorealism, boost-only);
  the in-browser ensemble uses a flat `1.0`. Measured with `tools/tune_inbrowser.py`
  on the eval reports, applying salience to the 2-model combo is a wash — ±1–2 %,
  dataset-dependent (slightly helps OpenImages, slightly hurts the harder
  iNaturalist set) — so the JS port of `voters/salience.py` isn't worth it for now.
- **timm center-crop (done).** The in-browser timm input now resizes +
  center-crops like timm's ImageNet eval transform (`crop_pct` 0.875) instead of
  a flat stretch, so the model sees the framing it was served on. (iNat keeps a
  stretch — its server preprocessing stretches too, so it was already in parity.)
  `tools/measure_resize.py` quantifies the stretch-vs-crop verdict delta over the
  eval set.

## Potential improvements (unscheduled)

- **Ensemble distillation.** Pseudo-label a large unlabeled web set with the
  current 4-model ensemble, then train a small **student** model — a fast, single
  bundle-able classifier that inherits the open-vocab voters' generalization
  (fits the `training/` scaffold). The strongest path to a good in-browser model.
- **Re-shop the ImageNet voter slot.** The in-browser ensemble's ImageNet
  voter(s) can be compared against other lightweight, permissively-licensed
  ImageNet-1k backbones that may decorrelate better, using
  [`tools/eval_third_voter.py`](../tools/eval_third_voter.py) (holds iNat fixed,
  sweeps a candidate's weight vs. recall/FPR). Candidates worth a head-to-head:
  `convnext_nano` / `convnext_tiny`, `tf_efficientnetv2_b0`, `regnety_016`,
  `resnet26d`, `xcit_tiny_12_p16_224`, `edgenext_small` — all Apache-2.0 / MIT.
  Avoid the Apple `mobilevit*` / `fastvit*` weights (restricted licence, like
  MobileCLIP2). Each is a ~40-minute drop-in.
- **Alt-text as a classification signal.** Fold an image's `alt` / `title` /
  `aria` text into the evidence (a keyword or CLIP-text vote). A logic change —
  weigh evasion and false-positive risk first.
- **More *atypical* training / eval data.** Egg sacs, molts, drawings,
  tiny/partial subjects — the known weak spots.
- **WebGPU / WebNN acceleration** for the in-browser path as browser support
  matures.

> The arachnophobia constraint stays in force throughout: models are trained and
> evaluated only from the AES-encrypted set, decoded in memory and never rendered
> — see [docs/evaluation.md](evaluation.md).
