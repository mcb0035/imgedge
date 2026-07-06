# ImgEdge configuration reference

ImgEdge is configured in two places: **per-browser settings in the extension
popup**, and **server-side environment variables**. The popup's tuning sliders
are sent with each request, so they override the server defaults live. For the
request/response shape these values affect, see the
[interface reference](api.md).

## Popup (per-browser)

The **Detection mode** presets pick how many voters run per image -- **Fast**
(iNat + timm), **Balanced** (+ MobileCLIP), or **Accurate** (+ SigLIP) -- trading
speed for thoroughness; a preset whose voter isn't loaded on the server is greyed
out. Everything else lives under **Advanced**: enable/disable, classifier
endpoint + token, *Send image bytes* (for cookie/LAN-gated images), *Block when
classifier unreachable* (fail-closed), *Strict mode* (block until explicitly
allowed), *Scan CSS backgrounds*, and the **Block threshold** and **Salience
weighting** tuning sliders (sent per request, so they tune live and override the
server defaults below). The whitelist / allowed-sites / blocklist stay visible.

**In-browser Fast mode.** *Classify in the browser (no server needed)*
(`inBrowserOnly`) runs the iNat + timm ensemble entirely client-side, so no local
server is required. Even with it off, ImgEdge falls back to in-browser
classification whenever the server is unreachable (`inBrowserFallback`, on by
default). Either way the bundled models run in an offscreen document via ONNX
Runtime Web — see the [in-browser Fast mode notes](../extension/inbrowser/README.md).

Under **Advanced → Backup**, *Export settings* saves your setup to a JSON file and
*Import settings* loads one back. The file holds only the detection mode, sliders,
toggles, and endpoint — never your token or any allow/block URLs. All settings and
lists live in the browser's local `chrome.storage.local` and never leave your
machine (see [PRIVACY.md](../PRIVACY.md)).

## Server (environment variables)

| Variable | Default | Purpose |
|----------|---------|---------|
| `IMGEDGE_TARGET` | `Arachnida` | Taxon to block (any iNaturalist name, e.g. `Araneae` for spiders only) |
| `IMGEDGE_THRESHOLD` | `0.18` | Block when the (salience-scaled) ensemble score ≥ this. The extension popup sends its own **Block threshold** (default `0.15`) as a per-request override, so `0.15` is the effective value for extension traffic. |
| `IMGEDGE_VOTE` | `evidence` | Ensemble policy: `evidence\|any\|all\|majority\|weighted` |
| `IMGEDGE_TIMM_MODEL` | `mobilenetv3_large_100.ra_in1k` | timm/HF model id for the second voter |
| `IMGEDGE_TIMM_EXCLUDE` | arachnid set | ImageNet terms (comma-sep) to **block** |
| `IMGEDGE_TIMM_CONTRAST` | look-alike set | ImageNet terms that argue **against** a block |
| `IMGEDGE_TIMM_CONTRAST_WEIGHT` | `0.0` | How hard look-alike evidence counts |
| `IMGEDGE_TIMM_THRESHOLD` | `0.5` | timm voter's own block threshold |
| `IMGEDGE_TIMM_WEIGHT` | `0.5` | timm evidence weight in the ensemble |
| `IMGEDGE_INAT_OVERRIDE` | `0.9` | iNat P(block) at/above which it blocks outright, ignoring the contrast voter (`>1` disables) |
| `IMGEDGE_SIGLIP` | `1` | Load the open-vocab SigLIP 2 third voter when its `siglip` extra is installed (`0`=skip) |
| `IMGEDGE_SIGLIP_MODEL` | `google/siglip2-base-patch16-224` | HF SigLIP model id for the third voter |
| `IMGEDGE_SIGLIP_WEIGHT` | `2.0` | SigLIP evidence weight in the ensemble |
| `IMGEDGE_SIGLIP_GATE` | `0.0` | Cascade floor: skip SigLIP below this iNat+timm score (`0`=only when already blocking; raise to trade recall for speed) |
| `IMGEDGE_MOBILECLIP` | `1` | Load the MobileCLIP voter (smaller/faster open-vocab alternative to SigLIP) when its `mobileclip` extra is installed (`0`=skip) |
| `IMGEDGE_MOBILECLIP_WEIGHT` | `1.0` | MobileCLIP evidence weight in the ensemble |
| `IMGEDGE_EP` | `auto` | ONNX provider: `auto\|npu\|ovgpu\|cuda\|dml\|cpu` |
| `IMGEDGE_POOL` | `min(4, cpus)` | TFLite interpreter pool size |
| `IMGEDGE_WORKERS` | `8` | Max concurrent HTTP request workers |
| `IMGEDGE_REQUEST_TIMEOUT` | `15` | Per-connection read timeout, seconds (slowloris guard) |
| `IMGEDGE_PORT` | `8723` | Local classifier port (host stays `127.0.0.1`); change to avoid a conflict |
| `IMGEDGE_FETCH_PORTS` | `80,443` | Allowed image-fetch destination ports (`any` for no limit) |
| `IMGEDGE_FETCH_HTTPS_ONLY` | `0` | Refuse plaintext `http://` image URLs |
| `IMGEDGE_FETCH_ALLOW_HOSTS` | _(none)_ | If set, fetch only from these domains (comma-sep; subdomains included) |
| `IMGEDGE_FETCH_PER_HOST` | `4` | Max concurrent fetches to a single host (`0` disables) |
| `IMGEDGE_FETCH_UA` | _(generic browser)_ | `User-Agent` the server sends when fetching an image |
| `IMGEDGE_TOKEN` / `IMGEDGE_TOKEN_FILE` | generated → `~/.imgedge_token` | Access token |
| `IMGEDGE_CACHE_FILE` | `~/.imgedge_cache.json` | Verdict cache (`none` to disable) |
| `IMGEDGE_LOG_FILE` | `~/.imgedge.log` | Rotating log (1MB×3 ≈ 4MB cap; `none` to disable) |
| `IMGEDGE_LOG_LEVEL` | `INFO` | `DEBUG\|INFO\|WARNING\|ERROR` |
| `IMGEDGE_PROFILE` | `1` | Expose rolling latency stats in `/health` (`0` = off) |
| `IMGEDGE_SANDBOX` | `0` | Decode images in a recycled worker-process pool (crash isolation + per-worker memory cap) |
| `IMGEDGE_SANDBOX_APPCONTAINER` | `0` | Windows: decode each image in a no-network AppContainer (one-time, near-instant `icacls` grant on first run) |
| `IMGEDGE_MODEL` / `IMGEDGE_ONNX` / `IMGEDGE_TAXONOMY` | under `src/imgedge/inat/models/` | Model/taxonomy paths |

See the [README security model](../README.md#security-model) for the reasoning
behind the fetch and sandbox defaults.
