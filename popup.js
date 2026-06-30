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
  failClosed: false,
  strict: false,
  scanBackgrounds: true,
};

const $ = (id) => document.getElementById(id);

// id -> { key, removeType, isHost }
const LISTS = {
  whitelist: { key: KEYS.whitelist, removeType: "whitelistRemove", isHost: false },
  domains: { key: KEYS.domains, removeType: "domainRemove", isHost: true },
  blocklist: { key: KEYS.blocklist, removeType: "blocklistRemove", isHost: false },
};

async function load() {
  const data = await chrome.storage.local.get(Object.values(KEYS));
  const s = Object.assign({}, DEFAULTS, data[KEYS.settings] || {});
  $("enabled").checked = s.enabled;
  $("endpoint").value = s.endpoint;
  $("token").value = s.token;
  $("sendData").checked = s.sendData;
  $("failClosed").checked = s.failClosed;
  $("strict").checked = s.strict;
  $("scanBackgrounds").checked = s.scanBackgrounds;
  for (const id of Object.keys(LISTS)) renderList(id, data[LISTS[id].key] || []);
  loadCounts();
  checkHealth();
}

async function loadCounts() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) return;
    const c = await chrome.runtime.sendMessage({ type: "getCounts", tabId: tab.id });
    if (c) $("counts").textContent = `Allowed ${c.allow || 0} \u00B7 Blocked ${c.block || 0}`;
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
  let base;
  try { base = new URL(settings.endpoint || DEFAULTS.endpoint); }
  catch { setHealthLine(el, "bad", "Classifier: invalid endpoint"); return; }
  try {
    if (!settings.token) {
      const r = await fetch(new URL("/health", base).href, { method: "GET" });
      if (!r.ok) throw new Error(String(r.status));
      const j = await r.json();
      if (j.status !== "ok") setHealthLine(el, "warn", "Classifier: model not loaded");
      else setHealthLine(el, "warn", "Classifier: token required \u2014 paste server token");
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
      setHealthLine(el, "bad", "Classifier: identity NOT verified \u2014 possible impersonation");
      return;
    }
    // Verified: now safe to send the token for the detailed view.
    const r = await fetch(new URL("/health", base).href, {
      method: "GET", headers: { "X-ImgEdge-Token": settings.token },
    });
    if (!r.ok) throw new Error(String(r.status));
    const j = await r.json();
    if (j.status === "ok") {
      const prov = j.provider ? ` \u00B7 ${j.provider}` : "";
      const vote = j.voters && j.voters.length > 1 ? ` \u00B7 vote:${j.policy} \u00d7${j.voters.length}` : "";
      const perf = j.stats && j.stats.n ? ` \u00B7 ${j.stats.infer_ms}ms/img (n=${j.stats.n})` : "";
      setHealthLine(el, "ok", `Classifier: verified \u00B7 ${j.target} (${j.taxa} taxa)${prov}${vote}${perf}`);
    } else {
      setHealthLine(el, "warn", "Classifier: model not loaded");
    }
  } catch {
    setHealthLine(el, "bad", "Classifier: unreachable");
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
    li.textContent = "Empty.";
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
    btn.textContent = "Remove";
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

async function save() {
  const endpoint = $("endpoint").value.trim() || DEFAULTS.endpoint;
  const btn = $("save");
  if (!isLocalEndpoint(endpoint)) {
    btn.textContent = "Endpoint must be local (localhost)";
    setTimeout(() => (btn.textContent = "Save settings"), 1800);
    return;
  }
  const settings = {
    enabled: $("enabled").checked,
    endpoint,
    token: $("token").value.trim(),
    sendData: $("sendData").checked,
    failClosed: $("failClosed").checked,
    strict: $("strict").checked,
    scanBackgrounds: $("scanBackgrounds").checked,
  };
  await chrome.storage.local.set({ [KEYS.settings]: settings });
  btn.textContent = "Saved";
  setTimeout(() => (btn.textContent = "Save settings"), 1000);
}

$("save").addEventListener("click", save);
$("showToken").addEventListener("change", (e) => {
  $("token").type = e.target.checked ? "text" : "password";
});
load();
