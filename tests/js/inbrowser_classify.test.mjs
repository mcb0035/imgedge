// Copyright the ImgEdge contributors.
// SPDX-License-Identifier: Apache-2.0
import test from "node:test";
import assert from "node:assert/strict";

import { runModel, tooSmallToClassify, MIN_CLASSIFY_DIM } from "../../extension/inbrowser/classify.mjs";

test("runModel feeds an NHWC float32 tensor under the model's input name", async () => {
  const meta = { input: { height: 2, width: 2 } };
  const input = Float32Array.from([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]); // 2*2*3
  const outData = Float32Array.from([0.1, 0.2, 0.3]);

  let seen = null;
  const ort = {
    Tensor: class {
      constructor(type, data, dims) {
        this.type = type;
        this.data = data;
        this.dims = dims;
      }
    },
  };
  const session = {
    inputNames: ["serving_default_input_1:0"],
    outputNames: ["StatefulPartitionedCall:0"],
    run: async (feeds) => {
      seen = feeds;
      return { "StatefulPartitionedCall:0": { data: outData } };
    },
  };

  const out = await runModel(ort, session, meta, input);
  assert.equal(out, outData); // returns the named output's data

  const tensor = seen["serving_default_input_1:0"];
  assert.equal(tensor.type, "float32");
  assert.deepEqual(tensor.dims, [1, 2, 2, 3]);
  assert.equal(tensor.data, input);
});

test("tooSmallToClassify flags placeholders and tiny images", () => {
  assert.equal(tooSmallToClassify(1, 1), true); // 1x1 lazy-load placeholder
  assert.equal(tooSmallToClassify(MIN_CLASSIFY_DIM - 1, 500), true);
  assert.equal(tooSmallToClassify(500, MIN_CLASSIFY_DIM - 1), true);
  assert.equal(tooSmallToClassify(MIN_CLASSIFY_DIM, MIN_CLASSIFY_DIM), false);
  assert.equal(tooSmallToClassify(800, 600), false);
});
