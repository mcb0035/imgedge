// Copyright the ImgEdge contributors.
// SPDX-License-Identifier: Apache-2.0
/* global ort */
// Phase 0 feasibility spike (see ./README.md). Loads inat.onnx under ONNX
// Runtime Web, feeds a randomly-filled tensor of the model's own input shape,
// and reports which execution provider ran plus p50/p90 inference latency. No
// image or dataset is used: this measures "does it run + how fast", not accuracy.

const out = document.getElementById("out");
const log = (msg) => {
  out.textContent += "\n" + msg;
};

const MODEL_URL = "inat.onnx";
const WARMUP = 3;
const ITERS = 20;
// iNat ONNX input is NHWC float32 [batch, 299, 299, 3] (batch dim is dynamic).
// Set to null to instead read the shape from the model's input metadata.
const INPUT_SHAPE = [1, 299, 299, 3];

async function makeSession() {
  ort.env.wasm.wasmPaths = "./"; // .wasm copied next to index.html
  for (const ep of ["webgpu", "wasm"]) {
    try {
      const session = await ort.InferenceSession.create(MODEL_URL, {
        executionProviders: [ep],
      });
      return { session, ep };
    } catch (e) {
      log(`EP ${ep} unavailable: ${e.message || e}`);
    }
  }
  throw new Error("no execution provider could create the session");
}

function inputDims(session, name) {
  if (INPUT_SHAPE) return INPUT_SHAPE;
  const meta = session.inputMetadata ? session.inputMetadata[name] : null;
  const dims = meta && meta.dimensions ? meta.dimensions : [1, 3, 224, 224];
  // Dynamic axes may be -1/0/strings; default those to 1.
  return dims.map((d) => (typeof d === "number" && d > 0 ? d : 1));
}

function randomFeeds(session) {
  const feeds = {};
  for (const name of session.inputNames) {
    const dims = inputDims(session, name);
    const size = dims.reduce((a, b) => a * b, 1);
    const data = Float32Array.from({ length: size }, () => Math.random());
    feeds[name] = new ort.Tensor("float32", data, dims);
    log(`input ${name}: [${dims.join(", ")}]`);
  }
  return feeds;
}

function percentile(sorted, p) {
  const i = Math.min(sorted.length - 1, Math.floor((p / 100) * sorted.length));
  return sorted[i];
}

async function main() {
  out.textContent = `ORT Web ${ort.env.versions ? ort.env.versions.common : "?"}`;
  const { session, ep } = await makeSession();
  log(`execution provider: ${ep}`);
  log(`outputs: ${session.outputNames.join(", ")}`);

  const feeds = randomFeeds(session);
  for (let i = 0; i < WARMUP; i++) await session.run(feeds);

  const times = [];
  for (let i = 0; i < ITERS; i++) {
    const t0 = performance.now();
    const result = await session.run(feeds);
    times.push(performance.now() - t0);
    if (i === 0) {
      const first = result[session.outputNames[0]];
      log(`output[0] shape: [${first.dims.join(", ")}]`);
    }
  }
  times.sort((a, b) => a - b);
  log(`\nlatency over ${ITERS} runs (${ep}):`);
  log(`  p50 ${percentile(times, 50).toFixed(1)} ms`);
  log(`  p90 ${percentile(times, 90).toFixed(1)} ms`);
  log(`  min ${times[0].toFixed(1)} ms   max ${times[times.length - 1].toFixed(1)} ms`);
}

main().catch((e) => log(`\nFAILED: ${e.message || e}\n${e.stack || ""}`));
