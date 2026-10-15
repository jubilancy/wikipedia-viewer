/* Wikipedia Cabinet: loads data/articles.csv, renders index cards, opens a flippable detail card. No build step. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const GAP = 22, MIN_COL = 250, BATCH = 48;
  const state = { rows: [], filtered: [], shown: 0, cols: [], colW: 0, base: "data/", side: new Map(), openKey: null };
  const fmt = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });
  const fmtFull = new Intl.NumberFormat("en");
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* storage unavailable */ } },
  };

  // ---------- CSV ----------
  function parseCSV(text) {
    const out = []; let row = [], f = "", q = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (q) {
        if (c === '"') { if (text[i + 1] === '"') { f += '"'; i++; } else q = false; } else f += c;
      } else if (c === '"') q = true;
      else if (c === ",") { row.push(f); f = ""; }
      else if (c === "\n") { row.push(f); out.push(row); row = []; f = ""; }
      else if (c !== "\r") f += c;
    }
    if (f || row.length) { row.push(f); out.push(row); }
    const head = out.shift() || [];
    return out.filter((r) => r.length > 1).map((r) => Object.fromEntries(head.map((h, i) => [h, r[i] ?? ""])));
  }

  // ---------- helpers ----------
  const split = (s) => (s ? s.split("|").filter(Boolean) : []);
  const num = (s) => (s === "" || s == null ? NaN : Number(s));
  function el(tag, props = {}, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v; else if (k === "text") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v); else n.setAttribute(k, v === true ? "" : v);
    }
    for (const k of kids.flat()) if (k != null && k !== false && k !== 0) n.append(k.nodeType ? k : document.createTextNode(k));
    return n;
  }
  function hash(s) { let h = 2166136261; for (const c of s) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; }
  const safeUrl = (u) => (/^https?:\/\//i.test(u) ? u : "");
  const wikiUrl = (lang, title) => `https://${lang}.wikipedia.org/wiki/${encodeURIComponent(title.replace(/ /g, "_"))}`;

  // ---------- prepare rows ----------
  function prepare(r) {
    r.tagList = split(r.tags); r.catList = split(r.categories); r.listList = split(r.lists);
    r.views = num(r.pageviews_total); r.len = num(r.length); r.ok = r.status === "ok";
    r.w = num(r.thumb_width); r.h = num(r.thumb_height);
    r.hasImg = !!r.thumb_url && r.w > 0 && r.h > 0;
    r.hay = [r.title, r.bookmark_title, r.requested_titles.replace(/\|/g, " "), r.short_description, r.summary,
      r.tags.replace(/\|/g, " "), r.notes, r.categories.replace(/\|/g, " "), r.lists.replace(/\|/g, " ")].join("\n").toLowerCase();
    r.rnd = hash(r.key);
    return r;
  }

  // ---------- filters ----------
  function filters() {
    return {
      q: $("q").value.trim().toLowerCase().split(/\s+/).filter(Boolean), list: $("list").value, lang: $("lang").value,
      cat: $("cat").value.trim().toLowerCase(), sort: $("sort").value, img: $("img").checked,
      tags: [...document.querySelectorAll("#tags .chip[aria-pressed=true]")].map((b) => b.dataset.tag),
    };
  }
  const sorters = {
    added: (a, b) => (b.added || "").localeCompare(a.added || "") || a.title.localeCompare(b.title),
    title: (a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: "base" }),
    views: (a, b) => (isNaN(b.views) ? -1 : b.views) - (isNaN(a.views) ? -1 : a.views) || a.title.localeCompare(b.title),
    edited: (a, b) => (b.last_edited || "").localeCompare(a.last_edited || "") || a.title.localeCompare(b.title),
    length: (a, b) => (isNaN(b.len) ? -1 : b.len) - (isNaN(a.len) ? -1 : a.len) || a.title.localeCompare(b.title),
    shuffle: (a, b) => a.rnd - b.rnd,
  };
  function apply(pushUrl = true) {
    const f = filters();
    state.filtered = state.rows.filter((r) =>
      f.q.every((t) => r.hay.includes(t)) && (!f.list || r.listList.includes(f.list)) && (!f.lang || r.lang === f.lang) &&
      (!f.cat || r.catList.some((c) => c.toLowerCase().includes(f.cat))) && (!f.img || r.hasImg) &&
      f.tags.every((t) => r.tagList.includes(t))).sort(sorters[f.sort]);
    if (pushUrl) {
      const p = new URLSearchParams();
      if ($("q").value) p.set("q", $("q").value); if (f.list) p.set("list", f.list); if (f.lang) p.set("lang", f.lang);
      if ($("cat").value) p.set("cat", $("cat").value); if (f.sort !== "added") p.set("sort", f.sort);
      if (f.img) p.set("img", "1"); if (f.tags.length) p.set("tags", f.tags.join("|"));
      history.replaceState(null, "", (p.toString() ? "?" + p : location.pathname) + location.hash);
    }
    $("grid").replaceChildren(); state.shown = 0; state.cols = [];
    $("empty").hidden = state.filtered.length > 0;
    $("status").textContent = `Showing ${fmtFull.format(state.filtered.length)} of ${fmtFull.format(state.rows.length)} bookmarks`;
    renderMore();
  }

  // ---------- cards + masonry ----------
  function cardEl(r, idx) {
    const tilt = ((r.rnd % 31) - 15) / 10; // -1.5 .. 1.5 deg
    let tile;
    if (r.hasImg) {
      const ratio = Math.min(1.6, Math.max(0.72, r.w / r.h));
      tile = el("div", { class: "tile", style: `aspect-ratio:${ratio}` }, el("img", {
        src: r.thumb_url, width: r.w, height: r.h, loading: "lazy", decoding: "async",
        alt: r.short_description ? `${r.title}: ${r.short_description}` : r.title,
      }));
    } else {
      tile = el("div", { class: "tile noimg", style: "aspect-ratio:1.9", "aria-hidden": "true" }, el("span", { text: r.title.charAt(0).toUpperCase() }));
    }
    const card = el("article", { class: `card${r.rnd % 3 === 0 ? " tape" : ""}${r.ok ? "" : " missing"}`, style: `--tilt:${tilt}deg`, "data-key": r.key },
      tile,
      el("div", { class: "card-body" },
        el("h2", {}, el("button", { type: "button", "aria-haspopup": "dialog", onclick: () => openCard(r.key), text: r.title })),
        r.short_description && el("p", { class: "desc", text: r.short_description }),
        r.notes && el("p", { class: "note", text: r.notes.split(" || ")[0] }),
        r.tagList.length && el("div", { class: "tags" }, r.tagList.slice(0, 5).map((t) =>
          el("button", { type: "button", class: "chip", text: t, "aria-label": `Filter by tag ${t}`, onclick: () => toggleTag(t, true) }))),
        el("div", { class: "meta" },
          el("span", { text: r.lang }),
          !r.ok && el("span", { class: "badge", text: r.status === "missing" ? "not found" : r.status }),
          r.is_disambiguation === "true" && el("span", { class: "badge", text: "disambiguation" }),
          !isNaN(r.views) && el("span", { text: `${fmt.format(r.views)} views/30d` }),
          r.listList.length && el("span", { text: r.listList.join(", ") }))));
    return card;
  }
  function layout(from = 0) {
    const grid = $("grid"), W = grid.clientWidth - 32 + 0;
    const n = Math.max(1, Math.floor((W + GAP) / (MIN_COL + GAP)));
    const cw = (W + GAP) / n - GAP;
    const cards = [...grid.children];
    if (state.cols.length !== n || Math.abs(state.colW - cw) > 0.5) { from = 0; state.cols = new Array(n).fill(0); state.colW = cw; }
    else if (from === 0) state.cols = new Array(n).fill(0);
    const todo = cards.slice(from);
    todo.forEach((c) => (c.style.width = cw + "px"));
    const heights = todo.map((c) => c.offsetHeight); // batched read
    todo.forEach((c, i) => {
      let col = 0; for (let k = 1; k < n; k++) if (state.cols[k] < state.cols[col]) col = k;
      c.style.translate = `${16 + col * (cw + GAP)}px ${state.cols[col]}px`;
      state.cols[col] += heights[i] + GAP;
    });
    grid.style.height = Math.max(0, ...state.cols) + "px";
  }
  function renderMore() {
    const next = state.filtered.slice(state.shown, state.shown + BATCH);
    if (!next.length) return;
    const from = state.shown;
    $("grid").append(...next.map(cardEl));
    state.shown += next.length;
    layout(from);
  }

  // ---------- tag + control setup ----------
  function toggleTag(t, on) {
    const b = [...document.querySelectorAll("#tags .chip")].find((x) => x.dataset.tag === t);
    if (b) { b.setAttribute("aria-pressed", String(on ?? b.getAttribute("aria-pressed") !== "true")); apply(); }
  }
  function buildControls() {
    const count = (get) => { const m = new Map(); state.rows.forEach((r) => get(r).forEach((v) => m.set(v, (m.get(v) || 0) + 1))); return m; };
    const opts = (sel, label, m) => { sel.replaceChildren(el("option", { value: "", text: label }),
      ...[...m].sort((a, b) => a[0].localeCompare(b[0])).map(([k, n]) => el("option", { value: k, text: `${k} (${n})` }))); };
    opts($("list"), "All lists", count((r) => r.listList));
    opts($("lang"), "All languages", count((r) => [r.lang]));
    const cats = [...count((r) => r.catList)].sort((a, b) => b[1] - a[1]).slice(0, 600);
    $("catlist").replaceChildren(...cats.map(([c]) => el("option", { value: c })));
    const tags = [...count((r) => r.tagList)].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    const mk = (t, n) => el("button", { type: "button", class: "chip", "data-tag": t, "aria-pressed": "false", text: `${t} ${n}`, onclick: (e) => toggleTag(t, e.currentTarget.getAttribute("aria-pressed") !== "true") });
    const row = $("tags"); const first = tags.slice(0, 30);
    row.replaceChildren(...first.map(([t, n]) => mk(t, n)));
    if (tags.length > 30) {
      const more = el("button", { type: "button", class: "chip", text: `all ${tags.length} tags`, "aria-expanded": "false" });
      more.addEventListener("click", () => { more.replaceWith(...tags.slice(30).map(([t, n]) => mk(t, n))); });
      row.append(more);
    }
    const p = new URLSearchParams(location.search);
    $("q").value = p.get("q") || ""; $("list").value = p.get("list") || ""; $("lang").value = p.get("lang") || "";
    $("cat").value = p.get("cat") || ""; $("sort").value = p.get("sort") || "added"; $("img").checked = p.get("img") === "1";
    (p.get("tags") || "").split("|").filter(Boolean).forEach((t) => {
      let b = [...row.querySelectorAll(".chip")].find((x) => x.dataset.tag === t);
      if (!b) { b = mk(t, "•"); row.append(b); }
      b.setAttribute("aria-pressed", "true");
    });
    let timer;
    $("q").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => apply(), 150); });
    ["list", "lang", "sort", "img"].forEach((id) => $(id).addEventListener("change", () => apply()));
    $("cat").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => apply(), 200); });
    $("moreFilters").open = window.matchMedia("(min-width: 700px)").matches || !!(p.get("list") || p.get("lang") || p.get("cat") || p.get("img"));
  }

  // ---------- detail dialog ----------
  const dlg = $("dlg");
  const idx = (k) => state.filtered.findIndex((r) => r.key === k);
  function openCard(key, fromHash = false) {
    const r = state.rows.find((x) => x.key === key); if (!r) return;
    state.openKey = key; setFlip(false);
    $("front").replaceChildren(...frontFace(r)); $("back").replaceChildren(el("p", { text: "Turn the card over to load details." }));
    $("back").dataset.loaded = "";
    if (!dlg.open) dlg.showModal();
    $("front").scrollTop = 0;
    if (!fromHash) history.replaceState(null, "", location.search + "#" + encodeURI(key));
    const i = idx(key); $("prev").disabled = i <= 0; $("next").disabled = i < 0 || i >= state.filtered.length - 1;
  }
  function frontFace(r) {
    const out = [];
    const pageUrl = r.url;
    out.push(el("h2", { id: "dlgTitle", text: r.title }));
    if (r.short_description) out.push(el("p", { class: "desc", text: r.short_description }));
    const fig = r.image_url && r.w ? el("figure", {},
      el("img", { src: r.thumb_url, width: r.w, height: r.h, alt: r.short_description ? `${r.title}: ${r.short_description}` : r.title }),
      el("figcaption", {}, "Image: ", r.image_author || "unknown author", " · ",
        r.image_license_url ? el("a", { href: safeUrl(r.image_license_url), text: r.image_license || "licence" }) : (r.image_license || "licence not recorded"),
        r.image_page_url && [" · ", el("a", { href: safeUrl(r.image_page_url), text: "file page" })])) : null;
    const text = el("div", {},
      r.ok ? el("p", { class: "summary", text: r.summary || "No summary available." }) : el("p", { class: "summary", text: `This page was not available (${r.status}). Check the report.csv for the reason.` }),
      r.notes && el("p", { class: "note", text: r.notes.split(" || ").join("  /  ") }),
      r.tagList.length && el("div", { class: "tags" }, r.tagList.map((t) => el("button", { type: "button", class: "chip", text: t, onclick: () => { dlg.close(); toggleTag(t, true); } }))),
      el("p", {}, el("a", { href: safeUrl(pageUrl), text: `Read “${r.title}” on Wikipedia` }), " · ", el("a", { href: safeUrl(pageUrl) + "?action=history", text: "history & authors" }),
        " · text under ", el("a", { href: "https://creativecommons.org/licenses/by-sa/4.0/", text: "CC BY-SA 4.0" })));
    out.push(el("div", { class: `lead${fig ? " has-img" : ""}` }, fig, text));
    out.push(el("h3", { text: "At a glance" }), el("dl", { class: "kv" }, ...kv([
      ["Language", r.lang], ["Lists", r.listList.join(", ")], ["Added", r.added], ["Last edited", (r.last_edited || "").slice(0, 10)],
      ["Length", r.len ? `${fmtFull.format(r.len)} bytes` : ""], ["30-day views", isNaN(r.views) ? "" : fmtFull.format(r.views)],
      ["Protection", (r.protection || "").split("|").filter(Boolean).join(", ")],
      ["Also asked as", split(r.requested_titles).filter((t) => t !== r.title).join(", ")]])));
    return out;
  }
  const kv = (pairs) => pairs.filter(([, v]) => v).flatMap(([k, v]) => [el("dt", { text: k }), el("dd", { text: v })]);

  async function backFace(r) {
    const body = $("back");
    if (body.dataset.loaded === r.key) return;
    body.dataset.loaded = r.key; body.setAttribute("aria-busy", "true");
    body.replaceChildren(el("p", { text: "Loading details…" }));
    let s = state.side.get(r.key);
    if (!s && r.sidecar) {
      try {
        const url = state.base + r.sidecar.split("/").map(encodeURIComponent).join("/");
        const res = await fetch(url); if (!res.ok) throw new Error(res.status);
        s = await res.json(); state.side.set(r.key, s);
      } catch (e) { body.replaceChildren(el("p", { text: "Could not load the details file for this card." })); body.removeAttribute("aria-busy"); return; }
    }
    if (state.openKey !== r.key) return;
    body.replaceChildren(...(s ? backContent(r, s) : [el("p", { text: "No extra details were saved for this card." })]));
    body.removeAttribute("aria-busy");
  }
  function sparkline(pv) {
    const v = pv.series.map((x) => x[1]), max = Math.max(1, ...v), n = v.length;
    const pts = v.map((y, i) => [n === 1 ? 150 : (i / (n - 1)) * 300, 58 - (y / max) * 52]);
    const d = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("");
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg"); svg.setAttribute("viewBox", "0 0 300 60"); svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("class", "spark"); svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `Daily page views over ${n} days to ${pv.through}: low ${fmtFull.format(Math.min(...v))}, high ${fmtFull.format(max)}, total ${fmtFull.format(v.reduce((a, b) => a + b, 0))}.`);
    const area = document.createElementNS(ns, "path"); area.setAttribute("class", "area"); area.setAttribute("d", `${d}L300,60L0,60Z`);
    const line = document.createElementNS(ns, "path"); line.setAttribute("d", d);
    svg.append(area, line); return svg;
  }
  function backContent(r, s) {
    const out = [el("h2", { text: r.title }), el("p", { class: "desc", text: "Back of the card: the details behind the bookmark." })];
    if (s.pageviews) out.push(el("h3", { text: `Page views, last ${s.pageviews.series.length} days` }), sparkline(s.pageviews),
      el("p", { class: "meta", text: `Total ${fmtFull.format(s.pageviews.series.reduce((a, b) => a + b[1], 0))} · through ${s.pageviews.through} · all platforms, human users` }));
    const wd = s.wikidata || {};
    if (wd.id) {
      out.push(el("h3", { text: "Wikidata" }), el("p", {}, el("a", { href: `https://www.wikidata.org/wiki/${encodeURIComponent(wd.id)}`, text: wd.id }),
        wd.description ? ` · ${wd.description}` : "", wd.sitelink_count ? ` · ${wd.sitelink_count} sitelinks` : ""));
      if ((wd.facts || []).length) out.push(el("dl", { class: "kv" }, ...wd.facts.filter((f) => f.property !== "P18").flatMap((f) => [el("dt", { text: f.label }), el("dd", { text: f.values.join("; ") })])));
    }
    out.push(el("h3", { text: "Counts" }), el("dl", { class: "kv" }, ...kv([
      ["Backlinks (articles)", s.backlinks ? `${fmtFull.format(s.backlinks.count)}${s.backlinks.capped ? "+ (capped)" : ""}` : ""],
      ["Outgoing links", fmtFull.format((s.links || []).length)], ["External links", fmtFull.format((s.external_links || []).length)],
      ["Templates", fmtFull.format((s.templates || []).length)], ["Redirects to it", (s.aliases || []).length ? (s.aliases.length > 8 ? s.aliases.slice(0, 8).join(", ") + ` … (+${s.aliases.length - 8})` : s.aliases.join(", ")) : ""],
      ["Coordinates", (s.coordinates || [])[0] ? `${s.coordinates[0].lat}, ${s.coordinates[0].lon}` : ""]])));
    const c0 = (s.coordinates || [])[0];
    if (c0) out.push(el("p", {}, el("a", { href: `https://www.openstreetmap.org/?mlat=${c0.lat}&mlon=${c0.lon}#map=10/${c0.lat}/${c0.lon}`, text: "Open on a map" })));
    if ((s.sections || []).length) out.push(el("h3", { text: "Contents" }), el("ol", { class: "toc", "aria-label": "Table of contents" },
      ...s.sections.map((x) => el("li", { "data-l": x.level }, el("a", { href: `${safeUrl(s.page_url)}#${encodeURIComponent(x.anchor)}`, text: `${x.number} ${x.line}` })))));
    if ((s.categories || []).length) out.push(el("h3", { text: "Categories" }), el("div", { class: "cats" }, s.categories.slice(0, 40).map((c) => el("span", { text: c }))));
    if ((s.media || []).length) out.push(el("h3", { text: `Media (${s.media.length})` }), el("ul", { class: "gallery" },
      ...s.media.filter((m) => m.thumb).slice(0, 18).map((m) => el("li", {}, el("img", { src: safeUrl(m.thumb), alt: m.caption || m.title.replace(/^File:/, "").replace(/_/g, " "), loading: "lazy" }),
        el("a", { href: wikiUrl(r.lang, m.title), text: m.caption ? m.caption.slice(0, 60) : "file page" })))));
    if ((s.language_links || []).length) out.push(el("h3", { text: `Other languages (${s.language_links.length})` }), el("div", { class: "langs" },
      ...s.language_links.slice(0, 60).map((l) => el("a", { href: wikiUrl(l.lang, l.title), lang: l.lang, text: l.lang, title: l.title }))));
    if (s.lead_image && s.lead_image.file) out.push(el("h3", { text: "Lead image credit" }), el("p", { text: `${s.lead_image.author || "Unknown author"} · ${s.lead_image.license || "licence not recorded"}${s.lead_image.attribution ? " · " + s.lead_image.attribution : ""}` }));
    return out;
  }
  function setFlip(on) {
    $("flipper").classList.toggle("turned", on); $("flip").setAttribute("aria-pressed", String(on));
    $("flip").textContent = on ? "Turn card back" : "Turn card over";
    on ? ($("front").setAttribute("inert", ""), $("back").removeAttribute("inert")) : ($("back").setAttribute("inert", ""), $("front").removeAttribute("inert"));
    if (on) { const r = state.rows.find((x) => x.key === state.openKey); if (r) backFace(r); }
  }
  function step(d) { const i = idx(state.openKey) + d; if (state.filtered[i]) openCard(state.filtered[i].key); }
  $("flip").addEventListener("click", () => setFlip($("flip").getAttribute("aria-pressed") !== "true"));
  $("prev").addEventListener("click", () => step(-1)); $("next").addEventListener("click", () => step(1));
  $("close").addEventListener("click", () => dlg.close());
  dlg.addEventListener("close", () => { state.openKey = null; history.replaceState(null, "", location.pathname + location.search); });
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
  dlg.addEventListener("keydown", (e) => {
    if (e.target.matches("input,select,textarea")) return;
    if (e.key === "ArrowLeft") { step(-1); e.preventDefault(); } else if (e.key === "ArrowRight") { step(1); e.preventDefault(); }
    else if (e.key.toLowerCase() === "f") { setFlip($("flip").getAttribute("aria-pressed") !== "true"); e.preventDefault(); }
  });
  window.addEventListener("hashchange", () => { const k = decodeURI(location.hash.slice(1)); if (k && k !== state.openKey) openCard(k, true); });

  // ---------- theme ----------
  function setTheme(t) {
    if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
    const dark = t === "dark" || (!t && matchMedia("(prefers-color-scheme: dark)").matches);
    $("theme").textContent = dark ? "Light mode" : "Dark mode";
  }
  $("theme").addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark"; store.set("theme", next); setTheme(next);
  });
  setTheme(store.get("theme"));

  // ---------- boot ----------
  async function load() {
    for (const base of ["data/", "../data/"]) {
      try { const r = await fetch(base + "articles.csv"); if (r.ok) { state.base = base; return parseCSV(await r.text()); } } catch { /* try next */ }
    }
    throw new Error("articles.csv not found");
  }
  load().then((rows) => {
    state.rows = rows.map(prepare);
    const ok = state.rows.filter((r) => r.ok).length;
    $("sub").textContent = `${fmtFull.format(state.rows.length)} pinned articles in ${new Set(state.rows.map((r) => r.lang)).size} language${new Set(state.rows.map((r) => r.lang)).size === 1 ? "" : "s"}${ok < state.rows.length ? ` (${state.rows.length - ok} not available)` : ""}`;
    buildControls(); apply(false);
    new IntersectionObserver((e) => { if (e[0].isIntersecting && state.shown < state.filtered.length) renderMore(); }, { rootMargin: "800px" }).observe($("sentinel"));
    let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => layout(0), 120); });
    if (location.hash.length > 1) openCard(decodeURI(location.hash.slice(1)), true);
  }).catch((e) => { $("sub").textContent = "Could not load data/articles.csv. Run the script first, or serve the site from the repo root."; console.error(e); });
})();
