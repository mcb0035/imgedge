#!/bin/bash -eu
# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
# Compile every Python fuzz harness in fuzz/ into a standalone libFuzzer target.
for harness in "$SRC"/imgedge/fuzz/*_fuzzer.py; do
  compile_python_fuzzer "$harness"
done
