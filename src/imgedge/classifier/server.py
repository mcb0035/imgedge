#!/usr/bin/env python3
# Copyright the ImgEdge contributors.
# SPDX-License-Identifier: Apache-2.0
"""ImgEdge local classifier — blocks images of a target taxon (default:
class Arachnida) using the iNaturalist vision model. Fully local; nothing
about image content leaves the machine.

Protocol
--------
POST /classify  (JSON, header X-ImgEdge-Token: <token>):
    { "url": "<image url>", "data": "data:image/...;base64,..."?,
      "meta": { "kind": "img|input|svg|poster|bg", "w": <px>, "h": <px> }?,
      "profile": "fast|balanced|accurate"?, "threshold": <0..1>?, "salience": <0..1>? }
  -> { "block": <bool>, "reason": "<text>", "score": <0..1> }
GET  /health    (no auth):
    -> { "status", "target", "taxa", "voters", "profiles", "policy", "provider", "auth_required" }

Setup:
  pip install -e .                  # numpy, pillow, ai-edge-litert
  imgedge-download-models          # fetch + verify the vision model + taxonomy
Run:
  imgedge-server                   # prints the access token to paste into the popup

Environment overrides:
  IMGEDGE_TARGET     taxon name to block (default: Arachnida)
  IMGEDGE_THRESHOLD  block when P(target) >= this (default: 0.18)
  IMGEDGE_MODEL      path to the .tflite vision model
  IMGEDGE_TAXONOMY   path to taxonomy.csv
  IMGEDGE_TOKEN      fixed access token (else one is generated and persisted)
  IMGEDGE_TOKEN_FILE where to persist the token (default: ~/.imgedge_token)
  IMGEDGE_WORKERS    max concurrent request workers (default: 8)
  IMGEDGE_ONNX       path to an ONNX model (enables the GPU/NPU backend)
  IMGEDGE_EP         execution provider: auto|npu|ovgpu|cuda|dml|cpu (default: auto)
  IMGEDGE_POOL       TFLite interpreter pool size (default: min(4, cpus))
  IMGEDGE_CACHE_FILE verdict cache path, or "none" to disable
  IMGEDGE_LOG_FILE   log path, or "none" (default: ~/.imgedge.log; size-capped + rotated)
  IMGEDGE_LOG_LEVEL  DEBUG|INFO|WARNING|ERROR (default: INFO)
  IMGEDGE_PROFILE    expose rolling latency stats in /health (default: 1; 0=off)
  IMGEDGE_SANDBOX    decode images in a recycled worker pool (default: 0; 1=on)
  IMGEDGE_SANDBOX_APPCONTAINER  decode in a no-network Windows AppContainer (default: 0)
  IMGEDGE_VOTE       policy: evidence|any|all|majority|weighted (default: evidence)
  IMGEDGE_TIMM_MODEL HF/timm model id (default: mobilenetv3_large_100.ra_in1k)
  IMGEDGE_TIMM_EXCLUDE   comma-separated ImageNet terms to BLOCK (arachnids)
  IMGEDGE_TIMM_CONTRAST  comma-separated ImageNet terms that argue AGAINST a block
  IMGEDGE_TIMM_CONTRAST_WEIGHT  weight of contrast (look-alike) evidence (default: 0.0)
  IMGEDGE_TIMM_THRESHOLD timm voter block threshold (default: 0.5)
  IMGEDGE_TIMM_WEIGHT    timm evidence weight in the ensemble (default: 0.5)
  IMGEDGE_SIGLIP     load the open-vocab SigLIP 2 voter if installed (default: 1; 0=skip)
  IMGEDGE_SIGLIP_MODEL   HF SigLIP model id (default: google/siglip2-base-patch16-224)
  IMGEDGE_SIGLIP_WEIGHT  siglip evidence weight in the ensemble (default: 2.0)
  IMGEDGE_SIGLIP_GATE    cascade floor; skip SigLIP below this iNat+timm score (default: 0.0)
  IMGEDGE_MOBILECLIP     load the MobileCLIP voter if installed (smaller/faster open-vocab; default: 1; 0=skip)
  IMGEDGE_MOBILECLIP_MODEL  open_clip model (default: MobileCLIP2-S0)
  IMGEDGE_MOBILECLIP_WEIGHT mobileclip evidence weight in the ensemble (default: 1.0)
"""

import base64
import hashlib
import hmac
import http.client
import ipaddress
import json
import logging
import os
import secrets
import socket
import sys
import threading
import time
import urllib.request
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PKG_DIR = Path(__file__).resolve().parent.parent
INAT_DIR = PKG_DIR / "inat"

