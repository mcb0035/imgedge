# ClusterFuzzLite build image for the image-decode fuzzers.
# https://google.github.io/clusterfuzzlite/build-integration/python/
FROM gcr.io/oss-fuzz-base/base-builder-python

# Install the package + its runtime deps (numpy / Pillow / ai-edge-litert) so the
# harness can import the decode path. The OSS-Fuzz base image ships Python 3.11
# while the project floor is 3.13, so ignore the Requires-Python gate -- the
# decode path uses no >=3.12 syntax, so it imports fine on 3.11.
COPY . $SRC/imgedge
WORKDIR $SRC/imgedge
RUN pip3 install --ignore-requires-python .

COPY .clusterfuzzlite/build.sh $SRC/
