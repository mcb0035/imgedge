# ImgEdge interface reference

The software ImgEdge produces exposes two external interfaces:

1. a **local HTTP API** — the classifier the browser extension talks to, and
2. a small **command-line interface** — to install models and run the server.

Everything is local: the server binds to loopback only and no image content
leaves the machine. For the tunables referenced below, see the
[configuration reference](configuration.md).

---

## HTTP API

| | |
|---|---|
| **Base URL** | `http://127.0.0.1:8723` (host fixed to loopback; port = `IMGEDGE_PORT`) |
| **Transport** | Plain HTTP over loopback — no TLS, **no CORS headers** (so a web page can't call it), no redirects |
| **Encoding** | `application/json`, UTF-8, request and response |
| **Auth** | `POST /classify` requires the header `X-ImgEdge-Token: <token>` (constant-time compared). `GET /health` is open for liveness and returns fuller detail *with* the token. |

The access token is printed by `imgedge-server` on start and persisted to
`~/.imgedge_token` (mode `0600`); paste it into the extension popup once.

### `POST /classify`

Classify one image and return a block/allow verdict.

**Request headers**

| Header | Required | Value |
|---|---|---|
| `X-ImgEdge-Token` | yes | the server's access token |
| `Content-Type` | recommended | `application/json` |

**Request body**

| Field | Type | Required | Meaning |
|---|---|---|---|
| `url` | string | yes\* | Image URL; the server fetches it (SSRF-guarded) unless `data` is supplied. |
| `data` | string | no | A `data:image/<type>;base64,…` data URL. When present, these bytes are classified directly and **no network fetch happens** (used for cookie/LAN-gated images). |
| `meta` | object | no | Page hints for salience: `{ "kind": "img\|input\|svg\|poster\|bg", "w": <int px>, "h": <int px> }`. |
| `threshold` | number | no | Per-request block-threshold override, clamped to `0..1` (the popup's slider). |
| `salience` | number | no | Per-request salience-weight override, clamped to `0..1`. |

\* Either `url` or `data` must identify an image; `data` alone still needs `url`
present as the cache key.

**Response** — `200 OK`

```json
{ "block": true, "reason": "arachnid: order Araneae (0.91)", "score": 0.91 }
```

| Field | Type | Meaning |
|---|---|---|
| `block` | boolean | `true` → hide the image; `false` → show it. |
| `reason` | string | Short human-readable explanation (voter/taxon that decided it, or a sentinel — see below). Never contains internal paths. |
| `score` | number | Final salience-scaled ensemble score in `0..1`. |

Sentinel `reason` values (always with `block: false`, `score: 0.0`):
`model-unavailable` (model not loaded), `fetch-failed` (couldn't retrieve the
URL — transient, not cached), `error` (un-decodable/crafted input — the detail is
logged locally, not returned).

**Status codes**

| Code | Body | When |
|---|---|---|
| `200` | verdict | Always for an authorized `/classify`, including un-decodable input (fails open: `block:false`). |
| `401` | `{"error":"unauthorized"}` | Missing/invalid token. |
| `413` | `{"error":"payload too large"}` | Body exceeds 16 MB. |
| `404` | — | Any path other than `/classify`. |

**Limits** — request body ≤ **16 MB**, decoded image ≤ **8 MB**, per-connection
read timeout **15 s** (`IMGEDGE_REQUEST_TIMEOUT`, a slowloris guard).

**Example**

```powershell
$token = Get-Content ~/.imgedge_token
Invoke-RestMethod -Uri http://127.0.0.1:8723/classify -Method Post `
  -Headers @{ "X-ImgEdge-Token" = $token } `
  -ContentType "application/json" `
  -Body '{"url":"https://example.com/cat.jpg","meta":{"kind":"img","w":800,"h":600}}'
```

### `GET /health`

Liveness and (with the token) configuration status — used by the popup badge.

**Query parameters**

| Param | Meaning |
|---|---|
| `challenge` | Optional nonce. The response adds `proof = HMAC-SHA256(token, challenge)` (hex), letting the extension confirm it's talking to the real server (which knows the token) without sending the token first — an anti port-squatting check. |

**Response** — `200 OK`. Unauthenticated callers get liveness only:

```json
{ "status": "ok", "model": true, "auth_required": true }
```

With a valid `X-ImgEdge-Token`, the full payload adds configuration + telemetry:

| Field | Type | Meaning |
|---|---|---|
| `status` | string | `ok` or `model-missing`. |
| `model` | boolean | Whether the vision model is loaded. |
| `auth_required` | boolean | Always `true`. |
| `version` | string | Server version. |
| `target` | string | Blocked taxon (e.g. `Arachnida`). |
| `threshold` | number | Active block threshold. |
| `taxa` | number | Count of taxa matched under the target. |
| `backend` | string | Model backend (`tflite` / `onnx`). |
| `provider` | string | Execution provider (`cpu`, `npu`, `cuda`, …). |
| `voters` | string[] | Active voter names. |
| `policy` | string | Ensemble policy (`evidence`, `any`, …). |
| `inat_override` | number | iNat P(block) that blocks outright. |
| `stats` | object\|null | Rolling latency snapshot when `IMGEDGE_PROFILE=1`. |
| `sandbox` | string\|null | `appcontainer`, `process`, or `null`. |

Any path other than `/health` returns `404`.

---

## Command-line interface

Installed as console scripts by `pip install -e .`:

| Command | What it does |
|---|---|
| `imgedge-server` | Start the local classifier (prints the access token). Honours all `IMGEDGE_*` [environment variables](configuration.md). |
| `imgedge-download-models` | Download and SHA-256-verify the iNaturalist vision model + taxonomy into `src/imgedge/inat/models/`. |

Supporting module entry points:

| Command | What it does |
|---|---|
| `python -m imgedge.inat.inat_vision <image>` | Rank the top iNaturalist taxa for one local image (diagnostic). |
| `python -m imgedge.inat.convert_to_onnx` | Convert the bundled TFLite model to ONNX for the GPU/NPU backend. |

---

## Extension ↔ server

The extension is the primary client of the HTTP API:
[`content.js`](../content.js) reports each image's URL and rendered size/kind;
[`background.js`](../background.js) `POST`s them to the configured endpoint with
the token and applies the verdict. See the
[README security model](../README.md#security-model) for the trust boundaries and
[SECURITY.md](../SECURITY.md) for the hardening detail.