try:
    __version__ = pkg_version("imgedge")
except PackageNotFoundError:
    __version__ = "0+unknown"

HOST = "127.0.0.1"  # loopback only, by design (not configurable)
PORT = int(os.environ.get("IMGEDGE_PORT", "8723"))

TARGET = os.environ.get("IMGEDGE_TARGET", "Arachnida")
THRESHOLD = float(os.environ.get("IMGEDGE_THRESHOLD", "0.18"))
MODEL_PATH = Path(os.environ.get("IMGEDGE_MODEL", INAT_DIR / "models" / "INatVision_Small_2_fact256_8bit.tflite"))
TAXONOMY_PATH = Path(os.environ.get("IMGEDGE_TAXONOMY", INAT_DIR / "models" / "taxonomy.csv"))
ONNX_PATH = Path(os.environ.get("IMGEDGE_ONNX", INAT_DIR / "models" / "INatVision_Small_2_fact256_8bit.onnx"))
EP_PREF = os.environ.get("IMGEDGE_EP", "auto")  # auto|npu|ovgpu|cuda|dml|cpu
VOTE_POLICY = os.environ.get("IMGEDGE_VOTE", "evidence")  # evidence|any|all|majority|weighted
TIMM_THRESHOLD = float(os.environ.get("IMGEDGE_TIMM_THRESHOLD", "0.5"))
TIMM_WEIGHT = float(os.environ.get("IMGEDGE_TIMM_WEIGHT", "0.5"))
# iNat (real-organism) confidence at/above which it blocks outright, ignoring
# the look-alike contrast voter. Set >1.0 (e.g. 1.1) to disable.
INAT_OVERRIDE = float(os.environ.get("IMGEDGE_INAT_OVERRIDE", "0.9"))
# Third voter: open-vocabulary SigLIP 2. Loaded whenever its extra is installed
# (like the timm voter); set IMGEDGE_SIGLIP=0 to skip loading it (e.g. to save
# RAM on a constrained box). Recognises arachnids the closed-vocab voters have
# no class for, adding independent positive evidence on borderline images.
SIGLIP_ENABLE = os.environ.get("IMGEDGE_SIGLIP", "1") != "0"
SIGLIP_THRESHOLD = float(os.environ.get("IMGEDGE_SIGLIP_THRESHOLD", "0.5"))
SIGLIP_WEIGHT = float(os.environ.get("IMGEDGE_SIGLIP_WEIGHT", "2.0"))
# Cascade gate: skip the SigLIP voter when the cheap iNat+timm combined score is
# below this floor. Default 0.0 only skips it when the cheap voters ALREADY
# block (SigLIP is positive-only, so it cannot change that verdict) -- lossless.
# On real web data most images sit just under the threshold (iNat gives a small
# baseline signal), so raising this trades a little recall for fewer SigLIP runs.
SIGLIP_GATE = float(os.environ.get("IMGEDGE_SIGLIP_GATE", "0.0"))
# MobileCLIP voter: a smaller/faster open-vocabulary alternative to SigLIP
# (open_clip). Loaded when its extra is installed; set IMGEDGE_MOBILECLIP=0 to
# skip. Also deferred (runs under the cascade).
MOBILECLIP_ENABLE = os.environ.get("IMGEDGE_MOBILECLIP", "1") != "0"
MOBILECLIP_THRESHOLD = float(os.environ.get("IMGEDGE_MOBILECLIP_THRESHOLD", "0.5"))
MOBILECLIP_WEIGHT = float(os.environ.get("IMGEDGE_MOBILECLIP_WEIGHT", "1.0"))

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_BODY_BYTES = 16 * 1024 * 1024  # request-body cap (8MB image -> ~11MB base64 + JSON)
# Keep the fetch budget under the extension's 15s classify timeout so a slow
# image doesn't make the extension abort and fail open.
FETCH_TIMEOUT = 6
MAX_WORKERS = int(os.environ.get("IMGEDGE_WORKERS", "8"))
REQUEST_TIMEOUT = int(os.environ.get("IMGEDGE_REQUEST_TIMEOUT", "15"))  # slowloris guard
POOL_SIZE = int(os.environ.get("IMGEDGE_POOL", str(min(4, os.cpu_count() or 1))))
LOAD_RETRY_SEC = 30
# Persistent verdict cache. Keyed by a hash of the URL (never the URL itself);
# stores only the verdict, so no image data or browsing URLs touch the disk.
_cache_env = os.environ.get("IMGEDGE_CACHE_FILE", str(Path.home() / ".imgedge_cache.json"))
CACHE_PATH = None if _cache_env == "none" else Path(_cache_env)

