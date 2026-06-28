#!/usr/bin/env python3
"""ImgEdge local classifier — blocks images of a target taxon (default:
class Arachnida) using the iNaturalist vision model. Fully local; nothing
about image content leaves the machine.

Protocol
--------
POST /classify  (JSON, header X-ImgEdge-Token: <token>):
    { "url": "<image url>", "data": "data:image/...;base64,..."?,
      "meta": { "kind": "img|input|svg|poster|bg", "w": <px>, "h": <px> }? }
  -> { "block": <bool>, "reason": "<text>", "score": <0..1> }
GET  /health    (no auth):
    -> { "status", "target", "taxa", "voters", "policy", "provider", "auth_required" }

Setup:
  pip install -r ../inat/requirements.txt
  pip install tensorflow            # (or ai-edge-litert) to run the .tflite
  python ../inat/download_models.py # fetch the vision model + taxonomy
Run:
  python classifier/server.py       # prints the access token to paste into the popup

Environment overrides:
  IMGEDGE_TARGET     taxon name to block (default: Arachnida)
  IMGEDGE_THRESHOLD  block when P(target) >= this (default: 0.5)
  IMGEDGE_MODEL      path to the .tflite vision model
  IMGEDGE_TAXONOMY   path to taxonomy.csv
  IMGEDGE_TOKEN      fixed access token (else one is generated and persisted)
  IMGEDGE_TOKEN_FILE where to persist the token (default: ~/.imgedge_token)
  IMGEDGE_WORKERS    max concurrent request workers (default: 8)
  IMGEDGE_ONNX       path to an ONNX model (enables the GPU/NPU backend)
  IMGEDGE_EP         execution provider: auto|npu|ovgpu|cuda|dml|cpu (default: auto)
  IMGEDGE_POOL       TFLite interpreter pool size (default: min(4, cpus))
  IMGEDGE_CACHE_FILE verdict cache path, or "none" to disable
  IMGEDGE_VOTE       policy: evidence|any|all|majority|weighted (default: evidence)
  IMGEDGE_TIMM_MODEL HF/timm model id (default: mobilenetv3_large_100.ra_in1k)
  IMGEDGE_TIMM_EXCLUDE   comma-separated ImageNet terms to BLOCK (arachnids)
  IMGEDGE_TIMM_CONTRAST  comma-separated ImageNet terms that argue AGAINST a block
  IMGEDGE_TIMM_CONTRAST_WEIGHT  weight of contrast (look-alike) evidence (default: 1.0)
  IMGEDGE_TIMM_THRESHOLD timm voter block threshold (default: 0.5)
  IMGEDGE_TIMM_WEIGHT    timm evidence weight in the ensemble (default: 0.5)
"""

import base64
import hashlib
import ipaddress
import json
import os
import secrets
import socket
import threading
import time
import urllib.request
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

PKG_DIR = Path(__file__).resolve().parent.parent
INAT_DIR = PKG_DIR / "inat"

HOST = "127.0.0.1"
PORT = 8723

TARGET = os.environ.get("IMGEDGE_TARGET", "Arachnida")
THRESHOLD = float(os.environ.get("IMGEDGE_THRESHOLD", "0.5"))
MODEL_PATH = Path(os.environ.get(
    "IMGEDGE_MODEL", INAT_DIR / "models" / "INatVision_Small_2_fact256_8bit.tflite"))
TAXONOMY_PATH = Path(os.environ.get("IMGEDGE_TAXONOMY", INAT_DIR / "models" / "taxonomy.csv"))
ONNX_PATH = Path(os.environ.get(
    "IMGEDGE_ONNX", INAT_DIR / "models" / "INatVision_Small_2_fact256_8bit.onnx"))
EP_PREF = os.environ.get("IMGEDGE_EP", "auto")  # auto|npu|ovgpu|cuda|dml|cpu
VOTE_POLICY = os.environ.get("IMGEDGE_VOTE", "evidence")  # evidence|any|all|majority|weighted
TIMM_THRESHOLD = float(os.environ.get("IMGEDGE_TIMM_THRESHOLD", "0.5"))
TIMM_WEIGHT = float(os.environ.get("IMGEDGE_TIMM_WEIGHT", "0.5"))

