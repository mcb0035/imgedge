// Copyright the ImgEdge contributors.
// SPDX-License-Identifier: Apache-2.0
const KEYS = {
  settings: "imgedge:settings",
  whitelist: "imgedge:whitelist",
  domains: "imgedge:domains",
  blocklist: "imgedge:blocklist",
};
const DEFAULTS = {
  enabled: true,
  endpoint: "http://localhost:8723/classify",
  token: "",
  sendData: false,
  inBrowserOnly: false,
  failClosed: false,
  strict: false,
  scanBackgrounds: true,
  threshold: 0.15,
  salience: 1.0,
  profile: "balanced", // easy-mode preset: fast | balanced | accurate
};

// Keys included when exporting/importing a config. Deliberately excludes `token`
// (a secret) and the allow/block lists (they contain URLs) -- see PRIVACY.md.
const EXPORT_KEYS = [
  "enabled", "endpoint", "sendData", "inBrowserOnly", "failClosed",
  "strict", "scanBackgrounds", "threshold", "salience", "profile",
];

const $ = (id) => document.getElementById(id);

// Fill data-i18n text/attributes from _locales (WebExtension i18n). Elements
// carry the source-language text inline as a fallback; this replaces it with the
// message for the user's locale. Runs once at load.
function applyI18n() {
  const t = (k) => chrome.i18n.getMessage(k);
  for (const el of document.querySelectorAll("[data-i18n]")) {
    const m = t(el.dataset.i18n);
    if (m) el.textContent = m;
  }
  for (const el of document.querySelectorAll("[data-i18n-placeholder]")) {
    const m = t(el.dataset.i18nPlaceholder);
    if (m) el.setAttribute("placeholder", m);
  }
  for (const el of document.querySelectorAll("[data-i18n-title]")) {
    const m = t(el.dataset.i18nTitle);
    if (m) el.setAttribute("title", m);
  }
}

// id -> { key, removeType, isHost }
const LISTS = {
  whitelist: { key: KEYS.whitelist, removeType: "whitelistRemove", isHost: false },
  domains: { key: KEYS.domains, removeType: "domainRemove", isHost: true },
  blocklist: { key: KEYS.blocklist, removeType: "blocklistRemove", isHost: false },
};

async function load() {
  applyI18n();
  const data = await chrome.storage.local.get(Object.values(KEYS));
  const s = Object.assign({}, DEFAULTS, data[KEYS.settings] || {});
  $("enabled").checked = s.enabled;
  $("endpoint").value = s.endpoint;
  $("token").value = s.token;
  $("sendData").checked = s.sendData;
  $("inBrowserOnly").checked = s.inBrowserOnly;
  $("failClosed").checked = s.failClosed;
  $("strict").checked = s.strict;
  $("scanBackgrounds").checked = s.scanBackgrounds;
  $("threshold").value = s.threshold;
  $("salience").value = s.salience;
  setProfile(s.profile);
  updateSliderLabels();
  for (const id of Object.keys(LISTS)) renderList(id, data[LISTS[id].key] || []);
  loadCounts();
  checkHealth();
}

async function loadCounts() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) return;
    const c = await chrome.runtime.sendMessage({ type: "getCounts", tabId: tab.id });
    if (c) $("counts").textContent = chrome.i18n.getMessage("countsLine", [String(c.allow || 0), String(c.block || 0)]);
  } catch {}
}

// Verify the classifier proves it knows the token (HMAC challenge) before we
// send the token to it, so a local port-squatter can't impersonate it (F2).
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

async function checkHealth() {
  const el = $("health");
  const data = await chrome.storage.local.get([KEYS.settings]);
  const settings = Object.assign({}, DEFAULTS, data[KEYS.settings] || {});
  if (settings.inBrowserOnly) {
    setHealthLine(el, "ok", chrome.i18n.getMessage("healthInBrowser"));
    return;
  }
  let base;
  try { base = new URL(settings.endpoint || DEFAULTS.endpoint); }
  catch { setHealthLine(el, "bad", chrome.i18n.getMessage("healthInvalidEndpoint")); return; }
  try {
    if (!settings.token) {
      const r = await fetch(new URL("/health", base).href, { method: "GET" });
      if (!r.ok) throw new Error(String(r.status));
      const j = await r.json();
      if (j.status !== "ok") setHealthLine(el, "warn", chrome.i18n.getMessage("healthModelNotLoaded"));
      else setHealthLine(el, "warn", chrome.i18n.getMessage("healthTokenRequired"));
      return;
    }
    // Identity check: challenge the server to prove it knows the token.
    const nonce = crypto.randomUUID();
    const cu = new URL("/health", base);
    cu.searchParams.set("challenge", nonce);
    const vr = await fetch(cu.href, { method: "GET" });
    if (!vr.ok) throw new Error(String(vr.status));
    const vj = await vr.json();
    if (!eqHex(await hmacHex(settings.token, nonce), vj.proof)) {
      setHealthLine(el, "bad", chrome.i18n.getMessage("healthIdentityUnverified"));
      return;
    }
    // Verified: now safe to send the token for the detailed view.
    const r = await fetch(new URL("/health", base).href, {
      method: "GET", headers: { "X-ImgEdge-Token": settings.token },
    });
    if (!r.ok) throw new Error(String(r.status));
    const j = await r.json();
    if (j.status === "ok") {
      const myVer = chrome.runtime.getManifest().version;
      const ver = j.version
        ? (j.version === myVer ? ` v${j.version}` : ` v${j.version} \u2260 ext v${myVer}`)
        : "";
      const prov = j.provider ? ` \u00B7 ${j.provider}` : "";
      const vote = j.voters && j.voters.length > 1 ? ` \u00B7 vote:${j.policy} \u00d7${j.voters.length}` : "";
      const perf = j.stats && j.stats.n ? ` \u00B7 ${j.stats.infer_ms}ms/img (n=${j.stats.n})` : "";
      setHealthLine(el, "ok", `${chrome.i18n.getMessage("healthVerified")}${ver} \u00B7 ${j.target} (${j.taxa} ${chrome.i18n.getMessage("taxaLabel")})${prov}${vote}${perf}`);
      applyProfiles(j.profiles);
    } else {
      setHealthLine(el, "warn", chrome.i18n.getMessage("healthModelNotLoaded"));
    }
  } catch {
    setHealthLine(el, "bad", chrome.i18n.getMessage("healthUnreachable"));
  }
}

