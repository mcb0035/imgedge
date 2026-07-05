// Copyright the ImgEdge contributors.
// SPDX-License-Identifier: Apache-2.0
/* ImgEdge background service worker.
 * Owns settings + lists (whitelist URLs, allowed domains, blocklist URLs) and
 * talks to the local classifier. Also wires the right-click context menu so the
 * user can allow/block any image or allow a whole site. It only returns a
 * verdict { allow, reason, score } — content scripts decide how to render.
 */

const KEYS = {
  settings: "imgedge:settings",
  whitelist: "imgedge:whitelist",
  domains: "imgedge:domains",
  blocklist: "imgedge:blocklist",
};

const DEFAULTS = {
  enabled: true,
  endpoint: "http://localhost:8723/classify",
  token: "", // shared secret the local classifier requires (from its console)
  sendData: false, // POST base64 image bytes in addition to the URL
  failClosed: false, // block when the classifier can't be reached
  inBrowserFallback: true, // if the server is unreachable, classify locally in an offscreen document
  strict: false, // block by default; show only what the classifier explicitly allows
  scanBackgrounds: true, // also filter CSS background / list images
  threshold: 0.5, // block threshold, sent per request (lower = block more); popup slider
  salience: 1.0, // size/detail weighting strength 0..1 (lower = block more); popup slider
  profile: "balanced", // easy-mode preset: which voter subset to run; popup selector
};

const MENUS = [
  { id: "imgedge-allow", titleKey: "menuAllowImage" },
  { id: "imgedge-block", titleKey: "menuBlockImage" },
  { id: "imgedge-allow-domain", titleKey: "menuAllowDomain" },
  { id: "imgedge-explain", titleKey: "menuExplain" },
];

chrome.runtime.onInstalled.addListener(async () => {
  const cur = await chrome.storage.local.get(Object.values(KEYS));
  const patch = {};
  if (!cur[KEYS.settings]) patch[KEYS.settings] = DEFAULTS;
  if (!cur[KEYS.whitelist]) patch[KEYS.whitelist] = [];
  if (!cur[KEYS.domains]) patch[KEYS.domains] = [];
  if (!cur[KEYS.blocklist]) patch[KEYS.blocklist] = [];
  if (Object.keys(patch).length) await chrome.storage.local.set(patch);
  setupMenus();
});

if (chrome.runtime.onStartup) chrome.runtime.onStartup.addListener(setupMenus);

function setupMenus() {
  if (!chrome.contextMenus) return;
  chrome.contextMenus.removeAll(() => {
    for (const m of MENUS) {
      chrome.contextMenus.create({ id: m.id, title: chrome.i18n.getMessage(m.titleKey), contexts: ["all"] });
    }
  });
}

if (chrome.contextMenus) {
  chrome.contextMenus.onClicked.addListener((info, tab) => {
    if (!tab || tab.id < 0) return;
    const action =
      info.menuItemId === "imgedge-allow" ? "allow" :
      info.menuItemId === "imgedge-block" ? "block" :
      info.menuItemId === "imgedge-allow-domain" ? "allow-domain" :
      info.menuItemId === "imgedge-explain" ? "explain" : null;
    if (!action) return;
    const payload = { type: "context", action, srcUrl: info.srcUrl || null };
    const opts = info.frameId != null ? { frameId: info.frameId } : undefined;
    chrome.tabs.sendMessage(tab.id, payload, opts, () => void chrome.runtime.lastError);
  });
}

// ---- Badge counters + classifier health -----------------------------------
const CLASSIFY_TIMEOUT_MS = 15000; // headroom for a slow classifier (server fetch is 6s)
const BADGE_COLOR = "#c0392b";       // blocked-count badge
const HEALTH_BAD_COLOR = "#5f6368";  // classifier error / model missing
const tabCounts = new Map(); // tabId -> Map<frameId, { allow, block }>

// "unknown" until the first classify call; then "ok" | "model-missing" | "error".
let health = "unknown";

if (chrome.action && chrome.action.setBadgeBackgroundColor) {
  chrome.action.setBadgeBackgroundColor({ color: BADGE_COLOR });
}

function healthBad() {
  return health === "error" || health === "model-missing";
}

function sumTab(tabId) {
  const frames = tabCounts.get(tabId);
  const total = { allow: 0, block: 0 };
  if (frames) for (const c of frames.values()) { total.allow += c.allow; total.block += c.block; }
  return total;
}

function badgeTitle(tabId) {
  if (health === "error") return chrome.i18n.getMessage("badgeUnreachable");
  if (health === "model-missing") return chrome.i18n.getMessage("badgeModelMissing");
  const { allow, block } = sumTab(tabId);
  return chrome.i18n.getMessage("badgeCounts", [String(allow), String(block)]);
}

function applyBadge(tabId) {
  if (!chrome.action) return;
  let text;
  if (healthBad()) text = "!";
  else { const b = sumTab(tabId).block; text = b ? String(b) : ""; }
  chrome.action.setBadgeText({ tabId, text });
  chrome.action.setTitle({ tabId, title: badgeTitle(tabId) });
}

