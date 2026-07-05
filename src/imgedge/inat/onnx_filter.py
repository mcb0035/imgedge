# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""ONNX Runtime backend for the iNaturalist vision model — runs on GPU/NPU.

Reuses the taxonomy mask, decode hardening, and pre/post-processing from
inat_filter. It selects an execution provider, defaulting to the Intel NPU
(OpenVINO) when present, then GPU, then CPU. ONNX Runtime sessions are
thread-safe for concurrent Run(), so one session serves every request thread.

Get an ONNX model first:   python convert_to_onnx.py
Install a runtime + provider, e.g.:
  pip install onnxruntime-openvino   # Intel NPU / GPU  (server default: NPU)
  pip install onnxruntime-directml   # any DX12 GPU (NVIDIA / Intel / AMD)
  pip install onnxruntime-gpu        # NVIDIA CUDA
"""

import numpy as np
import onnxruntime as ort  # type: ignore

from imgedge.inat.inat_filter import (
    DEFAULT_TARGET,
    build_mask,
    open_guarded,
    postprocess,
    prep_input,
)

_OV = "OpenVINOExecutionProvider"
_CUDA = "CUDAExecutionProvider"
_DML = "DmlExecutionProvider"
_CPU = "CPUExecutionProvider"


def _candidates(ep):
    """Ordered list of (provider, options, label) to try, given an EP preference."""
    avail = set(ort.get_available_providers())
    ep = (ep or "auto").lower()
    out = []

    def ov(device, label):
        if _OV in avail:
            out.append((_OV, {"device_type": device}, label))

    def plain(provider, label):
        if provider in avail:
            out.append((provider, {}, label))

    if ep in ("npu", "openvino-npu"):
        ov("NPU", "NPU (OpenVINO)")
    elif ep in ("ovgpu", "openvino-gpu"):
        ov("GPU", "GPU (OpenVINO)")
    elif ep == "cuda":
        plain(_CUDA, "GPU (CUDA)")
    elif ep == "dml":
        plain(_DML, "GPU/NPU (DirectML)")
    elif ep == "cpu":
        pass
    else:  # auto: NPU first (if present), then GPU options, then CPU
        ov("NPU", "NPU (OpenVINO)")
        ov("GPU", "GPU (OpenVINO)")
        plain(_CUDA, "GPU (CUDA)")
        plain(_DML, "GPU/NPU (DirectML)")
    out.append((_CPU, {}, "CPU (ONNX)"))
    return out


def _dim(value, default):
    return int(value) if isinstance(value, int) and value > 0 else default


class OnnxTaxonFilter:
    """ONNX backend; mirrors TaxonFilter's interface (score_bytes, match_count)."""

    backend = "onnx"

    def __init__(self, model_path, taxonomy_csv, target=DEFAULT_TARGET, ep="auto"):
        self.session = None
        self.provider = None
        last_err = None
        for provider, options, label in _candidates(ep):
            try:
                providers = [(provider, options)] if options else [provider]
                session = ort.InferenceSession(str(model_path), providers=providers)
                if provider not in session.get_providers():
                    raise RuntimeError(f"{provider} did not bind ({session.get_providers()})")
                self.session = session
                self.provider = label
                break
            except Exception as e:  # provider/device unusable -> try the next one
                last_err = e
                self.session = None
        if self.session is None:
            raise RuntimeError(f"no usable ONNX execution provider ({last_err})")

        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        shape = list(inp.shape)
        # TFLite-origin models are NHWC [1, H, W, 3]; tolerate NCHW [1, 3, H, W] too.
        self._nhwc = len(shape) == 4 and shape[-1] == 3
        if self._nhwc:
            self._h, self._w = _dim(shape[1], 224), _dim(shape[2], 224)
        else:
            self._h, self._w = _dim(shape[2], 224), _dim(shape[3], 224)
        self._uint8 = inp.type == "tensor(uint8)"
        self.target = target
        self.mask = build_mask(taxonomy_csv, target)
        self.match_count = int(self.mask.sum())

    def score(self, img):
        data = prep_input(img, self._h, self._w, self._uint8)  # NHWC batch of 1
        if not self._nhwc:
            data = np.transpose(data, (0, 3, 1, 2))  # -> NCHW
        out = self.session.run(None, {self.input_name: data})[0][0]
        return postprocess(out, self.mask)

    def score_bytes(self, raw):
        with open_guarded(raw) as img:
            return self.score(img)