# Logging. The file is bounded (maxBytes * (backups+1)) so a stuck/erroring
# extension hammering /classify can never grow it without limit.
LOG_LEVEL = os.environ.get("IMGEDGE_LOG_LEVEL", "INFO").upper()
_log_env = os.environ.get("IMGEDGE_LOG_FILE", str(Path.home() / ".imgedge.log"))
LOG_FILE = None if _log_env == "none" else Path(_log_env)
LOG_MAX_BYTES = int(os.environ.get("IMGEDGE_LOG_MAX_BYTES", str(1024 * 1024)))
LOG_BACKUPS = int(os.environ.get("IMGEDGE_LOG_BACKUPS", "3"))
PROFILE = os.environ.get("IMGEDGE_PROFILE", "1") != "0"
SANDBOX = os.environ.get("IMGEDGE_SANDBOX", "0") != "0"
SANDBOX_WORKERS = int(os.environ.get("IMGEDGE_SANDBOX_WORKERS", "2"))
SANDBOX_RECYCLE = int(os.environ.get("IMGEDGE_SANDBOX_RECYCLE", "200"))
SANDBOX_MEM_MB = int(os.environ.get("IMGEDGE_SANDBOX_MEM_MB", "1024"))
SANDBOX_CONFINE = os.environ.get("IMGEDGE_SANDBOX_CONFINE", "1") != "0"
# Low-IL is OFF by default: dropping a running worker to Low integrity breaks
# lazy imports of the (profile-installed) Python stdlib/venv on a typical box.
# See confine.worker_init. AppContainer is the supported strong-isolation path.
SANDBOX_LOWIL = os.environ.get("IMGEDGE_SANDBOX_LOWIL", "0") != "0"
# AppContainer: decode in a no-network, no-write Windows AppContainer (strong
# isolation). Windows-only; falls back to the plain pool elsewhere.
SANDBOX_APPCONTAINER = os.environ.get("IMGEDGE_SANDBOX_APPCONTAINER", "0") != "0"
log = logging.getLogger("imgedge")


class _Dedupe(logging.Filter):
    """Collapse a burst of identical messages so a stuck client can't flood the log."""

    def __init__(self, window=10.0):
        super().__init__()
        self.window = window
        self._last = None
        self._at = 0.0
        self._suppressed = 0

    def filter(self, record):
        msg = record.getMessage()
        now = time.monotonic()
        if msg == self._last and now - self._at < self.window:
            self._suppressed += 1
            return False
        if self._suppressed:
            record.msg = f"{record.msg} (+{self._suppressed} repeats suppressed)"
            record.args = ()
        self._last, self._at, self._suppressed = msg, now, 0
        return True