function setHealth(next) {
  if (next === health || !chrome.action) { health = next; return; }
  health = next;
  chrome.action.setBadgeBackgroundColor({ color: healthBad() ? HEALTH_BAD_COLOR : BADGE_COLOR });
  // Default badge covers tabs with no per-tab text; then refresh known tabs.
  chrome.action.setBadgeText({ text: healthBad() ? "!" : "" });
  for (const tabId of tabCounts.keys()) applyBadge(tabId);
}

function recordTally(tabId, frameId, counts) {
  let frames = tabCounts.get(tabId);
  if (!frames) { frames = new Map(); tabCounts.set(tabId, frames); }
  frames.set(frameId, { allow: counts.allow | 0, block: counts.block | 0 });
  applyBadge(tabId);
}

function clearTab(tabId) {
  tabCounts.delete(tabId);
  applyBadge(tabId);
}

if (chrome.tabs && chrome.tabs.onUpdated) {
  chrome.tabs.onUpdated.addListener((tabId, info) => { if (info.status === "loading") clearTab(tabId); });
}
if (chrome.tabs && chrome.tabs.onRemoved) {
  chrome.tabs.onRemoved.addListener((tabId) => tabCounts.delete(tabId));
}

// ---- Storage helpers -------------------------------------------------------
async function getSettings() {
  const r = await chrome.storage.local.get([KEYS.settings]);
  return Object.assign({}, DEFAULTS, r[KEYS.settings] || {});
}

async function getList(key) {
  const r = await chrome.storage.local.get([key]);
  return r[key] || [];
}

async function addTo(key, value) {
  const list = await getList(key);
  if (!list.includes(value)) {
    list.push(value);
    await chrome.storage.local.set({ [key]: list });
  }
}

async function removeFrom(key, value) {
  const list = (await getList(key)).filter((v) => v !== value);
  await chrome.storage.local.set({ [key]: list });
}

function hostOf(url) {
  try {
    return new URL(url).hostname;
  } catch {
    return "";
  }
}

// ---- Image bytes -----------------------------------------------------------
const MAX_FETCH_BYTES = 8 * 1024 * 1024; // match the server's MAX_IMAGE_BYTES

