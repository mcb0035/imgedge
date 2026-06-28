/* ImgEdge content script — filters every image surface the user can see:
 *   <img> (incl. <picture>/<source> and srcset), <input type="image">,
 *   SVG <image>, <video poster>, and CSS background-image / list-style-image.
 * Each surface is hidden until the local classifier returns a verdict, then
 * revealed or blocked. Per-image overrides: click a blocked placeholder, or
 * right-click any image to allow / block / allow-this-site (context menu).
 *
 * Note: surfaces in the initial HTML may be partially fetched by the browser's
 * preload scanner before this script reaches them; they are always prevented
 * from being *displayed*. Truly stopping those bytes needs declarativeNetRequest,
 * which can't consult an async classifier, so the decision lives here.
 */
(() => {
  "use strict";
  if (window.__imgEdgeInjected) return;
  window.__imgEdgeInjected = true;

  const STATE = "imgedge";
  const PENDING = "pending", BLOCKED = "blocked", ALLOWED = "allowed";
  const SVG_NS = "http://www.w3.org/2000/svg";
  const XLINK = "http://www.w3.org/1999/xlink";

  const lists = {
    enabled: true,
    strict: false,
    scanBackgrounds: true,
    whitelist: new Set(),
    domains: new Set(),
    blocklist: new Set(),
  };

  const tracked = new Map();     // Element -> descriptor
  const verdicts = new Map();    // url -> Promise<{ allow, reason }>
  const totals = { allow: 0, block: 0 }; // per-frame counts for the toolbar badge
  let flushTimer = null;
  const selfMut = new WeakSet(); // elements we are mutating (ignored by observer)
  const bgSeen = new WeakSet();  // elements already queued for background scan
  const bgQueue = [];
  let bgScheduled = false;
  let lastContextEl = null;

  const ready = init();

  async function init() {
    try {
      applyConfig(await chrome.runtime.sendMessage({ type: "getConfig" }));
    } catch {
      /* background unavailable -> keep fail-open defaults */
    }
  }

  function applyConfig(r) {
    if (!r) return;
    const s = r.settings || {};
    lists.enabled = s.enabled !== false;
    lists.strict = s.strict === true;
    lists.scanBackgrounds = s.scanBackgrounds !== false;
    lists.whitelist = new Set(r.whitelist || []);
    lists.domains = new Set(r.domains || []);
    lists.blocklist = new Set(r.blocklist || []);
  }

  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "local") return;
    let touched = false;
    if (changes["imgedge:settings"]) {
      const s = changes["imgedge:settings"].newValue || {};
      lists.enabled = s.enabled !== false;
      lists.strict = s.strict === true;
      lists.scanBackgrounds = s.scanBackgrounds !== false;
      touched = true;
    }
    if (changes["imgedge:whitelist"]) { lists.whitelist = new Set(changes["imgedge:whitelist"].newValue || []); touched = true; }
    if (changes["imgedge:domains"]) { lists.domains = new Set(changes["imgedge:domains"].newValue || []); touched = true; }
    if (changes["imgedge:blocklist"]) { lists.blocklist = new Set(changes["imgedge:blocklist"].newValue || []); touched = true; }
    if (touched) { verdicts.clear(); reevaluate(); }
  });

  // ---- URL helpers ---------------------------------------------------------
  function abs(u) { try { return new URL(u, document.baseURI).href; } catch { return ""; } }
  function hostOf(u) { try { return new URL(u).hostname; } catch { return ""; } }
  function firstCssUrl(value) {
    if (!value || value === "none") return "";
    const m = /url\(\s*(['"]?)([^'")]+)\1\s*\)/i.exec(value);
    return m ? abs(m[2]) : "";
  }
  function usable(url) { return !!url && !url.startsWith("about:"); }

  // ---- Verdicts ------------------------------------------------------------
  function localVerdict(url) {
    if (!lists.enabled) return "allow";
    if (lists.blocklist.has(url)) return "block";
    if (lists.whitelist.has(url)) return "allow";
    const h = hostOf(url);
    if (h && lists.domains.has(h)) return "allow";
    return null;
  }

  function blobToDataUrl(url) {
    return fetch(url).then((r) => r.blob()).then(
      (blob) => new Promise((res, rej) => {
        const fr = new FileReader();
        fr.onload = () => res(fr.result);
        fr.onerror = () => rej(fr.error);
        fr.readAsDataURL(blob);
      })
    );
  }

  async function getVerdict(url) {
    const lv = localVerdict(url);
    if (lv) return { allow: lv === "allow", reason: lv === "block" ? "blocklist" : undefined };
    if (verdicts.has(url)) return verdicts.get(url);
    const p = (async () => {
      let data;
      if (url.startsWith("blob:")) data = await blobToDataUrl(url).catch(() => null);
      try { return await chrome.runtime.sendMessage({ type: "classify", url, data }); }
      catch { return { allow: !lists.strict }; }
    })();
    verdicts.set(url, p);
    return p;
  }

  function reevaluate() {
    for (const d of tracked.values()) {
      const lv = localVerdict(d.url);
      if (lv === "allow") applyVerdict(d, true);
      else if (lv === "block") applyVerdict(d, false, "blocklist");
      // unknown -> leave the current state untouched
    }
  }

  // ---- Badge tally ---------------------------------------------------------
  function scheduleFlush() {
    if (flushTimer) return;
    flushTimer = setTimeout(flushTally, 300);
  }
  function flushTally() {
    flushTimer = null;
    try { chrome.runtime.sendMessage({ type: "tally", allow: totals.allow, block: totals.block }); } catch {}
  }
  function tally(d, state) {
    if (d.counted === state) return;
    if (d.counted === "allow") totals.allow--;
    else if (d.counted === "block") totals.block--;
    if (state === "allow") totals.allow++; else totals.block++;
    d.counted = state;
    scheduleFlush();
  }
  function applyVerdict(d, allow, reason) {
    if (allow) d.reveal(); else d.block(reason);
    tally(d, allow ? "allow" : "block");
  }

  // ---- Mutation guard (ignore our own DOM edits in the observer) -----------
  function mutate(el, fn) {
    selfMut.add(el);
    try { fn(); } finally { queueMicrotask(() => selfMut.delete(el)); }
  }

  // ---- Placeholder (only for <img> / <input type=image>) -------------------
  function makePlaceholder(el, url, reason) {
    const ph = document.createElement("span");
    ph.className = "imgedge-placeholder";
    ph.setAttribute("role", "button");
    ph.setAttribute("tabindex", "0");
    ph.title = url || "";
    ph.textContent =
      "\u{1F6AB} Blocked" + (reason ? " \u00B7 " + reason : "") + " \u2014 click to show";
    const w = el.getAttribute && el.getAttribute("width");
    const h = el.getAttribute && el.getAttribute("height");
    if (w && /^\d+$/.test(w)) ph.style.minWidth = w + "px";
    if (h && /^\d+$/.test(h)) ph.style.minHeight = h + "px";
    const show = (e) => { e.preventDefault(); e.stopPropagation(); allowUrl(url); };
    ph.addEventListener("click", show);
    ph.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") show(e); });
    el.insertAdjacentElement("beforebegin", ph);
    return ph;
  }

  async function allowUrl(url) {
    lists.whitelist.add(url);
    verdicts.delete(url);
    reevaluate();
    try { await chrome.runtime.sendMessage({ type: "whitelistAdd", url }); } catch {}
  }

  // ---- Descriptors (one per surface) ---------------------------------------
  // <img>/<input>/<svg image> keep their src and are just hidden via CSS until
  // the verdict arrives (no remove/restore -> the browser fetches each at most
  // once). The image loads hidden; if blocked it is replaced and never shown.
  function makeImgDescriptor(el, url) {
    const d = {
      el, url, kind: "img",
      pending() { el.dataset[STATE] = PENDING; },
      reveal() {
        if (d._ph) { d._ph.remove(); d._ph = null; }
        el.dataset[STATE] = ALLOWED;
      },
      block(reason) {
        el.dataset[STATE] = BLOCKED;
        if (!d._ph) d._ph = makePlaceholder(el, url, reason);
      },
    };
    return d;
  }

  function makeInputDescriptor(el, url) {
    const d = {
      el, url, kind: "input",
      pending() { el.dataset[STATE] = PENDING; },
      reveal() {
        if (d._ph) { d._ph.remove(); d._ph = null; }
        el.dataset[STATE] = ALLOWED;
      },
      block(reason) {
        el.dataset[STATE] = BLOCKED;
        if (!d._ph) d._ph = makePlaceholder(el, url, reason);
      },
    };
    return d;
  }

  function makeSvgDescriptor(el, url) {
    return {
      el, url, kind: "svg",
      pending() { el.dataset[STATE] = PENDING; },
      reveal() { el.dataset[STATE] = ALLOWED; },
      block() { el.dataset[STATE] = BLOCKED; },
    };
  }

  function makePosterDescriptor(el, url) {
    const store = {};
    return {
      el, url, kind: "poster",
      pending() { mutate(el, () => { store.poster = el.getAttribute("poster"); if (store.poster !== null) el.removeAttribute("poster"); }); },
      reveal() { mutate(el, () => { if (store.poster != null) el.setAttribute("poster", store.poster); }); },
      block() { /* leave the poster removed */ },
    };
  }

  function makeBgDescriptor(el, url) {
    return {
      el, url, kind: "bg",
      pending() { mutate(el, () => el.classList.add("imgedge-bg-pending")); },
      reveal() { mutate(el, () => el.classList.remove("imgedge-bg-pending", "imgedge-bg-blocked")); },
      block() { mutate(el, () => { el.classList.remove("imgedge-bg-pending"); el.classList.add("imgedge-bg-blocked"); }); },
    };
  }

  // ---- Processing ----------------------------------------------------------
  async function run(d) {
    tracked.set(d.el, d);
    d.pending();
    await ready;
    const v = await getVerdict(d.url);
    applyVerdict(d, !!(v && v.allow), v && v.reason);
  }

  function imgUrl(el) {
    const u = el.currentSrc || el.src;
    if (u) return u;
    const ss = el.getAttribute("srcset");
    if (ss) { const f = ss.split(",")[0].trim().split(/\s+/)[0]; if (f) return abs(f); }
    return "";
  }

  // Skip decorative/tiny images (icons, tracking pixels): never arachnid photos,
  // and a large share of classifier load. Only skip when a small size is known;
  // unknown-size images are still classified.
  const MIN_DIM = 32; // both sides under this -> treat as an icon
  const TINY = 8;     // any side this small -> tracker / spacer pixel
  function tooSmall(el) {
    let w = parseInt((el.getAttribute && el.getAttribute("width")) || "", 10);
    let h = parseInt((el.getAttribute && el.getAttribute("height")) || "", 10);
    if (!(w > 0) || !(h > 0)) {
      let r = null;
      try { r = el.getBoundingClientRect(); } catch {}
      if (r) { if (!(w > 0)) w = r.width; if (!(h > 0)) h = r.height; }
    }
    if ((w > 0 && w <= TINY) || (h > 0 && h <= TINY)) return true;
    return w > 0 && h > 0 && w < MIN_DIM && h < MIN_DIM;
  }

  function processImg(el) {
    if (tracked.has(el)) return;
    const url = imgUrl(el);
    if (!usable(url)) { el.dataset[STATE] = ALLOWED; return; }
    if (tooSmall(el)) { el.dataset[STATE] = ALLOWED; return; }
    run(makeImgDescriptor(el, url));
  }

  function processInput(el) {
    if (tracked.has(el)) return;
    const url = el.src || abs(el.getAttribute("src") || "");
    if (!usable(url)) return;
    if (tooSmall(el)) return;
    run(makeInputDescriptor(el, url));
  }

  function processSvg(el) {
    if (tracked.has(el)) return;
    const url = abs(el.getAttribute("href") || el.getAttributeNS(XLINK, "href") || "");
    if (!usable(url)) return;
    run(makeSvgDescriptor(el, url));
  }

  function processPoster(el) {
    if (tracked.has(el)) return;
    const raw = el.getAttribute("poster");
    if (!raw) return;
    const url = abs(raw);
    if (!usable(url)) return;
    run(makePosterDescriptor(el, url));
  }

  function processBg(el) {
    if (tracked.has(el)) return;
    let cs;
    try { cs = getComputedStyle(el); } catch { return; }
    if (!cs || cs.display === "none" || cs.visibility === "hidden") return;
    const url = firstCssUrl(cs.backgroundImage) || firstCssUrl(cs.listStyleImage);
    if (!usable(url)) return;
    if (tooSmall(el)) return;
    run(makeBgDescriptor(el, url));
  }

  // ---- Background scan queue (idle-batched; getComputedStyle is costly) -----
  const ric = window.requestIdleCallback || ((cb) => setTimeout(() => cb({ timeRemaining: () => 8 }), 32));
  function queueBg(el) {
    if (!lists.scanBackgrounds || bgSeen.has(el) || tracked.has(el)) return;
    bgSeen.add(el);
    bgQueue.push(el);
    if (!bgScheduled) { bgScheduled = true; ric(drainBg); }
  }
  function drainBg(deadline) {
    let budget = 300;
    while (bgQueue.length && budget-- > 0 && (!deadline || deadline.timeRemaining() > 2)) {
      processBg(bgQueue.shift());
    }
    bgScheduled = false;
    if (bgQueue.length) { bgScheduled = true; ric(drainBg); }
  }

  // ---- Dispatch / scan -----------------------------------------------------
  function isSkippable(el) {
    if (!el || el.nodeType !== 1) return true;
    if (el.classList && el.classList.contains("imgedge-placeholder")) return true;
    const t = (el.tagName || "").toUpperCase();
    return t === "SCRIPT" || t === "STYLE" || t === "META" || t === "LINK" ||
           t === "HEAD" || t === "TITLE" || t === "NOSCRIPT" || t === "TEMPLATE";
  }

  function dispatch(el) {
    if (isSkippable(el)) return;
    const t = (el.tagName || "").toUpperCase();
    if (t === "IMG") processImg(el);
    else if (t === "INPUT" && el.type === "image") processInput(el);
    else if (t === "IMAGE" && el.namespaceURI === SVG_NS) processSvg(el);
    else if (t === "VIDEO" && el.getAttribute("poster")) processPoster(el);
    queueBg(el);
  }

  function scanTree(root) {
    if (!root) return;
    if (root.nodeType === 1) dispatch(root);
    if (root.querySelectorAll) {
      const all = root.querySelectorAll("*");
      for (let i = 0; i < all.length; i++) dispatch(all[i]);
    }
  }

  function reprocess(el) {
    const d = tracked.get(el);
    if (d) { if (d._ph) d._ph.remove(); tracked.delete(el); }
    delete el.dataset[STATE];
    if (el.classList) el.classList.remove("imgedge-bg-pending", "imgedge-bg-blocked");
    bgSeen.delete(el);
    dispatch(el);
  }

  // ---- Context-menu overrides ----------------------------------------------
  addEventListener("contextmenu", (e) => { lastContextEl = e.target; }, true);

  function descriptorFor(el) {
    let node = el;
    while (node && node.nodeType === 1) {
      if (tracked.has(node)) return tracked.get(node);
      node = node.parentElement;
    }
    return null;
  }

  function handleContext(action, srcUrl) {
    let url = srcUrl ? abs(srcUrl) : "";
    const d = descriptorFor(lastContextEl);
    if (!url && d) url = d.url;
    if (!url && lastContextEl && lastContextEl.tagName === "IMG") url = lastContextEl.currentSrc || lastContextEl.src;
    if (!usable(url)) return;

    if (action === "allow") {
      lists.whitelist.add(url);
      chrome.runtime.sendMessage({ type: "whitelistAdd", url }).catch(() => {});
    } else if (action === "block") {
      lists.blocklist.add(url);
      chrome.runtime.sendMessage({ type: "blocklistAdd", url }).catch(() => {});
    } else if (action === "allow-domain") {
      const h = hostOf(url);
      if (h) { lists.domains.add(h); chrome.runtime.sendMessage({ type: "domainAdd", host: h }).catch(() => {}); }
    }
    verdicts.delete(url);
    reevaluate();
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg && msg.type === "context") {
      handleContext(msg.action, msg.srcUrl);
      if (sendResponse) sendResponse({ ok: true });
    }
    return false;
  });

  // ---- Observe + kick off --------------------------------------------------
  // Only observe attributes that point at a NEW image to (re)classify. We do
  // NOT observe "style" or "class": pages mutate those constantly (animations,
  // frameworks, scroll effects), and re-scanning on every change pegs the CPU
  // and can hang the tab. Background images are still filtered on first sight.
  const observer = new MutationObserver((mutations) => {
    for (const m of mutations) {
      if (m.type === "childList") {
        for (const n of m.addedNodes) if (n.nodeType === 1) scanTree(n);
      } else if (m.type === "attributes") {
        if (m.target.nodeType === 1 && !selfMut.has(m.target)) reprocess(m.target);
      }
    }
  });
  observer.observe(document.documentElement || document, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["src", "srcset", "href", "xlink:href", "poster"],
  });

  scanTree(document.documentElement);
  document.addEventListener("DOMContentLoaded", () =>
    scanTree(document.body || document.documentElement)
  );
})();
