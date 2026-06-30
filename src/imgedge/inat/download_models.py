"""Download + verify the iNaturalist vision model + taxonomy.

These assets come from https://github.com/inaturalist/model-files/releases and
are subject to iNaturalist's terms — check the repo's license before
redistributing. For local/personal use this just fetches them into inat/models
(next to this script), which is where the classifier server looks by default.

Integrity (why this isn't a "blind download"): every default asset is pinned to
a known-good SHA-256 in CHECKSUMS and verified after download. A file whose hash
doesn't match is deleted and the run aborts, so a tampered release, a MITM, or
the wrong file can never be silently handed to the TFLite interpreter. Transfers
are HTTPS-only and any redirect must stay on a github(usercontent).com host.

Example:
  python download_models.py                 # vision model + taxonomy (verified)
  python download_models.py --verify        # only re-check on-disk files vs. pins
  python download_models.py --print-hashes  # show on-disk SHA-256s (to re-pin)
  python download_models.py --all           # also geomodel + common names (unpinned)
"""

import argparse
import hashlib
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

RELEASE = "https://github.com/inaturalist/model-files/releases/download/v25.01.15"

# name -> (filename, default?)
ASSETS = {
    "vision": ("INatVision_Small_2_fact256_8bit.tflite", True),
    "taxonomy_csv": ("taxonomy.csv", True),
    "taxonomy_json": ("taxonomy.json", True),
    "geomodel": ("INatGeomodel_Small_2_8bit.tflite", False),
    "common_names": ("commonNames.tar.gz", False),
}

# Pinned SHA-256 of each trusted file (filename -> hex digest), captured from the
# v25.01.15 release. An asset with no entry here is refused unless you pass
# --allow-unverified. Re-pin only after vetting new files from a trusted source
# (python download_models.py --print-hashes).
CHECKSUMS = {
    "INatVision_Small_2_fact256_8bit.tflite": "eae277b24efa629b998d5f9c091da0576162cb1aad498786087acd001dc86d2c",
    "taxonomy.csv": "bd18483667d8a0ce7c1676ad4160a61589390ef090b0fb8092da50832dcecb69",
    "taxonomy.json": "7df72a7a05afe53f20344339552b6c980423e1bd25e5cc69587f4f4619edc0e8",
}

MAX_BYTES = 256 * 1024 * 1024  # cap so a hostile/oversized response can't fill the disk
CHUNK = 1 << 16


def _host_ok(host):
    if not host:
        return False
    host = host.lower()
    return host == "github.com" or host.endswith(".githubusercontent.com")


class _HostCheckedRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects, but only to HTTPS URLs on an allow-listed host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        u = urlparse(newurl)
        if u.scheme != "https" or not _host_ok(u.hostname):
            raise urllib.error.URLError(f"refused redirect to {newurl!r}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_HostCheckedRedirect)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def download(url, dest, expected, allow_unverified=False):
    name = dest.name
    if expected is None and not allow_unverified:
        raise RuntimeError(f"no pinned checksum for {name}; refusing (pass --allow-unverified to override)")

    if dest.exists():
        if expected is None or sha256_of(dest) == expected:
            print(f"-> {name}  ({'present, verified' if expected else 'present, UNVERIFIED'})")
            return
        print(f"-> {name}  (present but hash mismatch — re-downloading)")

    u = urlparse(url)
    if u.scheme != "https" or not _host_ok(u.hostname):
        raise RuntimeError(f"refusing non-HTTPS / off-host URL: {url!r}")

    tmp = dest.with_suffix(dest.suffix + ".part")
    h = hashlib.sha256()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "imgedge-downloader"})
        with _opener.open(req, timeout=30) as resp, open(tmp, "wb") as out:
            total = int(resp.headers.get("Content-Length", 0))
            read = 0
            while True:
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                read += len(chunk)
                if read > MAX_BYTES:
                    raise RuntimeError(f"{name} exceeds the {MAX_BYTES // (1 << 20)} MB cap")
                out.write(chunk)
                h.update(chunk)
                if total:
                    print(f"\r-> {name}  {read * 100 // total:3d}%", end="", flush=True)
        digest = h.hexdigest()
        if expected is not None and digest != expected:
            raise RuntimeError(f"checksum mismatch for {name}\n  expected {expected}\n  got      {digest}")
        tmp.replace(dest)
        print(f"\r-> {name}  done ({read // 1024} KB, {'verified' if expected else 'UNVERIFIED'})")
    except BaseException as e:
        if tmp.exists():
            tmp.unlink()
        print(f"\r-> {name}  FAILED: {e}")
        raise


def main():
    p = argparse.ArgumentParser(description="Download + verify iNaturalist model assets.")
    p.add_argument(
        "--out",
        default=None,
        help="output directory (default: <this script>/models, where the classifier server looks)",
    )
    p.add_argument("--all", action="store_true", help="also fetch geomodel + common names")
    p.add_argument("--verify", action="store_true", help="only check on-disk files against the pinned SHA-256s")
    p.add_argument(
        "--allow-unverified",
        action="store_true",
        help="permit assets that have no pinned checksum (NOT recommended)",
    )
    p.add_argument(
        "--print-hashes",
        action="store_true",
        help="print SHA-256 of the selected on-disk files and exit",
    )
    args = p.parse_args()

    # Default next to this script (inat/models) so the server finds the files
    # regardless of the current working directory.
    out_dir = Path(args.out) if args.out else Path(__file__).resolve().parent / "models"
    selected = [fn for fn, default in ASSETS.values() if default or args.all]

    if args.print_hashes:
        for fn in selected:
            path = out_dir / fn
            print(f"{(sha256_of(path) if path.exists() else '(missing)'):<64}  {fn}")
        return

    if args.verify:
        bad = 0
        for fn in selected:
            path = out_dir / fn
            expected = CHECKSUMS.get(fn)
            if expected is None:
                print(f"NO-PIN   {fn}")
            elif not path.exists():
                print(f"MISSING  {fn}")
                bad += 1
            elif sha256_of(path) == expected:
                print(f"OK       {fn}")
            else:
                print(f"MISMATCH {fn}")
                bad += 1
        if bad:
            sys.exit(f"\n{bad} file(s) failed verification.")
        print("\nAll pinned files verified.")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    for fn in selected:
        download(f"{RELEASE}/{fn}", out_dir / fn, CHECKSUMS.get(fn), args.allow_unverified)

    model = out_dir / "INatVision_Small_2_fact256_8bit.tflite"
    taxonomy = out_dir / "taxonomy.csv"
    print(f"\nDone (all verified). Files in: {out_dir.resolve()}")
    print(f"Next: python inat_vision.py <image> --model {model} --taxonomy {taxonomy}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        sys.exit(str(e) if str(e) else 1)