def _setup_logging():
    if log.handlers:
        return
    log.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    log.addFilter(_Dedupe())
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    log.addHandler(stream)
    if LOG_FILE:
        try:
            fh = RotatingFileHandler(LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8")
            fh.setFormatter(fmt)
            log.addHandler(fh)
        except OSError:
            pass  # never let logging setup stop the server


_setup_logging()

_ensemble = None  # VoteEnsemble (None if no voters are available)
_decoder = None  # DecodePool (None unless IMGEDGE_SANDBOX)
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
        # Create atomically, owner-only: O_EXCL closes the exists->write race and
        # 0o600 leaves no world-readable window (vs. write_text then chmod).
        try:
            fd = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            existing = token_file.read_text(encoding="utf-8").strip()  # lost a race
            return existing or token
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(token)
        return token
    except OSError:
        return secrets.token_urlsafe(24)  # ephemeral for this run


TOKEN = load_or_create_token()
_CACHE_HMAC_KEY = TOKEN.encode("utf-8")


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
        # HMAC with the per-install token so a local reader of the cache file
        # can't confirm a guessed URL by recomputing a plain SHA-256.
        return hmac.new(_CACHE_HMAC_KEY, url.encode("utf-8"), hashlib.sha256).hexdigest()

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


class Stats:
    """Thread-safe rolling latency stats (cheap; resettable). Avg is over all
    model-run requests since start/reset; cache hits are counted separately."""

    def __init__(self):
        self._lock = threading.Lock()
        self.n = self.blocked = self.hits = 0
        self.fetch_ms = self.infer_ms = self.max_ms = 0.0

    def record(self, fetch_ms, infer_ms, blocked):
        with self._lock:
            self.n += 1
            self.fetch_ms += fetch_ms
            self.infer_ms += infer_ms
            self.max_ms = max(self.max_ms, fetch_ms + infer_ms)
            self.blocked += 1 if blocked else 0

    def hit(self):
        with self._lock:
            self.hits += 1

    def snapshot(self):
        with self._lock:
            n = self.n
            return {
                "n": n,
                "blocked": self.blocked,
                "cache_hits": self.hits,
                "avg_ms": round((self.fetch_ms + self.infer_ms) / n, 1) if n else 0,
                "infer_ms": round(self.infer_ms / n, 1) if n else 0,
                "fetch_ms": round(self.fetch_ms / n, 1) if n else 0,
                "max_ms": round(self.max_ms, 1),
            }

    def reset(self):
        with self._lock:
            self.n = self.blocked = self.hits = 0
            self.fetch_ms = self.infer_ms = self.max_ms = 0.0


_stats = Stats()


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
        log.error("INTEGRITY FAIL: %s does not match its pinned hash", path.name)
        log.error("  expected %s", expected)
        log.error("  got      %s", actual)
        log.error("refusing to load it; re-download with: imgedge-download-models")
        return False
    return True


def load_filter():
    if not TAXONOMY_PATH.exists():
        log.warning("taxonomy not found at %s; run: imgedge-download-models", TAXONOMY_PATH)
        log.warning("running in fail-open mode (nothing will be blocked).")
        return None
    if not _verify_pinned(TAXONOMY_PATH):
        return None
    # Prefer the ONNX backend (GPU/NPU) when a converted model + runtime exist.
    if ONNX_PATH.exists():
        try:
            from imgedge.inat.onnx_filter import OnnxTaxonFilter

            flt = OnnxTaxonFilter(ONNX_PATH, TAXONOMY_PATH, target=TARGET, ep=EP_PREF)
            log.info(
                "model loaded (ONNX): %d '%s' taxa, threshold=%s, provider=%s",
                flt.match_count,
                TARGET,
                THRESHOLD,
                flt.provider,
            )
            return flt
        except Exception as e:
            log.warning("ONNX backend unavailable (%s); falling back to TFLite.", e)
    if MODEL_PATH.exists():
        if not _verify_pinned(MODEL_PATH):
            return None
        try:
            from imgedge.inat.inat_filter import TaxonFilter

            flt = TaxonFilter(MODEL_PATH, TAXONOMY_PATH, target=TARGET, pool_size=POOL_SIZE)
            log.info(
                "model loaded (TFLite): %d '%s' taxa, threshold=%s, pool=%s",
                flt.match_count,
                TARGET,
                THRESHOLD,
                POOL_SIZE,
            )
            return flt
        except Exception as e:
            log.error("failed to load TFLite model (%s); fail-open mode.", e)
            return None
    log.warning(
        "no model found in %s; run: imgedge-download-models (and install a runtime)",
        MODEL_PATH.parent,
    )
    log.warning("running in fail-open mode (nothing will be blocked).")
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
            log.warning("iNat voter unavailable (%s).", e)
    try:
        from imgedge.voters.timm_voter import TimmVoter

        tv = TimmVoter(threshold=TIMM_THRESHOLD, weight=TIMM_WEIGHT)
        voters.append(tv)
        log.info(
            "timm voter: %s on %s, %d block / %d contrast class(es)",
            tv.name,
            tv.provider,
            tv.matched,
            tv.contrast_matched,
        )
    except Exception as e:
        log.info('timm voter skipped (%s); pip install -e ".[voters]" to enable it.', e)
    if SIGLIP_ENABLE:
        try:
            from imgedge.voters.siglip_voter import SiglipVoter

            sv = SiglipVoter(threshold=SIGLIP_THRESHOLD, weight=SIGLIP_WEIGHT)
            voters.append(sv)
            log.info("siglip voter: %s on %s, %d prompt(s)", sv.name, sv.provider, len(sv.prompts))
        except Exception as e:
            log.info('siglip voter skipped (%s); pip install -e ".[voters,siglip]" and set IMGEDGE_SIGLIP=1.', e)
    if MOBILECLIP_ENABLE:
        try:
            from imgedge.voters.mobileclip_voter import MobileClipVoter

            mv = MobileClipVoter(threshold=MOBILECLIP_THRESHOLD, weight=MOBILECLIP_WEIGHT)
            voters.append(mv)
            log.info("mobileclip voter: %s on %s, %d prompt(s)", mv.name, mv.provider, len(mv.prompts))
        except Exception as e:
            log.info("mobileclip voter skipped (%s); needs .[voters,mobileclip] + IMGEDGE_MOBILECLIP=1.", e)
    if not voters:
        return None
    from imgedge.voters.base import VoteEnsemble

    ens = VoteEnsemble(voters, policy=VOTE_POLICY, threshold=THRESHOLD, inat_override=INAT_OVERRIDE, gate=SIGLIP_GATE)
    ens.inat = inat_voter
    log.info("ensemble ready: policy=%s, voters=%s", VOTE_POLICY, ens.names)
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
        try:
            _ensemble = load_ensemble()
        except Exception as e:
            log.error("ensemble load failed (%s); fail-open mode.", e)
            _ensemble = None
        return _ensemble


# ---- SSRF-guarded image fetch ----------------------------------------------
# Defense in depth against server-side request forgery on the user-supplied image
# URL:
#   1. scheme allow-list (http/https only) + a fast pre-check (_is_public_host);
#   2. redirects are never followed (blocks redirect-to-internal);
#   3. the socket is PINNED to the exact IP we validated, so the host cannot be
#      rebound to a private/loopback address between the check and the connect
#      (the classic DNS-rebinding TOCTOU bypass). TLS SNI + certificate checks
#      stay bound to the original hostname.
#
# Fetch policy (env-tunable). Defaults are safe for general browsing; the
# https-only / allow-list knobs let a security-conscious user lock egress down.
def _env_ports(raw):
    raw = (raw or "").strip().lower()
    if raw in ("", "any", "*"):
        return None  # no port restriction
    return {int(p) for p in raw.split(",") if p.strip().isdigit()} or None


ALLOWED_PORTS = _env_ports(os.environ.get("IMGEDGE_FETCH_PORTS", "80,443"))
FETCH_HTTPS_ONLY = os.environ.get("IMGEDGE_FETCH_HTTPS_ONLY", "0") != "0"
# Neutral, browser-like UA so the re-fetch doesn't advertise "ImgEdge" to image
# hosts (privacy: don't reveal the tool or the category being filtered).
FETCH_UA = os.environ.get(
    "IMGEDGE_FETCH_UA",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
)
ALLOW_HOSTS = tuple(
    h.strip().lower().rstrip(".") for h in os.environ.get("IMGEDGE_FETCH_ALLOW_HOSTS", "").split(",") if h.strip()
)
try:
    FETCH_PER_HOST = int(os.environ.get("IMGEDGE_FETCH_PER_HOST", "4"))
except ValueError:
    FETCH_PER_HOST = 4
_FETCH_HOST_MAX = 512  # cap on tracked per-host limiters (LRU-evicted)
_host_sems = OrderedDict()
_host_sems_lock = threading.Lock()

# NAT64 / DNS64 (RFC 6052 well-known + RFC 8215 local-use) embeds an IPv4
# destination inside a synthetic IPv6 address, so we judge the embedded IPv4.
_NAT64_WELLKNOWN = ipaddress.ip_network("64:ff9b::/96")
_NAT64_LOCAL = ipaddress.ip_network("64:ff9b:1::/48")
# Carrier-grade NAT shared space (RFC 6598) -- not globally routable.
_CGNAT = ipaddress.ip_network("100.64.0.0/10")
# Response content types that clearly aren't images (an SSRF probe of an
# internal web/API service); image/* and ambiguous types pass to Pillow.
_BAD_CONTENT_TYPES = (
    "text/",
    "application/json",
    "application/xml",
    "application/javascript",
    "multipart/",
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # never follow redirects (blocks redirect-to-internal SSRF)


def _ip_is_public(addr):
    """True only if `addr` is a routable, public, non-shared address. Unwraps
    IPv4-mapped and NAT64-embedded IPv6 so an internal IPv4 can't be smuggled
    inside an IPv6 wrapper, and rejects CGNAT (RFC 6598) shared space."""
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            return _ip_is_public(addr.ipv4_mapped)
        if addr in _NAT64_WELLKNOWN:
            return _ip_is_public(ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF))
        if addr in _NAT64_LOCAL:
            return False  # variable embedding format -> fail closed
    elif addr in _CGNAT:
        return False
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def _is_public_host(host):
    """True only if every resolved address for `host` is a routable public IP."""
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
        if not _ip_is_public(addr):
            return False
    return True


def _resolve_pinned_addr(host, port):
    """Resolve `host`, require EVERY resolved address to be public, and return one
    validated sockaddr to connect to. Raises OSError on lookup failure or if any
    address is non-public. Connecting to this exact address (instead of re-using
    the hostname) is what closes the DNS-rebinding TOCTOU gap."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not infos:
        raise OSError("no addresses for host")
    for _family, _type, _proto, _canon, sockaddr in infos:
        try:
            addr = ipaddress.ip_address(sockaddr[0])
        except ValueError as exc:
            raise OSError(f"unparseable address: {sockaddr[0]!r}") from exc
        if not _ip_is_public(addr):
            raise OSError(f"blocked non-public address: {sockaddr[0]}")
    return infos[0][4]


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Connects only to the validated IP for ``self.host`` (no second lookup)."""

    def connect(self):
        sockaddr = _resolve_pinned_addr(self.host, self.port)
        self.sock = socket.create_connection(sockaddr[:2], self.timeout, self.source_address)
        if self._tunnel_host:
            self._tunnel()


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """As above, with TLS SNI + certificate check kept on the original hostname."""

    def connect(self):
        sockaddr = _resolve_pinned_addr(self.host, self.port)
        sock = socket.create_connection(sockaddr[:2], self.timeout, self.source_address)
        if self._tunnel_host:
            self.sock = sock
            self._tunnel()
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_PinnedHTTPConnection, req)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_PinnedHTTPSConnection, req, context=self._context)


