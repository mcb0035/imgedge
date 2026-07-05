// Copyright the ImgEdge contributors.
// SPDX-License-Identifier: Apache-2.0
// Parity for the in-browser timm voter + ensemble: assert the JS core against
// the same fixture the Python test uses (Python is the source of truth).

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { toTimmInput, softmax, arachnidEvidence, evidenceFromLogits } from "../../extension/inbrowser/timm.mjs";
import { combineEvidence } from "../../extension/inbrowser/ensemble.mjs";

const fixture = JSON.parse(
  readFileSync(fileURLToPath(new URL("./fixtures/timm_parity.json", import.meta.url)), "utf8"),
);
const TOL = fixture.tolerance;

test("toTimmInput matches ImageNet mean/std NCHW normalization", () => {
  const { rgba, width, height, mean, std, expected_nchw } = fixture.preprocess;
  const got = toTimmInput(Uint8ClampedArray.from(rgba), width, height, { mean, std });
  assert.equal(got.length, expected_nchw.length);
  for (let i = 0; i < expected_nchw.length; i++) {
    assert.ok(Math.abs(got[i] - expected_nchw[i]) <= TOL, `nchw[${i}]: ${got[i]} vs ${expected_nchw[i]}`);
  }
});

test("evidenceFromLogits matches the Python softmax + signed evidence", () => {
  const { logits, block_indices, contrast_indices, contrast_weight, expected_evidence } = fixture.evidence;
  const got = evidenceFromLogits(Float32Array.from(logits), block_indices, contrast_indices, contrast_weight);
  assert.ok(Math.abs(got - expected_evidence) <= TOL, `${got} vs ${expected_evidence}`);
});

test("softmax + arachnidEvidence equals evidenceFromLogits", () => {
  const { logits, block_indices, contrast_indices, contrast_weight, expected_evidence } = fixture.evidence;
  const probs = softmax(Float32Array.from(logits));
  const got = arachnidEvidence(probs, block_indices, contrast_indices, contrast_weight);
  assert.ok(Math.abs(got - expected_evidence) <= TOL, `${got} vs ${expected_evidence}`);
});

test("combineEvidence matches the Python ensemble (evidence + iNat override)", () => {
  const { threshold, inat_override, cases } = fixture.ensemble;
  for (const c of cases) {
    const { score, block } = combineEvidence(c.rows, { threshold, inatOverride: inat_override });
    assert.ok(Math.abs(score - c.expected_score) <= TOL, `score ${score} vs ${c.expected_score}`);
    assert.equal(block, c.expected_block);
  }
});