MAX_IMAGE_BYTES = 8 * 1024 * 1024
# Keep the fetch budget under the extension's 15s classify timeout so a slow
# image doesn't make the extension abort and fail open.
FETCH_TIMEOUT = 6
MAX_WORKERS = int(os.environ.get("IMGEDGE_WORKERS", "8"))
POOL_SIZE = int(os.environ.get("IMGEDGE_POOL", str(min(4, os.cpu_count() or 1))))
LOAD_RETRY_SEC = 30
# Persistent verdict cache. Keyed by a hash of the URL (never the URL itself);
# stores only the verdict, so no image data or browsing URLs touch the disk.
_cache_env = os.environ.get("IMGEDGE_CACHE_FILE", str(Path.home() / ".imgedge_cache.json"))
CACHE_PATH = None if _cache_env == "none" else Path(_cache_env)

_ensemble = None            # VoteEnsemble (None if no voters are available)
_load_lock = threading.Lock()
_last_load_attempt = float("-inf")


# ---- Access token ----------------------------------------------------------
def load_or_create_token():
    env = os.environ.get("IMGEDGE_TOKEN")
    if env:
        return env
    token_file = Path(os.environ.get("IMGEDGE_TOKEN_FILE", Path.home() / ".imgedge_token"))
    try:
        if token_file.exists():
            existing = token_file.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        token = secrets.token_urlsafe(24)
        token_file.write_text(token, encoding="utf-8")
        try:
            os.chmod(token_file, 0o600)
        except OSError:
            pass
        return token
    except OSError:
        return secrets.token_urlsafe(24)  # ephemeral for this run


TOKEN = load_or_create_token()


