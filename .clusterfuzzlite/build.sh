#!/bin/bash -eu
# Compile every Python fuzz harness in fuzz/ into a standalone libFuzzer target.
for harness in "$SRC"/imgedge/fuzz/*_fuzzer.py; do
  compile_python_fuzzer "$harness"
done