function setHealthLine(el, cls, text) {
  el.className = "health " + cls;
  el.textContent = text;
}

function renderList(id, items) {
  const { removeType, isHost, key } = LISTS[id];
  const ul = $(id);
  ul.textContent = "";
  if (!items.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = chrome.i18n.getMessage("listEmpty");
    ul.appendChild(li);
    return;
  }
  items.forEach((value) => {
    const li = document.createElement("li");

    const span = document.createElement("span");
    span.className = "url";
    span.textContent = value;
    span.title = value;

    const btn = document.createElement("button");
    btn.textContent = chrome.i18n.getMessage("btnRemove");
    btn.addEventListener("click", async () => {
      const msg = { type: removeType };
      if (isHost) msg.host = value;
      else msg.url = value;
      await chrome.runtime.sendMessage(msg);
      const d = await chrome.storage.local.get([key]);
      renderList(id, d[key] || []);
    });

    li.appendChild(span);
    li.appendChild(btn);
    ul.appendChild(li);
  });
}

function isLocalEndpoint(u) {
  let x;
  try { x = new URL(u); } catch { return false; }
  if (x.protocol !== "http:" && x.protocol !== "https:") return false;
  const h = x.hostname.toLowerCase().replace(/^\[|\]$/g, "");
  return h === "localhost" || h === "127.0.0.1" || h === "::1";
}

// ---- Easy-mode presets -----------------------------------------------------
const PROFILE_ORDER = ["fast", "balanced", "accurate"];

function checkedProfile() {
  const r = document.querySelector('input[name="profile"]:checked');
  return r ? r.value : DEFAULTS.profile;
}

function setProfile(v) {
  const r = document.querySelector('input[name="profile"][value="' + v + '"]');
  if (r) r.checked = true;
}

async function persistProfile() {
  const data = await chrome.storage.local.get([KEYS.settings]);
  const s = Object.assign({}, DEFAULTS, data[KEYS.settings] || {});
  s.profile = checkedProfile();
  await chrome.storage.local.set({ [KEYS.settings]: s });
}

// Grey out presets whose voter isn't loaded on the server (from /health), and
// if the current choice is unavailable, fall back to the best available one.
function applyProfiles(profiles) {
  if (!profiles || typeof profiles !== "object") return;
  for (const r of document.querySelectorAll('input[name="profile"]')) {
    r.disabled = profiles[r.value] === false;
  }
  if (profiles[checkedProfile()] === false) {
    const best = [...PROFILE_ORDER].reverse().find((p) => profiles[p]) || "fast";
    setProfile(best);
    persistProfile();
  }
  const off = PROFILE_ORDER.filter((p) => profiles[p] === false);
  const hint = $("presethint");
  if (hint) {
    const names = off.map((p) => chrome.i18n.getMessage("preset" + p[0].toUpperCase() + p.slice(1))).join(" & ");
    hint.textContent = off.length ? chrome.i18n.getMessage("presetHintNeedsVoter", [names]) : "";
  }
}

async function save() {
  const endpoint = $("endpoint").value.trim() || DEFAULTS.endpoint;
  const btn = $("save");
  if (!isLocalEndpoint(endpoint)) {
    btn.textContent = chrome.i18n.getMessage("saveEndpointLocal");
    setTimeout(() => (btn.textContent = chrome.i18n.getMessage("btnSave")), 1800);
    return;
  }
  const settings = {
    enabled: $("enabled").checked,
    endpoint,
    token: $("token").value.trim(),
    sendData: $("sendData").checked,
    inBrowserOnly: $("inBrowserOnly").checked,
    failClosed: $("failClosed").checked,
    strict: $("strict").checked,
    scanBackgrounds: $("scanBackgrounds").checked,
    threshold: Number($("threshold").value),
    salience: Number($("salience").value),
    profile: checkedProfile(),
  };
  await chrome.storage.local.set({ [KEYS.settings]: settings });
  btn.textContent = chrome.i18n.getMessage("btnSaved");
  setTimeout(() => (btn.textContent = chrome.i18n.getMessage("btnSave")), 1000);
}