# ---- Persistent verdict cache ----------------------------------------------
class VerdictCache:
    """LRU cache of url-hash -> verdict, flushed to disk periodically."""

    def __init__(self, path, cap=50000, flush_every=50):
        self.path = path
        self.cap = cap
        self.flush_every = flush_every
        self._lock = threading.Lock()
        self._dirty = 0
        self._data = OrderedDict()
        self._load()

    @staticmethod
    def _key(url):
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    def get(self, url):
        if not url:
            return None
        k = self._key(url)
        with self._lock:
            v = self._data.get(k)
            if v is not None:
                self._data.move_to_end(k)
            return v

    def put(self, url, verdict):
        if not url:
            return
        k = self._key(url)
        with self._lock:
            self._data[k] = verdict
            self._data.move_to_end(k)
            while len(self._data) > self.cap:
                self._data.popitem(last=False)
            self._dirty += 1
            if self.path and self._dirty >= self.flush_every:
                self._flush_locked()

    def flush(self):
        with self._lock:
            if self.path:
                self._flush_locked()

    def _flush_locked(self):
        self._dirty = 0
        try:
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(self._data), encoding="utf-8")
            tmp.replace(self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        except OSError:
            pass

    def _load(self):
        if not self.path or not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data = OrderedDict(raw)
                while len(self._data) > self.cap:
                    self._data.popitem(last=False)
        except (OSError, ValueError):
            pass


_vcache = VerdictCache(CACHE_PATH)


# ---- Model (lazy + reloadable) ---------------------------------------------
def _verify_pinned(path):
    """Refuse a model/taxonomy file that doesn't match its pinned SHA-256.

    Files whose name has no pin (a custom IMGEDGE_MODEL, or the locally generated
    ONNX) pass through; only a *known* filename with altered bytes is rejected,
    so a tampered download can't be handed to the interpreter.
    """
    try:
        from imgedge.inat.download_models import CHECKSUMS, sha256_of
    except Exception:
        return True  # verifier unavailable -> don't hard-fail the server
    expected = CHECKSUMS.get(path.name)
    if not expected:
        return True
    actual = sha256_of(path)
    if actual != expected:
        print(f"[imgedge] INTEGRITY FAIL: {path.name} does not match its pinned hash")
        print(f"[imgedge]   expected {expected}")
        print(f"[imgedge]   got      {actual}")
        print("[imgedge] refusing to load it; re-download with python inat/download_models.py")
        print("[imgedge] (or update CHECKSUMS in inat/download_models.py if intended).")
        return False
    return True


def load_filter():
    if not TAXONOMY_PATH.exists():
        print(f"[imgedge] taxonomy not found at {TAXONOMY_PATH}")
        print("[imgedge] run: python inat/download_models.py")
        print("[imgedge] running in fail-open mode (nothing will be blocked).")
        return None
    if not _verify_pinned(TAXONOMY_PATH):
        return None
    # Prefer the ONNX backend (GPU/NPU) when a converted model + runtime exist.
    if ONNX_PATH.exists():
        try:
            from imgedge.inat.onnx_filter import OnnxTaxonFilter
            flt = OnnxTaxonFilter(ONNX_PATH, TAXONOMY_PATH, target=TARGET, ep=EP_PREF)
            print(f"[imgedge] model loaded (ONNX): {flt.match_count} '{TARGET}' taxa, "
                  f"threshold={THRESHOLD}, provider={flt.provider}")
            return flt
        except Exception as e:
            print(f"[imgedge] ONNX backend unavailable ({e}); falling back to TFLite.")
    if MODEL_PATH.exists():
        if not _verify_pinned(MODEL_PATH):
            return None
        try:
            from imgedge.inat.inat_filter import TaxonFilter
            flt = TaxonFilter(MODEL_PATH, TAXONOMY_PATH, target=TARGET, pool_size=POOL_SIZE)
            print(f"[imgedge] model loaded (TFLite): {flt.match_count} '{TARGET}' taxa, "
                  f"threshold={THRESHOLD}, pool={POOL_SIZE}")
            return flt
        except Exception as e:
            print(f"[imgedge] failed to load TFLite model ({e}); fail-open mode.")
            return None
    print(f"[imgedge] no model found in {MODEL_PATH.parent}")
    print("[imgedge] run: python inat/download_models.py  (and install a runtime)")
    print("[imgedge] running in fail-open mode (nothing will be blocked).")
    return None


def load_ensemble():
    """Build the voting ensemble: iNaturalist voter + optional timm voter."""
    voters = []
    inat_voter = None
    inat_model = load_filter()
    if inat_model is not None:
        try:
            from imgedge.voters.inat_voter import InatVoter
            inat_voter = InatVoter(inat_model, threshold=THRESHOLD)
            voters.append(inat_voter)
        except Exception as e:
            print(f"[imgedge] iNat voter unavailable ({e}).")
    try:
        from imgedge.voters.timm_voter import TimmVoter
        tv = TimmVoter(threshold=TIMM_THRESHOLD, weight=TIMM_WEIGHT)
        voters.append(tv)
        print(f"[imgedge] timm voter: {tv.name} on {tv.provider}, "
              f"{tv.matched} block / {tv.contrast_matched} contrast class(es)")
    except Exception as e:
        print(f"[imgedge] timm voter skipped ({e}); "
              f"pip install -r voters/requirements.txt to enable it.")
    if not voters:
        return None
    from imgedge.voters.base import VoteEnsemble
    ens = VoteEnsemble(voters, policy=VOTE_POLICY, threshold=THRESHOLD)
    ens.inat = inat_voter
    print(f"[imgedge] ensemble ready: policy={VOTE_POLICY}, voters={ens.names}")
    return ens


def ensure_ensemble():
    """Return the loaded ensemble, retrying if models appeared later."""
    global _ensemble, _last_load_attempt
    if _ensemble is not None:
        return _ensemble
    with _load_lock:
        if _ensemble is not None:
            return _ensemble
        now = time.monotonic()
        if now - _last_load_attempt < LOAD_RETRY_SEC:
            return None
        _last_load_attempt = now
        _ensemble = load_ensemble()
        return _ensemble


# ---- SSRF-guarded image fetch ----------------------------------------------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # never follow redirects (blocks redirect-to-internal SSRF)


_opener = urllib.request.build_opener(_NoRedirect)


def _is_public_host(host):
    """True only if every resolved address is a routable public IP."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_multicast or addr.is_reserved or addr.is_unspecified):
            return False
    return True


def fetch_image_bytes(url, data):
    """Bytes from an inline data URL, else fetch the http(s) URL (SSRF-guarded)."""
    if data and data.startswith("data:"):
        try:
            return base64.b64decode(data.split(",", 1)[1])
        except (ValueError, IndexError):
            return None
    if not url or not url.lower().startswith(("http://", "https://")):
        return None
    host = urlparse(url).hostname
    if not host or not _is_public_host(host):
        return None  # refuse loopback / private / link-local / reserved targets
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ImgEdge/1.0"})
        with _opener.open(req, timeout=FETCH_TIMEOUT) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            return resp.read(MAX_IMAGE_BYTES + 1)[:MAX_IMAGE_BYTES]
    except Exception:
        return None


def classify(url, data, meta=None):
    """Return a verdict dict. `data` is a base64 data URL or None; `meta` carries
    page hints (rendered size, element kind) used for salience weighting."""
    ens = ensure_ensemble()
    if ens is None:
        return {"block": False, "reason": "model-unavailable", "score": 0.0}

    cached = _vcache.get(url)
    if cached is not None:
        return cached

    raw = fetch_image_bytes(url, data)
    if not raw:
        return {"block": False, "reason": "fetch-failed", "score": 0.0}  # transient: don't cache

    try:
        verdict = ens.classify_bytes(raw, meta)  # {block, reason, score, votes}
    except Exception as e:
        # Can't decode/classify (e.g. SVG, bomb, crafted bytes) -> don't block, don't cache.
        return {"block": False, "reason": f"error:{e}", "score": 0.0}

    _vcache.put(url, verdict)  # only stable, model-derived verdicts are cached
    return verdict


def health_payload():
    """Status for the popup's /health check (no auth required)."""
    ens = ensure_ensemble()
    ok = ens is not None
    inat = getattr(ens, "inat", None) if ok else None
    return {
        "status": "ok" if ok else "model-missing",
        "target": getattr(inat, "target", TARGET),
        "threshold": THRESHOLD,
        "taxa": getattr(inat, "match_count", 0) if ok else 0,
        "model": ok,
        "backend": getattr(inat, "backend", None) if inat else None,
        "provider": getattr(inat, "provider", None) if inat else None,
        "voters": ens.names if ok else [],
        "policy": getattr(ens, "policy", None) if ok else None,
        "auth_required": True,
    }


class Handler(BaseHTTPRequestHandler):
    def _authorized(self):
        return secrets.compare_digest(self.headers.get("X-ImgEdge-Token", ""), TOKEN)

    def _send_json(self, status, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?", 1)[0] != "/health":
            self.send_response(404)
            self.end_headers()
            return
        self._send_json(200, health_payload())

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/classify":
            self.send_response(404)
            self.end_headers()
            return
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, TypeError):
            payload = {}
        self._send_json(200, classify(payload.get("url"), payload.get("data"),
                                      payload.get("meta")))

    def log_message(self, *_):
        pass  # quiet


class PooledHTTPServer(HTTPServer):
    """HTTP server with a bounded worker pool (no unbounded thread growth)."""
    daemon_threads = True

    def __init__(self, *args, max_workers=MAX_WORKERS, **kwargs):
        super().__init__(*args, **kwargs)
        self._pool = ThreadPoolExecutor(max_workers=max_workers)

    def process_request(self, request, client_address):
        self._pool.submit(self._handle, request, client_address)

    def _handle(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)

    def server_close(self):
        super().server_close()
        self._pool.shutdown(wait=False)
        _vcache.flush()


def main():
    ensure_ensemble()
    print(f"ImgEdge classifier on http://{HOST}:{PORT}  (blocking: {TARGET})")
    print(f"[imgedge] access token (paste into the ImgEdge popup):\n    {TOKEN}")
    PooledHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