_opener = urllib.request.build_opener(_PinnedHTTPHandler, _PinnedHTTPSHandler, _NoRedirect)


def _host_allowed(host):
    """True unless IMGEDGE_FETCH_ALLOW_HOSTS is set and `host` (or a parent
    domain) isn't on it."""
    if not ALLOW_HOSTS:
        return True
    host = host.lower().rstrip(".")
    return any(host == a or host.endswith("." + a) for a in ALLOW_HOSTS)


def _url_allowed(url):
    """Scheme, https-only, host-allowlist, and port checks on the user URL."""
    if not isinstance(url, str) or not url:
        return False
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return False
    if FETCH_HTTPS_ONLY and scheme != "https":
        return False
    if not parsed.hostname or not _host_allowed(parsed.hostname):
        return False
    try:
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError:
        return False  # malformed port in the authority
    return ALLOWED_PORTS is None or port in ALLOWED_PORTS


def _content_type_ok(ctype):
    """False for response content types that clearly aren't images; image/* and
    ambiguous types (octet-stream, missing) pass and let Pillow be the gate."""
    if not ctype:
        return True
    ctype = ctype.split(";", 1)[0].strip().lower()
    if ctype.startswith("image/"):
        return True
    return not ctype.startswith(_BAD_CONTENT_TYPES)


