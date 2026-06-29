# Third-party notices & model-licensing policy

ImgEdge itself is licensed under **Apache-2.0** (see [LICENSE](LICENSE)). This
file (1) attributes the third-party models and libraries it uses, and (2) is the
**checklist to follow before adding any new model** — so the project stays
license-clean as it grows.

> Not legal advice. License names below are from each project's own metadata;
> verify the upstream `LICENSE`/model card before relying on them, and get
> proper counsel before any **commercial** distribution.

---

## Models used (downloaded at runtime — NOT redistributed in this repo)

The model files live under a git-ignored `models/` directory; the server fetches
them over HTTPS and verifies a pinned SHA-256. Each remains under its own license.

| Model | Source | License | Copyright |
|---|---|---|---|
| iNaturalist vision model + taxonomy (`INatVision_Small_*`, `taxonomy.*`) | [github.com/inaturalist/model-files](https://github.com/inaturalist/model-files) (release `v25.01.15`) | **MIT** | © iNaturalist |
| timm MobileNetV3 (`mobilenetv3_large_100.ra_in1k`) — optional voter | [huggingface.co/timm/mobilenetv3_large_100.ra_in1k](https://huggingface.co/timm/mobilenetv3_large_100.ra_in1k) | **Apache-2.0** | © Ross Wightman / Hugging Face |

Training-data note: the timm model is trained on **ImageNet-1k**, whose *dataset*
terms lean research/non-commercial. The *weights* are Apache-2.0 and fine for
personal/open-source use — but flag this before any commercial deployment (see
"weights ≠ training data" below).

## Python libraries (all permissive)

numpy (BSD-3-Clause) · Pillow (HPND) · ai-edge-litert / LiteRT (Apache-2.0) ·
torch (BSD-3-Clause, optional) · timm (Apache-2.0, optional) ·
onnxruntime (MIT, optional). None are copyleft or non-commercial.

---

## Adding a model? Read this first.

The project is Apache-2.0 (permissive, OSI open-source). To keep it that way and
avoid license conflicts, a new model's license must be **compatible**. When in
doubt, prefer a permissively-licensed model and record the decision here.

### ✅ Allowed — permissive (use freely, with attribution)
`MIT` · `BSD-2-Clause` / `BSD-3-Clause` · `Apache-2.0` · `ISC` · `Unlicense` /
`CC0` · `CC-BY-4.0` (attribution only). Add the model to the table above and
you're done.

### ⛔ Off-limits — do **not** add without an explicit, documented owner decision
- **Non-commercial** — `CC-BY-NC*`, "non-commercial", "research/academic only",
  "evaluation only". These forbid commercial use and make the project no longer
  open-source.
- **Copyleft / share-alike** — `GPL-2.0`/`3.0`, **`AGPL-3.0`**, `LGPL`, any
  `CC-*-SA`, `MPL-2.0`, `EUPL`. These force source-disclosure / share-alike on
  combined works; GPL/AGPL are **incompatible with Apache-2.0** as one work
  (AGPL is especially viral for a network service).
- **Use-restricted "open" / vendor licenses** — `OpenRAIL` / `RAIL`,
  `CreativeML OpenRAIL-M`, the **Llama** community license, **Gemma** terms, and
  similar "community"/"acceptable-use" licenses. These are *not* OSI-open: they
  add field-of-use bans, acceptable-use policies, or user/revenue thresholds.
- **No-redistribution / gated / unknown** — weights you can't redistribute,
  gated Hugging Face models, or **any model with no stated license** (no license
  = all rights reserved → do not use).

### ⚠️ Watch-outs (true even for permissively-licensed models)
- **Weights license ≠ training-data license.** A model can be MIT/Apache yet be
  trained on restrictively-licensed data (ImageNet's research terms, CC-BY-NC or
  scraped data). For commercial use, data provenance is a real gray area —
  prefer models trained on permissive data.
- **"Open weights" ≠ "open source."** Many "open" models carry use restrictions.
- **Patent grants differ.** Apache-2.0 grants patent rights; MIT/BSD don't
  (lower but non-zero patent exposure).

### Checklist before merging a new model
1. Find the model's license (its repo `LICENSE` or HF model card). **None → stop.**
2. Confirm it's in the ✅ list. If it's ⛔ / ⚠️ → get an explicit owner decision and note it here.
3. If commercial use is possible, check the **training-data** provenance too.
4. Add a row to **Models used** above: name, source URL, **version/commit**, license, copyright.
5. Keep the weights **out of the repo** — git-ignored, downloaded + SHA-256-verified at runtime.
6. If you ever *bundle* an Apache-2.0 component, copy its required `NOTICE` lines into our `NOTICE`.
