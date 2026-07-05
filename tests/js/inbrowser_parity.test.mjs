// Copyright the ImgEdge contributors.
// SPDX-License-Identifier: Apache-2.0
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { toModelInput, targetScore, isBlocked } from "../../extension/inbrowser/inat.mjs";

const fixture = JSON.parse(
  readFileSync(fileURLToPath(new URL("./fixtures/inat_parity.json", import.meta.url)), "utf8"),
);
const TOL = fixture.tolerance;

test("toModelInput matches the Python prep_input normalization", () => {
  const { rgba, width, height, divisor, offset, expected_nhwc } = fixture.preprocess;
  const got = toModelInput(Uint8ClampedArray.from(rgba), width, height, { divisor, offset });
  assert.equal(got.length, expected_nhwc.length);
  for (let i = 0; i < expected_nhwc.length; i++) {
    assert.ok(
      Math.abs(got[i] - expected_nhwc[i]) <= TOL,
      `nhwc[${i}]: ${got[i]} vs ${expected_nhwc[i]}`,
    );
  }
});

test("targetScore matches the Python postprocess score", () => {
  const { output, arachnida_leaf_indices, expected_score } = fixture.postprocess;
  const got = targetScore(Float32Array.from(output), arachnida_leaf_indices);
  assert.ok(Math.abs(got - expected_score) <= TOL, `${got} vs ${expected_score}`);
});

test("targetScore returns 0 when no output is positive", () => {
  assert.equal(targetScore(Float32Array.from([-1, 0, -0.2]), [0, 1, 2]), 0);
});

test("isBlocked uses a >= threshold comparison", () => {
  assert.equal(isBlocked(0.5, 0.5), true);
  assert.equal(isBlocked(0.49, 0.5), false);
});
