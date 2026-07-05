// Copyright the ImgEdge contributors.
// SPDX-License-Identifier: Apache-2.0
/**
 * Pure, environment-agnostic core of the in-browser timm (ImageNet) voter.
 *
 * Mirrors imgedge.voters.timm_voter: normalize RGB with ImageNet mean/std into
 * an NCHW tensor, softmax the model's logits, then contribute *signed* evidence
 * = P(arachnid classes) - contrast_weight * P(look-alike classes). No DOM /
 * canvas / ONNX Runtime here, so it runs unchanged in a Node test and in the
 * offscreen document. Constants live in timm_web.json (tools/export_timm_web.py).
 */

/**
 * Convert RGBA pixel bytes for a width*height image into the model's NCHW
 * float32 input: `(value / 255 - mean[c]) / std[c]` over RGB, alpha dropped.
 * Channels are planar (all R, then all G, then all B) to match [1, 3, H, W].
 *
 * @param {Uint8ClampedArray|Uint8Array|number[]} rgba - length width*height*4
 * @param {number} width
 * @param {number} height
 * @param {{mean: number[], std: number[]}} opts - ImageNet mean/std (length 3)
 * @returns {Float32Array} length width*height*3, NCHW (planar) order
 */
export function toTimmInput(rgba, width, height, { mean, std }) {
  const n = width * height;
  const out = new Float32Array(3 * n);
  for (let p = 0, i = 0; i + 3 < rgba.length; i += 4, p++) {
    out[p] = (rgba[i] / 255 - mean[0]) / std[0];
    out[n + p] = (rgba[i + 1] / 255 - mean[1]) / std[1];
    out[2 * n + p] = (rgba[i + 2] / 255 - mean[2]) / std[2];
  }
  return out;
}

/**
 * Numerically stable softmax over a logit vector.
 *
 * @param {Float32Array|number[]} logits
 * @returns {Float32Array}
 */
export function softmax(logits) {
  let max = -Infinity;
  for (let i = 0; i < logits.length; i++) {
    if (logits[i] > max) max = logits[i];
  }
  const out = new Float32Array(logits.length);
  let sum = 0;
  for (let i = 0; i < logits.length; i++) {
    const e = Math.exp(logits[i] - max);
    out[i] = e;
    sum += e;
  }
  if (sum > 0) {
    for (let i = 0; i < out.length; i++) out[i] /= sum;
  }
  return out;
}

function sumAt(probs, indices) {
  let s = 0;
  for (let k = 0; k < indices.length; k++) {
    const idx = indices[k];
    if (idx >= 0 && idx < probs.length) s += probs[idx];
  }
  return s;
}

/**
 * Signed evidence from a probability vector: `P(block) - contrastWeight *
 * P(contrast)`. Mirrors imgedge.voters.timm_voter.assess.
 *
 * @param {Float32Array|number[]} probs - softmaxed probabilities
 * @param {number[]} blockIndices
 * @param {number[]} contrastIndices
 * @param {number} [contrastWeight]
 * @returns {number}
 */
export function arachnidEvidence(probs, blockIndices, contrastIndices, contrastWeight = 0) {
  return sumAt(probs, blockIndices) - contrastWeight * sumAt(probs, contrastIndices);
}

/**
 * Convenience: raw logits -> signed evidence (softmax then arachnidEvidence).
 *
 * @param {Float32Array|number[]} logits
 * @param {number[]} blockIndices
 * @param {number[]} contrastIndices
 * @param {number} [contrastWeight]
 * @returns {number}
 */
export function evidenceFromLogits(logits, blockIndices, contrastIndices, contrastWeight = 0) {
  return arachnidEvidence(softmax(logits), blockIndices, contrastIndices, contrastWeight);
}