def _acquire_host_slot(host):
    """Return a per-host BoundedSemaphore (caller acquires/releases) to cap
    concurrent fetches to one host, or None when disabled. The map is LRU-bounded
    so a long browsing session can't grow it without limit."""
    if FETCH_PER_HOST <= 0:
        return None
    with _host_sems_lock:
        sem = _host_sems.get(host)
        if sem is None:
            sem = threading.BoundedSemaphore(FETCH_PER_HOST)
            _host_sems[host] = sem
            if len(_host_sems) > _FETCH_HOST_MAX:
                _host_sems.popitem(last=False)  # evict least-recently-used
        else:
            _host_sems.move_to_end(host)
    return sem


def fetch_image_bytes(url, data):
    """Bytes from an inline data URL, else fetch the http(s) URL (SSRF-guarded)."""
    if isinstance(data, str) and data.startswith("data:"):
        try:
            return base64.b64decode(data.split(",", 1)[1])
        except (ValueError, IndexError):
            return None
    if not _url_allowed(url):
        return None
    host = urlparse(url).hostname
    if not host or not _is_public_host(host):
        return None  # refuse loopback / private / link-local / reserved targets
    sem = _acquire_host_slot(host)
    if sem is not None and not sem.acquire(timeout=FETCH_TIMEOUT):
        return None  # too many concurrent fetches to this host
    try:
        req = urllib.request.Request(url, headers={"User-Agent": FETCH_UA})
        with _opener.open(req, timeout=FETCH_TIMEOUT) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            if not _content_type_ok(resp.headers.get("Content-Type")):
                return None
            return resp.read(MAX_IMAGE_BYTES + 1)[:MAX_IMAGE_BYTES]
    except Exception:
        return None
    finally:
        if sem is not None:
            sem.release()


