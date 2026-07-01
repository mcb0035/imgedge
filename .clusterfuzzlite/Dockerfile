# ClusterFuzzLite build image for the image-decode fuzzers.
# https://google.github.io/clusterfuzzlite/build-integration/python/
FROM gcr.io/oss-fuzz-base/base-builder-python

# Install the package + its runtime deps (numpy / Pillow / ai-edge-litert) so the
# harness can import the decode path.
COPY . $SRC/imgedge
WORKDIR $SRC/imgedge
RUN pip3 install .

COPY .clusterfuzzlite/build.sh $SRC/
