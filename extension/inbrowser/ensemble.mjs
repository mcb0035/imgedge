// Copyright the ImgEdge contributors.
// SPDX-License-Identifier: Apache-2.0
/**
 * Pure evidence-combining core for the in-browser ensemble.
 *
 * Mirrors imgedge.voters.base `_combine` / `_evidence_verdict`: sum the signed,
 * weight-scaled evidence from each voter (positive pushes toward block, negative
 * pulls away), clamp to [0, 1], then apply the iNat-confidence override. The
 * salience multiplier is intentionally deferred (treated as 1.0 here) and will
 * be ported separately; see docs/roadmap.md Phase 2.
 */

/**
 * @typedef {Object} VoterRow
 * @property {number} weight   - the voter's ensemble weight
 * @property {number} evidence - signed evidence (positive = toward block)
 * @property {boolean} [isInat] - true for the iNat voter (drives the override)
 * @property {number} [score]   - the iNat score in [0,1] (for the override)
 */

/**
 * Combine voter rows into a final score + block decision.
 *
 * @param {VoterRow[]} rows
 * @param {{threshold: number, inatOverride?: number}} opts
 * @returns {{score: number, block: boolean}}
 */
export function combineEvidence(rows, { threshold, inatOverride = 0.9 }) {
  let pos = 0;
  let neg = 0;
  for (const r of rows) {
    const we = r.weight * r.evidence;
    if (r.evidence > 0) pos += we;
    else if (r.evidence < 0) neg += we;
  }
  // Salience multiplier is deferred (= 1.0); combined = clamp(pos + neg, 0, 1).
  let combined = Math.max(0, Math.min(1, pos + neg));
  const inat = rows.find((r) => r.isInat);
  const inatScore = inat && typeof inat.score === "number" ? inat.score : null;
  const override = inatScore !== null && inatScore >= inatOverride;
  if (override) combined = Math.max(combined, inatScore);
  return { score: combined, block: override || combined >= threshold };
}
