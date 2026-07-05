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
  **~447 ms p50 on the WASM fallback**. The biggest unknown is resolved — proceed
  to Phase 1.
- **Phase 1 — iNat-only Fast:** a single model in an offscreen document; verdict =
  iNat score vs. threshold; `content.js` falls back to in-browser when no server
  is reachable. Ships zero-install filtering.
- **Phase 2 — add the timm voter:** two-model Fast using the evidence policy
  ported to JS, parity-tested against the Python pipeline on synthetic images.
- **Phase 3 — polish:** WebGPU path, per-URL verdict cache, preset/health UX,
  bundle-size trimming, and `NOTICE` attribution for the bundled models.

### Key risks

- ~~Quantized-operator support in ORT Web WASM~~ — **cleared in Phase 0** (the
  model runs cleanly on both the WASM and WebGPU execution providers).
- Preprocessing / normalization parity between JS and Python (guarded by a parity
  test on synthetic images).
- Maintaining the ensemble in two languages (mitigated by shared constants +
  parity tests).
- WASM threading needs cross-origin isolation; plan for single-thread + SIMD as
  the baseline.

## Potential improvements (unscheduled)

- **Ensemble distillation.** Pseudo-label a large unlabeled web set with the
  current 4-model ensemble, then train a small **student** model — a fast, single
  bundle-able classifier that inherits the open-vocab voters' generalization
  (fits the `training/` scaffold). The strongest path to a good in-browser model.
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
