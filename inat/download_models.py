"""Download the iNaturalist vision model + taxonomy from the model-files release.

These assets come from https://github.com/inaturalist/model-files/releases and
are subject to iNaturalist's terms — check the repo's license before
redistributing. For local/personal use this just fetches them into ./models.

Example:
  python download_models.py                 # vision model + taxonomy (default)
  python download_models.py --all           # also geomodel + common names
"""

import argparse
import sys
import urllib.request
from pathlib import Path

RELEASE = "https://github.com/inaturalist/model-files/releases/download/v25.01.15"

# name -> (filename, default?)
ASSETS = {
    "vision": ("INatVision_Small_2_fact256_8bit.tflite", True),
    "taxonomy_csv": ("taxonomy.csv", True),
    "taxonomy_json": ("taxonomy.json", True),
    "geomodel": ("INatGeomodel_Small_2_8bit.tflite", False),
    "common_names": ("commonNames.tar.gz", False),
}


def download(url, dest):
    print(f"-> {dest.name}", end=" ", flush=True)
    if dest.exists():
        print("(already present, skipping)")
        return
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(url) as resp, open(tmp, "wb") as out:
            total = int(resp.headers.get("Content-Length", 0))
            read = 0
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                out.write(chunk)
                read += len(chunk)
                if total:
                    pct = read * 100 // total
                    print(f"\r-> {dest.name}  {pct:3d}%", end="", flush=True)
        tmp.replace(dest)
        print(f"\r-> {dest.name}  done ({read // 1024} KB)")
    except Exception as e:
        if tmp.exists():
            tmp.unlink()
        print(f"\r-> {dest.name}  FAILED: {e}")
        raise


def main():
    p = argparse.ArgumentParser(description="Download iNaturalist model assets.")
    p.add_argument("--out", default="models", help="output directory")
    p.add_argument("--all", action="store_true", help="also fetch geomodel + common names")
    args = p.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    selected = [a for a in ASSETS.values() if a[1] or args.all]
    for filename, _ in selected:
        download(f"{RELEASE}/{filename}", out_dir / filename)

    print(f"\nDone. Files in: {out_dir.resolve()}")
    print("Next: python inat_vision.py <image> --model models/"
          "INatVision_Small_2_fact256_8bit.tflite --taxonomy models/taxonomy.csv")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(1)
