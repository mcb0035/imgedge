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

async function checkHealth() {
  const el = $("health");
  const data = await chrome.storage.local.get([KEYS.settings]);
  const settings = Object.assign({}, DEFAULTS, data[KEYS.settings] || {});
  let healthUrl;
  try { healthUrl = new URL("/health", settings.endpoint || DEFAULTS.endpoint).href; }
  catch { healthUrl = null; }
  if (!healthUrl) { setHealthLine(el, "bad", "Classifier: invalid endpoint"); return; }
  try {
    const r = await fetch(healthUrl, { method: "GET" });
    if (!r.ok) throw new Error(String(r.status));
    const j = await r.json();
    if (j.auth_required && !settings.token) {
      setHealthLine(el, "warn", "Classifier: token required \u2014 paste server token");
    } else if (j.status === "ok") {
      const prov = j.provider ? ` \u00B7 ${j.provider}` : "";
      const vote = j.voters && j.voters.length > 1 ? ` \u00B7 vote:${j.policy} \u00d7${j.voters.length}` : "";
      setHealthLine(el, "ok", `Classifier: connected \u00B7 ${j.target} (${j.taxa} taxa)${prov}${vote}`);
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

async function save() {
  const settings = {
    enabled: $("enabled").checked,
    endpoint: $("endpoint").value.trim() || DEFAULTS.endpoint,
    token: $("token").value.trim(),
    sendData: $("sendData").checked,
    failClosed: $("failClosed").checked,
    strict: $("strict").checked,
    scanBackgrounds: $("scanBackgrounds").checked,
  };
  await chrome.storage.local.set({ [KEYS.settings]: settings });
  const btn = $("save");
  btn.textContent = "Saved";
  setTimeout(() => (btn.textContent = "Save settings"), 1000);
}

$("save").addEventListener("click", save);
load();