// ---- Backup: export / import (no token, no lists -- see PRIVACY.md) --------
function clamp(n, lo, hi) {
  return Math.min(hi, Math.max(lo, n));
}

// The exact object written to an export file: only the non-secret settings.
function buildExport(s) {
  const settings = {};
  for (const k of EXPORT_KEYS) settings[k] = s[k];
  return { app: "imgedge", kind: "settings", version: 1, settings };
}

// Merge an imported object into the current settings, applying ONLY the
// whitelisted keys with validation. The token is never read from the file (the
// current one is kept), the lists are untouched, and a non-local endpoint is
// ignored -- so importing a file can't leak a token, add URLs, or redirect the
// classifier off localhost.
function sanitizeImport(incoming, current) {
  const s = Object.assign({}, DEFAULTS, current || {});
  s.token = (current || {}).token || "";
  const src = incoming && typeof incoming.settings === "object" ? incoming.settings : incoming;
  if (!src || typeof src !== "object") return s;
  if (typeof src.endpoint === "string" && isLocalEndpoint(src.endpoint)) s.endpoint = src.endpoint;
  for (const k of ["enabled", "sendData", "failClosed", "strict", "scanBackgrounds"]) {
    if (typeof src[k] === "boolean") s[k] = src[k];
  }
  if (Number.isFinite(Number(src.threshold))) s.threshold = clamp(Number(src.threshold), 0.05, 0.95);
  if (Number.isFinite(Number(src.salience))) s.salience = clamp(Number(src.salience), 0, 1);
  if (PROFILE_ORDER.includes(src.profile)) s.profile = src.profile;
  return s;
}

function flash(btn, text) {
  const orig = btn._label || btn.textContent;
  btn._label = orig;
  btn.textContent = text;
  setTimeout(() => (btn.textContent = btn._label), 1400);
}

async function exportSettings() {
  const data = await chrome.storage.local.get([KEYS.settings]);
  const s = Object.assign({}, DEFAULTS, data[KEYS.settings] || {});
  const blob = new Blob([JSON.stringify(buildExport(s), null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "imgedge-settings.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
  flash($("exportSettings"), chrome.i18n.getMessage("flashExported"));
}

async function importSettings(file) {
  const btn = $("importSettings");
  let incoming;
  try {
    incoming = JSON.parse(await file.text());
  } catch {
    flash(btn, chrome.i18n.getMessage("flashInvalidFile"));
    return;
  }
  const data = await chrome.storage.local.get([KEYS.settings]);
  await chrome.storage.local.set({ [KEYS.settings]: sanitizeImport(incoming, data[KEYS.settings]) });
  await load();
  flash(btn, chrome.i18n.getMessage("flashImported"));
}

$("save").addEventListener("click", save);
$("showToken").addEventListener("change", (e) => {
  $("token").type = e.target.checked ? "text" : "password";
});

// Toggle checkboxes persist immediately (no Save needed), so enabling/disabling
// filtering sticks across page reloads and navigation. endpoint/token still use
// the Save button (endpoint needs localhost validation; the token is a paste field).
const TOGGLES = ["enabled", "sendData", "inBrowserOnly", "failClosed", "strict", "scanBackgrounds"];
async function persistToggle(id) {
  const data = await chrome.storage.local.get([KEYS.settings]);
  const s = Object.assign({}, DEFAULTS, data[KEYS.settings] || {});
  s[id] = $(id).checked;
  await chrome.storage.local.set({ [KEYS.settings]: s });
}
for (const id of TOGGLES) {
  $(id).addEventListener("change", () => persistToggle(id));
}

// Tuning sliders: update the live readout on input, persist on release (change).
const SLIDERS = ["threshold", "salience"];
function updateSliderLabels() {
  $("thresholdVal").textContent = Number($("threshold").value).toFixed(2);
  $("salienceVal").textContent = Number($("salience").value).toFixed(1);
}
async function persistSlider(id) {
  const data = await chrome.storage.local.get([KEYS.settings]);
  const s = Object.assign({}, DEFAULTS, data[KEYS.settings] || {});
  s[id] = Number($(id).value);
  await chrome.storage.local.set({ [KEYS.settings]: s });
}
for (const id of SLIDERS) {
  $(id).addEventListener("input", updateSliderLabels);
  $(id).addEventListener("change", () => persistSlider(id));
}

// Preset radios persist immediately (like the toggles).
for (const r of document.querySelectorAll('input[name="profile"]')) {
  r.addEventListener("change", persistProfile);
}

// Backup buttons: export downloads a JSON file; import reads one back.
$("exportSettings").addEventListener("click", exportSettings);
$("importSettings").addEventListener("click", () => $("importFile").click());
$("importFile").addEventListener("change", (e) => {
  const file = e.target.files && e.target.files[0];
  if (file) importSettings(file);
  e.target.value = ""; // allow re-importing the same file
});

load();
