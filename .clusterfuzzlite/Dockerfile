# ClusterFuzzLite build image for the image-decode fuzzers.
# https://google.github.io/clusterfuzzlite/build-integration/python/
# Pinned by digest for reproducible fuzz builds (OpenSSF Scorecard
# Pinned-Dependencies): base-builder-python resolved 2026-07-04 — bump the
# digest periodically to pick up base-image updates.
FROM gcr.io/oss-fuzz-base/base-builder-python@sha256:51a7caaecdc0b814dd32ad272eab7ca4a40c134cecd38294f2aabb9e32adcb4f

# The OSS-Fuzz base image ships Python 3.11, but the project pins numpy / Pillow
# versions that only publish 3.12+ wheels. The decode fuzzer needs only Pillow +
# numpy (inat_filter imports the TFLite runtime lazily, and the fuzzer never hits
# it), so install 3.11-compatible wheels and add the package itself without its
# pinned deps.
COPY . $SRC/imgedge
WORKDIR $SRC/imgedge
RUN pip3 install --no-cache-dir "numpy<2.3" "pillow<12" && \
    pip3 install --no-deps --ignore-requires-python .

COPY .clusterfuzzlite/build.sh $SRC/