def _get_decoder():
    """Lazily build the out-of-process decode pool when IMGEDGE_SANDBOX is set."""
    global _decoder
    if not SANDBOX:
        return None
    if _decoder is None:
        with _load_lock:
            if _decoder is None:
                if SANDBOX_APPCONTAINER and sys.platform == "win32":
                    from imgedge.classifier.ac_pool import AppContainerPool

                    _decoder = AppContainerPool(
                        workers=SANDBOX_WORKERS,
                        recycle=SANDBOX_RECYCLE,
                        confine_os=SANDBOX_CONFINE,
                        mem_mb=SANDBOX_MEM_MB,
                    )
                else:
                    from imgedge.classifier.decode_pool import DecodePool

                    _decoder = DecodePool(
                        workers=SANDBOX_WORKERS,
                        recycle=SANDBOX_RECYCLE,
                        confine_os=SANDBOX_CONFINE,
                        mem_mb=SANDBOX_MEM_MB,
                        low_il=SANDBOX_LOWIL,
                    )
                log.info(
                    "sandbox decode: kind=%s, %d workers, recycle %d, confined=%s, worker=%s",
                    getattr(_decoder, "kind", "process"),
                    SANDBOX_WORKERS,
                    SANDBOX_RECYCLE,
                    _decoder.confined,
                    _decoder.worker_integrity(),
                )
    return _decoder


def _clamp01(v):
    """Coerce a client override to a float in [0, 1], or None if absent/invalid."""
    if v is None:
        return None
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return None


# Popup "easy mode" presets -> the voter subset to run for a request. Keyed by
# the prefix of each voter's name (before the ":"). The subset is intersected
# with the loaded voters, so a preset whose open-vocab voter isn't installed
# degrades to the cheaper voters it can still run.
PROFILE_VOTERS = {
    "fast": ("inat", "timm"),
    "balanced": ("inat", "timm", "mobileclip"),
    "accurate": ("inat", "timm", "siglip"),
}
# Voters that set a preset apart from plain "fast"; a preset is only offered in
# /health when the extra voter(s) it needs are loaded ("fast" always is).
_PRESET_EXTRA = {"siglip", "mobileclip"}


def _profile_only(ens, profile):
    """Voter-name set to run for `profile`, intersected with the loaded voters,
    or None (run every loaded voter) when the profile is absent/unrecognised."""
    req = PROFILE_VOTERS.get(profile) if isinstance(profile, str) else None
    if not req:
        return None
    only = {v.name for v in ens.voters if v.name.split(":", 1)[0] in req}
    return only or None


def classify(url, data, meta=None, threshold=None, salience=None, profile=None):
    """Return a verdict dict. `data` is a base64 data URL or None; `meta` carries
    page hints (rendered size, element kind) used for salience weighting.
    `threshold`/`salience`/`profile` are optional per-request overrides: the
    popup sliders and the easy-mode preset (which voter subset to run)."""
    ens = ensure_ensemble()
    if ens is None:
        return {"block": False, "reason": "model-unavailable", "score": 0.0}

    only = _profile_only(ens, profile)
    # Cache per (url, overrides) so moving a slider or switching preset
    # re-classifies instead of returning a stale verdict -- which also keeps
    # blocking monotonic in threshold.
    cache_key = url
    if threshold is not None or salience is not None or only is not None:
        prof = ",".join(sorted(only)) if only else ""
        cache_key = f"{url}\x00t={threshold}\x00s={salience}\x00p={prof}"
    cached = _vcache.get(cache_key)
    if cached is not None:
        if PROFILE:
            _stats.hit()
        return cached

    t0 = time.perf_counter()
    raw = fetch_image_bytes(url, data)
    if not raw:
        return {"block": False, "reason": "fetch-failed", "score": 0.0}  # transient: don't cache
    fetch_ms = (time.perf_counter() - t0) * 1000

    t1 = time.perf_counter()
    try:
        verdict = ens.classify_bytes(raw, meta, _get_decoder(), threshold, salience, only=only)
    except Exception:
        # Can't decode/classify (e.g. SVG, bomb, crafted bytes) -> don't block, don't
        # cache. Log detail locally; return a generic reason (no internals to client).
        log.warning("classify failed", exc_info=True)
        return {"block": False, "reason": "error", "score": 0.0}
    if PROFILE:
        _stats.record(fetch_ms, (time.perf_counter() - t1) * 1000, verdict.get("block"))

    _vcache.put(cache_key, verdict)  # only stable, model-derived verdicts are cached
    return verdict


def _health_proof(challenge):
    """HMAC(token, challenge) hex. Lets the extension verify it's talking to the
    real classifier (which knows the token) WITHOUT sending the token first, so a
    local port-squatter that doesn't know the token can't impersonate the server."""
    return hmac.new(TOKEN.encode("utf-8"), challenge.encode("utf-8"), hashlib.sha256).hexdigest()


