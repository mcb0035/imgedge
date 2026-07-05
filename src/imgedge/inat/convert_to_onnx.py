# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""Convert the iNaturalist vision TFLite model to ONNX for GPU/NPU inference.

Requires (in addition to the model download):
  pip install tf2onnx onnx tensorflow

Run:
  python convert_to_onnx.py
Then the server auto-uses the ONNX backend (GPU/NPU) whenever onnxruntime and
an execution provider are installed. Verify parity afterwards, e.g.:
  python inat_vision.py <a spider photo>           # TFLite top taxon
  # the server's /health shows the active provider once running.
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TFLITE = HERE / "models" / "INatVision_Small_2_fact256_8bit.tflite"
ONNX = HERE / "models" / "INatVision_Small_2_fact256_8bit.onnx"


def main():
    if not TFLITE.exists():
        sys.exit(f"TFLite model not found: {TFLITE}\nRun: python download_models.py")
    cmd = [
        sys.executable,
        "-m",
        "tf2onnx.convert",
        "--tflite",
        str(TFLITE),
        "--output",
        str(ONNX),
        "--opset",
        "17",
    ]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"Wrote {ONNX}")
    print("The server will now prefer the ONNX backend (set IMGEDGE_EP to pick a provider).")


if __name__ == "__main__":
    main()
