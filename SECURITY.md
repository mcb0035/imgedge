# Security Policy

ImgEdge is a privacy tool: a browser extension plus a **local, on-device** image
classifier that blocks images of a chosen category. Its security goals are (1)
nothing about image *content* leaves your machine, and (2) the local classifier
can't be turned into a foothold by a web page or another local process.

## Supported versions

This is an early-stage personal project. Only the latest `main` (currently
`0.3.0`) receives security fixes. Pin to a commit if you need stability.

| Version | Supported |
| ------- | --------- |
| `main` / `0.3.0` | ✅ |
| older commits | ❌ |

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately via GitHub's [private vulnerability
reporting](https://github.com/mcb0035/imgedge/security/advisories/new):

1. Go to the repository's **Security** tab → **Report a vulnerability**
   (GitHub *private vulnerability reporting*). If that button isn't present,
   the maintainer can enable it under **Settings → Advanced Security →
   Private vulnerability reporting**.
2. Include: affected file/component, reproduction steps or a proof of concept,
   impact, and any suggested fix.

You'll get an acknowledgement **within 14 days** of the report — usually within a
few days (see the targets below). Please allow reasonable time before any public
disclosure, and coordinate a disclosure date in the report thread.

## Response and fix targets

ImgEdge is a **single-maintainer** project, so these are deliberately achievable
one-person commitments, not a staffed-team SLA. They are targets the maintainer
holds to — and anyone triaging or reviewing on the project's behalf is expected
to uphold them too.

| Commitment | Target |
| ---------- | ------ |
| **Acknowledge a vulnerability report** (initial response) | **≤ 14 days** from receipt, for every report. |
| **Fix a confirmed vulnerability** in ImgEdge's own code | **≤ 60 days** from confirmation for any **medium-or-higher severity** exploitable issue; criticals are prioritised immediately. |
| **Acknowledge a bug report** (non-security) | **≤ 14 days**; the acknowledgement need not include a fix. |
| **Respond to an enhancement request** | **≤ 30 days**; the response may be "yes", "no", or a discussion of merits. |

**Severity** uses the CVSS base qualitative score (v3.1 or later): *medium or
higher* is a base score of **4.0 or above**, taken from a recognised database
such as the [NVD](https://nvd.nist.gov/) when one exists, otherwise calculated by
the maintainer with the inputs disclosed once the issue is public.

**Findings from the project's own analysis are held to the same fix target.** A
medium-or-higher severity exploitable vulnerability confirmed by **static
analysis** (CodeQL, the CI Ruff ruleset) or **dynamic analysis** (the test suite
or the ClusterFuzzLite fuzzers) is fixed on the same **≤ 60-day** timeline after
it is confirmed. Where a given method has found no such vulnerability, that
method is N/A.

## Release notes and disclosure

ImgEdge is installed by users who update it themselves, so its release notes
carry vulnerability information (this is **not** N/A for us). Every release lists
— in [CHANGELOG.md](CHANGELOG.md) and the matching
[GitHub Release](https://github.com/mcb0035/imgedge/releases) — **every publicly
known run-time vulnerability in ImgEdge's own code that already had a CVE (or
comparable) identifier when the release was prepared**, with the identifier and
what/where it was fixed, so you can judge whether an update matters to you.

This covers the **project's own code only.** Vulnerabilities in third-party
dependencies are tracked continuously by `pip-audit` (CI), Dependabot, and the
OpenSSF Scorecard instead of being re-listed per release, because enumerating
every transitive dependency's advisories does not scale. A release that fixes no
such publicly known project vulnerability simply lists none.

## Security model

**Local-only by design.** The classifier binds to `127.0.0.1:8723`. Image
content is fetched and classified on your machine; only a verdict
(`block`/`allow` + score) is returned to the extension. No image bytes or
browsing URLs are sent to any third party.

Hardening that is implemented today:

- **Authenticated classify endpoint.** `POST /classify` requires the
  `X-ImgEdge-Token` header (constant-time compared). The token is taken from
  `IMGEDGE_TOKEN`, or generated and persisted to `~/.imgedge_token`, created
  atomically with owner-only perms (`O_EXCL`, mode `600`). `GET /health` is
  unauthenticated but returns only liveness (`status`, `model`); the target
  taxon, hardware provider, voters, and latency stats require the token.
- **Server-identity proof (anti port-squatting).** On request, `/health`
  returns `proof = HMAC(token, challenge)`; the extension verifies this *before*
  sending the token, so a local process that squatted `127.0.0.1:8723` (without
  the token) can't impersonate the classifier. On a port conflict it
  distinguishes an existing ImgEdge instance (reports it and exits cleanly)
  from another app holding the port (exits with guidance to set `IMGEDGE_PORT`).
- **Request read timeout.** Each connection has an inactivity timeout
  (`IMGEDGE_REQUEST_TIMEOUT`, default 15 s) so slow-drip (slowloris) clients
  can't tie up the bounded worker pool.
- **No permissive CORS.** The server sends no `Access-Control-Allow-Origin`, so
  a web page cannot read responses or pass a JSON preflight to the local
  server. The extension reaches it via host permissions, which bypass CORS.
- **SSRF guard.** When the server fetches an image URL it resolves the host and
  refuses loopback, private, link-local, CGNAT, multicast, reserved, and
  unspecified addresses (unwrapping IPv4-mapped and NAT64 IPv6 so an internal
  IPv4 can't hide inside an IPv6 wrapper); allows only `http(s)`; **pins the
  socket to the validated IP** so the host can't be rebound between check and
  connect; **follows no redirects**; restricts destination ports (default
  `80,443`); rejects non-image response content types; accepts only `200`; and
  caps the body at 8 MB with a short timeout plus a per-host concurrency limit.
  The `/classify` request body itself is capped at 16 MB. Egress can be locked
  down further with `IMGEDGE_FETCH_HTTPS_ONLY` and `IMGEDGE_FETCH_ALLOW_HOSTS`.
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
  Enabling one of these is **recommended for distributed installs or untrusted
  browsing**, as it is the primary containment for a decoder-level exploit.
- **Bounded concurrency.** Requests are served by a fixed worker pool; failures
  fail open (configurable to fail closed / strict).
- **Minimal on-disk footprint.** The verdict cache is keyed by a keyed hash
  (HMAC) of the URL (never the URL itself) and stores only verdicts.

## Cryptography

ImgEdge is not a cryptographic product and implements none of its own crypto — it
uses only standard, published primitives from the Python standard library:

- **Access token** — generated with `secrets.token_urlsafe(24)` (a CSPRNG,
  ~144 bits of entropy) and compared in constant time (`secrets.compare_digest`).
- **Cache keys & server-identity proof** — `HMAC-SHA-256` keyed by the token, so
  the on-disk cache can't confirm a guessed URL and a port-squatter can't forge
  the `/health` identity proof.
- **Asset integrity** — model / taxonomy files are pinned to a **SHA-256**,
  verified on download *and* before load; Python dependencies are hash-pinned
  (`pip install --require-hashes`).
- **Transport** — model downloads and image fetches use **HTTPS** (platform TLS);
  the fetch follows no redirects.

No broken or weak algorithms are used (no MD5, SHA-1, RC4, or single DES) and no
cipher modes are configured; SHA-256 and a ~144-bit token meet the NIST-2030
minimums. No user passwords are stored — the token is a random secret, not a
password — so no password hashing (Argon2/bcrypt/scrypt/PBKDF2) is involved. All
of the above is implementable with FLOSS (`hashlib`, `hmac`, `secrets`, platform
TLS).

## Verifying a release

Each [GitHub Release](https://github.com/mcb0035/imgedge/releases) ships the
extension ZIP with three independent, **keyless** ways to confirm it is genuine
and untampered — there is no long-lived signing key to trust or leak; the
signatures are bound to the release workflow's GitHub Actions OIDC identity and
logged in the public Sigstore transparency log. Replace `<ver>` with the version.

1. **Checksum** — the download matches the published hash:

   ```powershell
   (Get-FileHash imgedge-<ver>.zip -Algorithm SHA256).Hash.ToLower()   # compare to SHA256SUMS
   # on bash/zsh:  sha256sum -c SHA256SUMS
   ```

2. **Sigstore signature** over `SHA256SUMS` (needs
   [cosign](https://github.com/sigstore/cosign)):

   ```bash
   cosign verify-blob \
     --bundle SHA256SUMS.cosign.bundle \
     --certificate-identity-regexp '^https://github.com/mcb0035/imgedge/\.github/workflows/release\.yml@refs/tags/v' \
     --certificate-oidc-issuer https://token.actions.githubusercontent.com \
     SHA256SUMS
   ```

3. **Build provenance** (SLSA), tying the artifact to the workflow that built it
   (needs the [GitHub CLI](https://cli.github.com/)):

   ```bash
   gh attestation verify imgedge-<ver>.zip --repo mcb0035/imgedge
   ```

The same checks apply to `imgedge.crx` when a self-hosted `.crx` is published.

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
- **DNS rebinding.** Mitigated: the fetch resolves the host once, validates
  every returned address, and connects to that exact IP, so the destination
  can't be rebound to an internal address between the check and the connect.
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

- Keep Python dependencies current, e.g. `pip install -U pillow` (and whichever
  `onnxruntime` package you installed).
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