function bufferToBase64(buf) {
  let binary = "";
  const bytes = new Uint8Array(buf);
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

async function fetchAsDataUrl(url) {
  try {
    const r = await fetch(url);
    if (!r.ok) return null;
    const len = parseInt(r.headers.get("Content-Length") || "", 10);
    if (len > MAX_FETCH_BYTES) return null;            // skip oversized before buffering
    const buf = await r.arrayBuffer();
    if (buf.byteLength > MAX_FETCH_BYTES) return null;  // and after, if no header
    const type = r.headers.get("Content-Type") || "application/octet-stream";
    return `data:${type};base64,${bufferToBase64(buf)}`;
  } catch {
    return null;
  }
}

// ---- Server identity (anti port-squatting, F2) -----------------------------
// Verify the classifier proves it knows the token (HMAC challenge) before we
// send the token to it, so a local process that squatted the port can't
// impersonate it. Cached per (endpoint, token) for the worker's lifetime.
let serverTrust = { endpoint: null, token: null, ok: false };

async function hmacHex(keyStr, msgStr) {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw", enc.encode(keyStr), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(msgStr));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function eqHex(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}

async function ensureServerTrusted(s) {
  if (!s.token) return true; // nothing to verify against; server will 401 anyway
  if (serverTrust.ok && serverTrust.endpoint === s.endpoint && serverTrust.token === s.token) {
    return true;
  }
  try {
    const nonce = crypto.randomUUID();
    const cu = new URL("/health", s.endpoint);
    cu.searchParams.set("challenge", nonce);
    const r = await fetch(cu.href, { method: "GET" });
    if (r.ok) {
      const j = await r.json();
      if (eqHex(await hmacHex(s.token, nonce), j.proof)) {
        serverTrust = { endpoint: s.endpoint, token: s.token, ok: true };
        return true;
      }
    }
  } catch { /* fall through: untrusted */ }
  return false; // don't cache failure; retry next call
}

// ---- In-browser fallback (offscreen document) ------------------------------
// When the local server is unreachable, classify with the bundled model in an
// offscreen document — MV3 service workers can't keep a model warm. No network
// and no token surface: the zero-install path. See extension/inbrowser/.
const OFFSCREEN_URL = "inbrowser/offscreen.html";
let offscreenReady = null;

async function ensureOffscreen() {
  if (!chrome.offscreen) return false; // browser too old for offscreen documents
  if (offscreenReady) return offscreenReady;
  offscreenReady = (async () => {
    try {
      await chrome.offscreen.createDocument({
        url: OFFSCREEN_URL,
        reasons: ["BLOBS"],
        justification: "Classify images locally with the bundled model (no server).",
      });
    } catch (e) {
      // A document may already exist (race / prior create): reuse it; else fail.
      if (!/single offscreen|already/i.test(String(e))) {
        offscreenReady = null;
        throw e;
      }
    }
    return true;
  })();
  return offscreenReady;
}

// Ask the offscreen document to classify; returns { ok, blocked, score } or null.
async function classifyInBrowser(url, data, threshold) {
  const dataUrl = data || (/^https?:/i.test(url) ? await fetchAsDataUrl(url) : null);
  if (!dataUrl) return null;
  if (!(await ensureOffscreen())) return null;
  const resp = await chrome.runtime.sendMessage({
    target: "offscreen",
    type: "inbrowser-classify",
    dataUrl,
    threshold,
  });
  return resp && resp.ok ? resp : null;
}

// Verdict when the server can't be used: try the in-browser fallback, else fail
// open/closed per settings.
async function unreachableVerdict(s, strict, url, data, reason, error) {
  if (s.inBrowserFallback) {
    try {
      const r = await classifyInBrowser(url, data, s.threshold);
      if (r) {
        setHealth("ok");
        return { allow: strict ? r.blocked === false : !r.blocked, reason: "inbrowser", score: r.score };
      }
    } catch { /* fall through to fail open/closed */ }
  }
  setHealth("error");
  return { allow: strict ? false : !s.failClosed, reason, error };
}

// ---- Classification --------------------------------------------------------
async function classify(url, data, meta) {
  const s = await getSettings();
  if (!s.enabled) return { allow: true };
  const strict = s.strict === true;

  const [whitelist, domains, blocklist] = await Promise.all([
    getList(KEYS.whitelist),
    getList(KEYS.domains),
    getList(KEYS.blocklist),
  ]);

  if (blocklist.includes(url)) return { allow: false, reason: "blocklist" };
  if (whitelist.includes(url)) return { allow: true };
  const host = hostOf(url);
  if (host && domains.includes(host)) return { allow: true };

  if (s.token && !(await ensureServerTrusted(s))) {
    return await unreachableVerdict(s, strict, url, data, "server-unverified");
  }

  const body = { url };
  if (meta) body.meta = meta;
  if (typeof s.threshold === "number") body.threshold = s.threshold;
  if (typeof s.salience === "number") body.salience = s.salience;
  if (typeof s.profile === "string") body.profile = s.profile;
  if (data) body.data = data;
  else if (s.sendData && /^https?:/i.test(url)) {
    const d = await fetchAsDataUrl(url);
    if (d) body.data = d;
  }

  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), CLASSIFY_TIMEOUT_MS);
    const headers = { "Content-Type": "application/json" };
    if (s.token) headers["X-ImgEdge-Token"] = s.token;
    let resp;
    try {
      resp = await fetch(s.endpoint, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
        signal: ctrl.signal,
      });
    } finally {
      clearTimeout(timer);
    }
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const json = await resp.json();
    setHealth(json && json.reason === "model-unavailable" ? "model-missing" : "ok");
    // Strict mode allows only an explicit "not blocked" answer.
    const allow = strict ? json.block === false : !json.block;
    return { allow, reason: json.reason, score: json.score, votes: json.votes, salience: json.salience, dbg: json.dbg };
  } catch (e) {
    // Classifier unreachable / timed out: try in-browser, else strict blocks / honor failClosed.
    return await unreachableVerdict(s, strict, url, data, strict ? "strict-blocked" : "classifier-error", String(e));
  }
}

// ---- Messaging -------------------------------------------------------------
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id) return false; // ignore non-extension senders
  if (msg && msg.target === "offscreen") return false; // handled by the offscreen document
  (async () => {
    try {
      switch (msg && msg.type) {
        case "getConfig":
          sendResponse({
            settings: await getSettings(),
            whitelist: await getList(KEYS.whitelist),
            domains: await getList(KEYS.domains),
            blocklist: await getList(KEYS.blocklist),
          });
          break;
        case "classify":
          sendResponse(await classify(msg.url, msg.data, msg.meta));
          break;
        case "tally":
          if (sender && sender.tab) recordTally(sender.tab.id, sender.frameId || 0, { allow: msg.allow, block: msg.block });
          sendResponse({ ok: true });
          break;
        case "getCounts":
          sendResponse(sumTab(msg.tabId));
          break;
        case "whitelistAdd":
          await addTo(KEYS.whitelist, msg.url);
          sendResponse({ ok: true });
          break;
        case "whitelistRemove":
          await removeFrom(KEYS.whitelist, msg.url);
          sendResponse({ ok: true });
          break;
        case "blocklistAdd":
          await addTo(KEYS.blocklist, msg.url);
          sendResponse({ ok: true });
          break;
        case "blocklistRemove":
          await removeFrom(KEYS.blocklist, msg.url);
          sendResponse({ ok: true });
          break;
        case "domainAdd":
          await addTo(KEYS.domains, msg.host);
          sendResponse({ ok: true });
          break;
        case "domainRemove":
          await removeFrom(KEYS.domains, msg.host);
          sendResponse({ ok: true });
          break;
        default:
          sendResponse({ error: "unknown-message" });
      }
    } catch (e) {
      sendResponse({ error: String(e), allow: true });
    }
  })();
  return true; // keep the message channel open for the async response
});
