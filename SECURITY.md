# Security Policy

ImgEdge is a privacy tool: a browser extension plus a **local, on-device** image
classifier that blocks images of a chosen category. Its security goals are (1)
nothing about image *content* leaves your machine, and (2) the local classifier
can't be turned into a foothold by a web page or another local process.

## Supported versions

This is an early-stage personal project. Only the latest `main` (currently
`0.1.0`) receives security fixes. Pin to a commit if you need stability.

| Version | Supported |
| ------- | --------- |
| `main` / `0.1.0` | ✅ |
| older commits | ❌ |

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately via GitHub:

1. Go to the repository's **Security** tab → **Report a vulnerability**
   (GitHub *private vulnerability reporting*). If that button isn't present,
   the maintainer can enable it under **Settings → Advanced Security →
   Private vulnerability reporting**.
2. Include: affected file/component, reproduction steps or a proof of concept,
   impact, and any suggested fix.

You'll get an acknowledgement as soon as the maintainer sees it. Because this is
a single-maintainer hobby project, please allow reasonable time before any
public disclosure, and coordinate a disclosure date in the report thread.

## Security model

**Local-only by design.** The classifier binds to `127.0.0.1:8723`. Image
content is fetched and classified on your machine; only a verdict
(`block`/`allow` + score) is returned to the extension. No image bytes or
browsing URLs are sent to any third party.

Hardening that is implemented today:

- **Authenticated classify endpoint.** `POST /classify` requires the
  `X-ImgEdge-Token` header (constant-time compared). The token is taken from
  `IMGEDGE_TOKEN`, or generated and persisted to `~/.imgedge_token` (mode
  `600`). `GET /health` is unauthenticated and returns only liveness + the
  target taxon.
- **No permissive CORS.** The server sends no `Access-Control-Allow-Origin`, so
  a web page cannot read responses or pass a JSON preflight to the local
  server. The extension reaches it via host permissions, which bypass CORS.
- **SSRF guard.** When the server fetches an image URL it resolves the host and
  refuses loopback, private, link-local, multicast, reserved, and unspecified
  addresses; allows only `http(s)`; **follows no redirects**; accepts only
  `200`; and caps the body at 8 MB with a short timeout. The `/classify`
  request body itself is capped at 16 MB.
- **Pinned model integrity.** Model/taxonomy downloads are pinned to a SHA-256
  and verified on download *and* before load; a mismatched file is refused.
  Python deps ship as hash-pinned lock files (`pip install --require-hashes`).
  The logfile is size-capped + rotated and never contains the token.
- **Decode hardening.** Image decoding caps pixels
  (`Image.MAX_IMAGE_PIXELS`, a decompression-bomb guard) and restricts the
  parsed formats to a raster allowlist (`JPEG, PNG, WEBP, GIF, BMP`), checking
  dimensions before any heavy decode.
- **Optional decode isolation (opt-in, off by default).** `IMGEDGE_SANDBOX=1`
  runs the Pillow decode in a recycled worker-process pool, so a decoder crash
  or exploit is contained to a short-lived child (recycled every N images) and a
  Job object caps each worker's committed memory and reaps it on exit. On
  Windows, `IMGEDGE_SANDBOX_APPCONTAINER=1` additionally runs each worker inside
  a capability-less **AppContainer**: a compromised decoder then cannot open a
  socket (network denied) or write your files, while Pillow/numpy still work via
  read-only grants to the Python install. The decoder returns only a trusted
  pixel array to the parent over an inherited pipe (no shared writable handles).
- **Bounded concurrency.** Requests are served by a fixed worker pool; failures
  fail open (configurable to fail closed / strict).
- **Minimal on-disk footprint.** The verdict cache is keyed by a SHA-256 hash of
  the URL (never the URL itself) and stores only verdicts.

## Known limitations & residual risks

These are deliberately documented rather than hidden:

- **Image-codec memory-safety bugs.** The pixel cap, format allowlist, and byte
  cap reduce exposure, but a crafted image could still trigger a vulnerability
  in an underlying decoder (Pillow / libjpeg / libpng / libwebp / zlib).
  **Mitigation:** keep `pillow` and other dependencies updated, and enable
  decode isolation -- `IMGEDGE_SANDBOX=1` (recycled subprocess pool, all
  platforms) or, on Windows, `IMGEDGE_SANDBOX_APPCONTAINER=1` (a capability-less
  AppContainer that denies the decoder network and writes to your files). Both
  are opt-in and **off by default**; with them disabled the decode runs
  in-process, so the pixel cap, format allowlist, and byte cap are the only
  guards. The AppContainer path needs a one-time, near-instant `icacls` grant of
  its SID on the Python install (reversible: `icacls <path> /remove:g *<sid>`).
- **Inline image data (`sendData`).** When enabled, a page can hand image bytes
  directly to the decoder, bypassing the SSRF *fetch* path. Exposure is similar
  to fetched public images and is bounded by the same decode hardening.
- **DNS rebinding.** The SSRF guard validates at resolve time and disables
  redirects, but a rebind to an internal IP between validation and fetch is a
  narrow residual risk.
- **Local access.** Any local process that knows the token can call
  `/classify`; the token is the access control. `/health` is unauthenticated and
  reveals only that ImgEdge is running and which taxon it targets.
- **Preload scanner.** The extension prevents blocked images from being
  *displayed*, but the browser may have already issued the initial network
  request; ImgEdge does not block at the network layer by default.
- **Model files.** The iNaturalist model is downloaded over HTTPS from GitHub
  Releases and verified against a pinned SHA-256, and the server refuses a
  mismatched model. The pins were captured on first download (trust-on-first-
  use), so cross-check them independently if you need stronger provenance.

## Hardening recommendations for users

- Keep Python dependencies current: `pip install -U pillow onnxruntime*`.
- Leave the access token enabled (don't set an empty `IMGEDGE_TOKEN`).
- On Windows, consider `IMGEDGE_SANDBOX_APPCONTAINER=1` to decode untrusted
  images in a no-network AppContainer (the first run does a one-time, near-instant
  icacls grant of the container's read access to your Python install).
- Set `IMGEDGE_CACHE_FILE=none` if you don't want any verdicts persisted.
- The classifier never needs inbound network or elevated privileges — run it as
  your normal user and don't expose port `8723` beyond `127.0.0.1`.

## Out of scope

- **Classification accuracy.** False positives/negatives (an image wrongly
  blocked or shown) are quality issues, not security vulnerabilities.
- **Third-party model behavior** (iNaturalist vision model) beyond integrity of
  the download.
- **Browser/extension-platform vulnerabilities** in Edge/Chromium itself.