def health_payload(full=True):
    """Status for the popup's /health check.

    Unauthenticated callers get only liveness (status/model); the detailed fields
    (target taxon, hardware provider, voters, latency, sandbox) require the token,
    so a local process can't fingerprint the configuration."""
    ens = ensure_ensemble()
    ok = ens is not None
    payload = {"status": "ok" if ok else "model-missing", "model": ok, "auth_required": True}
    if not full:
        return payload
    inat = getattr(ens, "inat", None) if ok else None
    loaded = {v.name.split(":", 1)[0] for v in ens.voters} if ok else set()
    payload.update(
        {
            "version": __version__,
            "target": getattr(inat, "target", TARGET),
            "threshold": THRESHOLD,
            "taxa": getattr(inat, "match_count", 0) if ok else 0,
            "backend": getattr(inat, "backend", None) if inat else None,
            "provider": getattr(inat, "provider", None) if inat else None,
            "voters": ens.names if ok else [],
            "profiles": (
                {name: all(p in loaded for p in req if p in _PRESET_EXTRA) for name, req in PROFILE_VOTERS.items()}
                if ok
                else {}
            ),
            "policy": getattr(ens, "policy", None) if ok else None,
            "inat_override": INAT_OVERRIDE,
            "stats": _stats.snapshot() if PROFILE else None,
            "sandbox": (
                "appcontainer"
                if (SANDBOX and SANDBOX_APPCONTAINER and sys.platform == "win32")
                else "process"
                if SANDBOX
                else None
            ),
        }
    )
    return payload


class Handler(BaseHTTPRequestHandler):
    timeout = REQUEST_TIMEOUT  # per-connection inactivity timeout (slowloris guard)

    def _authorized(self):
        return secrets.compare_digest(self.headers.get("X-ImgEdge-Token", ""), TOKEN)

    def _send_json(self, status, obj):
        body = json.dumps(obj).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionError, OSError):
            pass  # client (extension) aborted or timed out -> ignore, no traceback

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/health":
            self.send_response(404)
            self.end_headers()
            return
        payload = health_payload(full=self._authorized())
        challenge = parse_qs(parsed.query).get("challenge", [None])[0]
        if challenge:
            payload = {**payload, "proof": _health_proof(challenge)}
        self._send_json(200, payload)

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
        except (TypeError, ValueError):
            length = 0
        if length > MAX_BODY_BYTES:
            self._send_json(413, {"error": "payload too large"})
            return
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, TypeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}  # valid JSON that isn't an object (e.g. an array) carries no fields
        url = payload.get("url")
        data = payload.get("data")
        meta = payload.get("meta")
        self._send_json(
            200,
            classify(
                url if isinstance(url, str) else None,
                data if isinstance(data, str) else None,
                meta if isinstance(meta, dict) else None,
                _clamp01(payload.get("threshold")),
                _clamp01(payload.get("salience")),
                payload.get("profile"),
            ),
        )

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

    def handle_error(self, request, client_address):
        log.debug("client %s disconnected mid-request", client_address)

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
        if _decoder is not None:
            _decoder.close()
        _vcache.flush()


def _port_in_use_by_imgedge():
    """True if something already answers /health on HOST:PORT like ImgEdge does,
    so a second launch is a benign 'already running' rather than a real conflict."""
    try:
        with urllib.request.urlopen(f"http://{HOST}:{PORT}/health", timeout=2) as resp:
            data = json.loads(resp.read(4096) or b"{}")
        return isinstance(data, dict) and "status" in data and "auth_required" in data
    except Exception:
        return False


def main():
    ensure_ensemble()
    try:
        httpd = PooledHTTPServer((HOST, PORT), Handler)
    except OSError as e:
        if _port_in_use_by_imgedge():
            print(
                f"[imgedge] already running at http://{HOST}:{PORT} -- reuse it: paste\n"
                f"    that server's token into the ImgEdge popup. Nothing to do here."
            )
            raise SystemExit(0) from None
        print(
            f"[imgedge] ERROR: cannot bind {HOST}:{PORT} ({e}).\n"
            f"    The port is in use by another application (or a just-stopped ImgEdge\n"
            f"    still releasing it -- retry shortly). Set IMGEDGE_PORT to a free port\n"
            f"    (and update the extension's endpoint) to run alongside it.",
            file=sys.stderr,
        )
        raise SystemExit(2) from e
    log.info("ImgEdge classifier on http://%s:%s  (blocking: %s)", HOST, PORT, TARGET)
    print(f"[imgedge] access token (paste into the ImgEdge popup):\n    {TOKEN}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
