// Copyright the ImgEdge contributors.
// SPDX-License-Identifier: Apache-2.0
// Verify the in-browser ensemble runs the iNat voter plus every present
// timm-style voter (the timm model + the optional deit3 third voter) and folds
// them all into the combined verdict. createImageBitmap + OffscreenCanvas are
// polyfilled so the browser glue runs in Node, and ORT is faked to return
// canned per-model outputs -- the verdict then depends only on the outputs and
// each voter's config, which is exactly the wiring under test (the decode /
// resize / preprocess math is covered by the parity tests).

import test from "node:test";
import assert from "node:assert/strict";

import { classifyBlobEnsemble } from "../../extension/inbrowser/classify.mjs";
import { targetScore } from "../../extension/inbrowser/inat.mjs";
import { evidenceFromLogits } from "../../extension/inbrowser/timm.mjs";
import { combineEvidence } from "../../extension/inbrowser/ensemble.mjs";

globalThis.createImageBitmap = async () => ({ width: 64, height: 64, close() {} });
globalThis.OffscreenCanvas = class {
  constructor(w, h) {
    this.width = w;
    this.height = h;
  }
  getContext() {
    return {
      imageSmoothingEnabled: false,
      imageSmoothingQuality: "",
      drawImage() {},
      getImageData: (x, y, w, h) => ({ data: new Uint8ClampedArray(w * h * 4) }),
    };
  }
};

const fakeOrt = () => ({ Tensor: class {} });

// A voter whose session ignores its input tensor and returns `out`; `runs`
// counts invocations so a test can assert the voter actually ran.
function voter(meta, out) {
  const session = {
    inputNames: ["input"],
    outputNames: ["out"],
    runs: 0,
    run() {
      session.runs++;
      return Promise.resolve({ out: { data: out } });
    },
  };
  return { session, meta, out };
}

const inat = () =>
  voter(
    { input: { width: 64, height: 64, divisor: 255, offset: 0 }, arachnida_leaf_indices: [1] },
    Float32Array.from([0.1, 0.6, 0.2]),
  );
const timm = () =>
  voter(
    {
      input: { width: 64, height: 64, layout: "NCHW", mean: [0.5, 0.5, 0.5], std: [0.5, 0.5, 0.5], crop_pct: 0.875 },
      block_indices: [0],
      contrast_indices: [2],
      contrast_weight: 0,
      weight: 0.5,
    },
    Float32Array.from([2.0, 0.0, 1.0]),
  );
const deit3 = () =>
  voter(
    {
      input: { width: 64, height: 64, layout: "NCHW", mean: [0.5, 0.5, 0.5], std: [0.5, 0.5, 0.5], crop_pct: 0.9 },
      block_indices: [0],
      contrast_indices: [2],
      contrast_weight: 0,
      weight: 0.75,
    },
    Float32Array.from([1.0, 0.0, 0.5]),
  );

const THRESHOLD = 0.15;

// Recompute the expected verdict from the same pure functions the ensemble
// uses, so the test tracks the real math rather than a hard-coded number.
function expected(models) {
  const ev = targetScore(models.inat.out, models.inat.meta.arachnida_leaf_indices);
  const rows = [{ weight: 1.0, evidence: ev, isInat: true, score: ev }];
  for (const key of ["timm", "deit3"]) {
    const v = models[key];
    if (!v) continue;
    const e = evidenceFromLogits(v.out, v.meta.block_indices, v.meta.contrast_indices, v.meta.contrast_weight);
    rows.push({ weight: v.meta.weight, evidence: e });
  }
  return combineEvidence(rows, { threshold: THRESHOLD });
}

test("classifyBlobEnsemble folds in iNat + timm + deit3 when all are present", async () => {
  const models = { inat: inat(), timm: timm(), deit3: deit3() };
  const { score, blocked } = await classifyBlobEnsemble(fakeOrt(), models, new Blob(), THRESHOLD);
  const exp = expected(models);
  assert.ok(Math.abs(score - exp.score) <= 1e-9, `score ${score} vs ${exp.score}`);
  assert.equal(blocked, exp.block);
  assert.equal(models.inat.session.runs, 1);
  assert.equal(models.timm.session.runs, 1);
  assert.equal(models.deit3.session.runs, 1);
});

test("classifyBlobEnsemble runs without deit3 (backward compatible 2-voter path)", async () => {
  const models = { inat: inat(), timm: timm(), deit3: null };
  const { score } = await classifyBlobEnsemble(fakeOrt(), models, new Blob(), THRESHOLD);
  assert.ok(Math.abs(score - expected(models).score) <= 1e-9);
  assert.equal(models.timm.session.runs, 1);
});
