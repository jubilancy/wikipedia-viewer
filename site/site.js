/* Progressive enhancement and the category page.
   Home, tags and articles are plain HTML and work without this file. This file adds:
   - type-to-filter on /tags and /categories
   - search, sort and filters on the home list (reads search.json)
   - the /category?name=<slug> page (reads categories.json + search.json), so no per-category files are needed. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const root = document.body.dataset.root || "./";
  const fmtDate = (s) => { const d = new Date(s); return isNaN(d) ? s : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }); };
  const fmtViews = (n) => (n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e4 ? (n / 1e3).toFixed(1) + "K" : n.toLocaleString("en"));
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const getJSON = (name) => fetch(root + name).then((r) => { if (!r.ok) throw new Error(name); return r.json(); });

  // One list item, same markup as the generated HTML.
  function itemEl(r) {
    const li = el("li", "item"), thumb = el("div", "thumb"), body = el("div", "item-body");
    thumb.setAttribute("aria-hidden", "true");
    if (r.i) { const img = el("img"); img.src = r.i; img.width = 112; img.height = 84; img.loading = "lazy"; img.decoding = "async"; img.alt = ""; thumb.append(img); }
    else thumb.textContent = (r.t[0] || "?").toUpperCase();
    const h2 = el("h2"), a = el("a", null, r.t);
    h2.lang = r.l; a.href = root + r.u; h2.append(a);
    if (r.st !== "ok") h2.append(el("span", "badge", r.st === "missing" ? "not found" : r.st));
    if (r.dis) h2.append(el("span", "badge", "disambiguation"));
    body.append(h2);
    if (r.d) body.append(el("p", "desc", r.d));
    const bits = [r.l, r.a ? "Added " + fmtDate(r.a) : "", r.v != null ? fmtViews(r.v) + " views in 30 days" : ""].filter(Boolean);
    body.append(el("p", "meta", bits.join("  ·  ")));
    if (r.g.length) {
      const tags = el("div", "tags");
      r.g.slice(0, 5).forEach((t, i) => { const l = el("a", null, "#" + t); l.href = root + "tag/" + r.gs[i]; tags.append(l); });
      body.append(tags);
    }
    li.append(thumb, body); return li;
  }

  // Render `hits` into #results 50 at a time with a "Show more" button.
  function renderList(hits) {
    const results = $("results"), wrap = $("more-wrap");
    let shown = 0;
    const more = () => {
      const ul = results.querySelector("ul") || results.appendChild(el("ul", "items"));
      hits.slice(shown, shown + 50).forEach((r) => ul.append(itemEl(r))); shown = Math.min(hits.length, shown + 50);
      wrap.replaceChildren();
      if (shown < hits.length) { const b = el("button", "btn", `Show more (${hits.length - shown} left)`); b.type = "button"; b.addEventListener("click", more); wrap.append(b); }
    };
    results.replaceChildren(); wrap.replaceChildren();
    if (!hits.length) results.append(el("p", "empty", "No bookmarks match. Try clearing a filter.")); else more();
  }

  // ----- /tags and /categories: type-to-filter
  const filter = $("filter");
  if (filter && $("index")) {
    const lis = [...$("index").children];
    filter.addEventListener("input", () => {
      const t = filter.value.trim().toLowerCase();
      let shown = 0;
      lis.forEach((li) => { const hit = !t || li.textContent.toLowerCase().includes(t); li.hidden = !hit; if (hit) shown++; });
      $("filter-status").textContent = t ? `Showing ${shown} of ${lis.length}` : "";
    });
  }

  // ----- /category?name=<slug>
  if ($("cat-app")) {
    const slug = new URLSearchParams(location.search).get("name") || "";
    Promise.all([getJSON("categories.json"), getJSON("search.json")]).then(([cats, all]) => {
      const c = cats[slug];
      if (!c) {
        $("cat-title").textContent = "Category not found";
        $("cat-crumb").textContent = "not found";
        $("results").append(el("p", "empty", "There is no category with that name. Browse all categories instead."));
        return;
      }
      document.title = `${c.n}: category, Wikipedia Cabinet`;
      $("cat-title").textContent = c.n; $("cat-crumb").textContent = c.n;
      $("cat-count").textContent = `${c.a.length} article${c.a.length === 1 ? "" : "s"}`;
      renderList(c.a.map((i) => all[i]));
    }).catch(() => { $("cat-title").textContent = "Could not load this category"; });
  }

  // ----- home list: search, sort, list and language filters
  const q = $("q");
  if (!q) return;
  const results = $("results"), pager = $("pager"), status = $("status"), wrap = $("more-wrap");
  const original = results.innerHTML;
  document.querySelectorAll(".js-only").forEach((n) => (n.hidden = false));
  let data = null, timer;
  const sorters = {
    added: (a, b) => (b.a || "").localeCompare(a.a || "") || a.t.localeCompare(b.t),
    title: (a, b) => a.t.localeCompare(b.t, undefined, { sensitivity: "base" }),
    views: (a, b) => (b.v ?? -1) - (a.v ?? -1) || a.t.localeCompare(b.t),
    edited: (a, b) => (b.e || "").localeCompare(a.e || "") || a.t.localeCompare(b.t),
    length: (a, b) => (b.n ?? -1) - (a.n ?? -1) || a.t.localeCompare(b.t),
  };

  function run() {
    const terms = q.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const list = $("list").value, lang = $("lang").value, sort = $("sort").value;
    if (!terms.length && !list && !lang && sort === "added") {
      results.innerHTML = original; wrap.replaceChildren(); if (pager) pager.hidden = false; status.textContent = ""; return;
    }
    if (!data) { status.textContent = "Loading…"; getJSON("search.json").then((d) => { data = d; run(); })
      .catch(() => { status.textContent = "Search is unavailable right now."; }); return; }
    const hits = data.filter((r) => terms.every((t) => r.h.includes(t)) && (!list || r.s.includes(list)) && (!lang || r.l === lang)).sort(sorters[sort]);
    if (pager) pager.hidden = true;
    status.textContent = `${hits.length} of ${data.length} bookmarks`;
    renderList(hits);
  }
  const soon = () => { clearTimeout(timer); timer = setTimeout(run, 150); };
  q.addEventListener("input", soon);
  ["sort", "list", "lang"].forEach((id) => $(id).addEventListener("change", run));
})();
