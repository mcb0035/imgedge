# Phase 0 spike — in-browser inference feasibility

Throwaway feasibility spike for the [in-browser Fast mode](../../docs/roadmap.md).
**Not shipped.** It exists to answer two questions before Phase 1:

1. Does the quantized **iNat ONNX** model load and run under **ONNX Runtime Web**
   (WASM, and WebGPU where available)?
2. What is the per-inference **latency** (WASM vs. WebGPU) on a real machine?

It feeds a **randomly-filled tensor** shaped to the model's own input — no image
and no dataset, so it is arachnophobia-safe and self-contained. Real image
decode / preprocessing is Phase 1.

## Run it

```powershell
cd spike/inbrowser-fast
npm init -y ; npm install onnxruntime-web      # brings ORT Web + its .wasm files
Copy-Item node_modules/onnxruntime-web/dist/ort-wasm-*.* .   # wasm binaries + .mjs loaders, next to index.html
# generate the iNat ONNX (see docs/development.md) and drop it here as inat.onnx
python serve.py 8080                            # static server w/ correct .mjs + .wasm MIME (file:// can't load wasm)
```

Then open <http://localhost:8080/> and read the results panel (and the DevTools
console). `serve.py` is a tiny wrapper around `http.server` that fixes the `.mjs`
MIME type (Windows serves it as `text/plain`, which browsers refuse to import).
On bash/zsh the `cp`/server commands are the same idea.

## What to look for

- **Does it run?** An unsupported-operator error means the quantized export needs
  adjusting for ORT Web — note the op. (If it fails on input *shape*, set the
  shape in `spike.js`.)
- **Latency:** p50 / p90 for the WASM EP, plus WebGPU if your browser/GPU support
  it. That sets the realistic per-image budget for Phase 1.

`inat.onnx`, the `*.wasm` files, and `node_modules/` are git-ignored.
