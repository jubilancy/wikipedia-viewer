#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Build the static Wikipedia Cabinet site from data/ (the output of wiki_bookmarks.py).

Writes plain HTML pages that GitHub Pages serves without file extensions:

    /                      bookmark list (paginated: /page/2, /page/3, ...)
    /tags                  every tag            /tag/<slug>       articles with that tag
    /categories            every category      /category?name=<slug>  one category (drawn in the browser)
    /article/<lang>/<slug> one article, with data from its sidecar JSON
    /search.json           index used by the search box on the home page
    /categories.json       category -> article indexes into search.json (used by /category)

    uv run build_site.py                         # data/ + site/  ->  _site/
    uv run build_site.py --out _site --base-path /wikipedia-viewer/
    uv run build_site.py --serve 8000                # build, then preview like GitHub Pages
"""
import argparse, csv, hashlib, html, json, re, shutil, sys, unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import quote

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--data", default="data", help="folder with articles.csv and articles/*.json")
ap.add_argument("--site", default="site", help="folder with static assets (style.css, site.js, favicon.svg)")
ap.add_argument("--out", default="_site", help="output folder (deleted first)")
ap.add_argument("--base-path", default="/", help="URL path the site is served under (used only by 404.html)")
ap.add_argument("--page-size", type=int, default=50, help="bookmarks per page on the home list")
ap.add_argument("--serve", type=int, metavar="PORT", help="after building, serve the site on this port (preview only)")
args = ap.parse_args()

esc = lambda s: html.escape(str(s), quote=True)
out = Path(args.out)

# ---------------------------------------------------------------- helpers

def slugify(s, prefix="x"):
    t = s.replace("ß", "ss").replace("Æ", "AE").replace("æ", "ae").replace("Ø", "O").replace("ø", "o")
    t = t.replace("Đ", "D").replace("đ", "d").replace("Ł", "L").replace("ł", "l")
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t or f"{prefix}-{hashlib.sha1(s.encode()).hexdigest()[:8]}"


def unique_slugs(names, prefix):
    """Map each name to a unique ASCII slug; collisions get -2, -3 ... in sorted order."""
    seen, result = {}, {}
    for n in sorted(names):
        base = slugify(n, prefix)
        slug, i = base, 2
        while slug in seen:
            slug, i = f"{base}-{i}", i + 1
        seen[slug] = n
        result[n] = slug
    return result


def fmt_date(s):
    try:
        return date.fromisoformat(s[:10]).strftime("%-d %b %Y")
    except (ValueError, TypeError):
        return s or ""


def fmt_views(v):
    try:
        n = int(v)
    except (ValueError, TypeError):
        return ""
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.1f}K" if n >= 1e4 else f"{n:,}"


def split(s):
    return [x for x in (s or "").split("|") if x]


def write(rel, text):
    p = out / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------- load

data = Path(args.data)
with open(data / "articles.csv", newline="", encoding="utf-8") as fh:
    rows = list(csv.DictReader(fh))
rows.sort(key=lambda r: r["title"].lower())               # then newest first; ties stay A to Z
rows.sort(key=lambda r: r["added"] or "", reverse=True)

# Start from an empty output folder so pages from an earlier build never linger.
_keep = [Path.cwd().resolve(), data.resolve(), Path(args.site).resolve()]
if any(out.resolve() == k or out.resolve() in k.parents for k in _keep):
    sys.exit(f"Refusing to delete {out}: it is (or contains) the working, data or site folder. Use a separate --out.")
shutil.rmtree(out, ignore_errors=True)

by_lang = defaultdict(list)
for r in rows:
    by_lang[r["lang"]].append(r)
for lang, rs in by_lang.items():
    m = unique_slugs([r["title"] for r in rs], "article")
    for r in rs:
        r["slug"] = m[r["title"]]
        r["href"] = f"article/{lang}/{r['slug']}"
    for r in rs:
        r["tagl"], r["catl"], r["listl"] = split(r["tags"]), split(r["categories"]), split(r["lists"])

tag_names = {t for r in rows for t in r["tagl"]}
cat_counts = defaultdict(int)
for r in rows:
    for c in r["catl"]:
        cat_counts[c] += 1
cat_names = {c for c, n in cat_counts.items()}
tag_slug = unique_slugs(tag_names, "tag")
cat_slug = unique_slugs(cat_names, "category")
tag_items, cat_items = defaultdict(list), defaultdict(list)
for r in rows:
    for t in r["tagl"]:
        tag_items[t].append(r)
    for c in r["catl"]:
        cat_items[c].append(r)

# ---------------------------------------------------------------- page chrome

# Runs before first paint: restore a saved theme and mark JavaScript as available, so nothing reflows or flashes later.
HEAD_SCRIPT = ('<script>try{var t=localStorage.getItem("theme");if(t==="dark"||t==="light")'
               'document.documentElement.setAttribute("data-theme",t)}catch(e){}'
               'document.documentElement.classList.add("js")</script>')
THEME_BTN = ('<button type="button" id="theme" class="theme-toggle" aria-label="Switch between light and dark mode">'
             '<span class="to-dark">Dark mode</span><span class="to-light">Light mode</span></button>')


def page(title, body, depth, active="", desc="", scripts="", wide=False, extra_head=""):
    p = "../" * depth
    cur = ' aria-current="page"'
    nav = "".join(
        f'<a href="{href}"{cur if key == active else ""}>{label}</a>'
        for key, href, label in (("home", p or "./", "Bookmarks"), ("tags", p + "tags", "Tags"),
                                 ("categories", p + "categories", "Categories")))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc or 'A personal cabinet of Wikipedia bookmarks.')}">
<link rel="icon" href="{p}favicon.svg" type="image/svg+xml">
{HEAD_SCRIPT}
<link rel="preload" href="{p}fonts/newsreader-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="{p}fonts/instrument-sans-latin.woff2" as="font" type="font/woff2" crossorigin>
{extra_head}
<link rel="stylesheet" href="{p}style.css">
</head>
<body data-root="{p or './'}">
<a class="skip" href="#main">Skip to content</a>
<div class="wrap{' wide' if wide else ''}">
<header class="top"><a class="brand" href="{p or './'}">Wikipedia Cabinet</a>
<div class="top-right"><nav aria-label="Main">{nav}</nav>{THEME_BTN}</div></header>
<main id="main">
{body}
</main>
<footer class="foot"><p>Article text and summaries come from <a href="https://www.wikipedia.org/">Wikipedia</a> and are available under
<a href="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0</a>. Each article page links to its Wikipedia source and edit history,
which list the authors. Images come from Wikimedia Commons or Wikipedia under the licence shown beside each one.
Fonts: Newsreader and Instrument Sans, under the <a href="{p}fonts/OFL-Newsreader.txt">SIL Open Font License</a>
(<a href="{p}fonts/OFL-InstrumentSans.txt">Instrument Sans licence</a>).</p></footer>
</div>
{scripts}
</body>
</html>
"""


def item(r, p):
    if r["thumb_url"] and r["thumb_width"]:
        thumb = f'<img src="{esc(r["thumb_url"])}" width="112" height="84" loading="lazy" decoding="async" alt="">'
    else:
        thumb = esc((r["title"] or "?")[0].upper())
    badges = ""
    if r["status"] != "ok":
        badges += f'<span class="badge">{"not found" if r["status"] == "missing" else esc(r["status"])}</span>'
    if r["is_disambiguation"] == "true":
        badges += '<span class="badge">disambiguation</span>'
    bits = [r["lang"], f"Added {fmt_date(r['added'])}" if r["added"] else "",
            f"{fmt_views(r['pageviews_total'])} views in 30 days" if r["pageviews_total"] else ""]
    tags = "".join(f'<a href="{p}tag/{tag_slug[t]}">#{esc(t)}</a>' for t in r["tagl"][:5])
    desc = r["short_description"] or ""
    return f"""<li class="item">
<div class="thumb" aria-hidden="true">{thumb}</div>
<div class="item-body">
<h2 lang="{esc(r['lang'])}"><a href="{p}{r['href']}">{esc(r['title'])}</a>{badges}</h2>
{f'<p class="desc">{esc(desc)}</p>' if desc else ''}
<p class="meta">{esc('  ·  '.join(b for b in bits if b))}</p>
{f'<div class="tags">{tags}</div>' if tags else ''}
</div>
</li>"""


def item_list(rs, p):
    return '<ul class="items">\n' + "\n".join(item(r, p) for r in rs) + "\n</ul>" if rs else \
        '<p class="empty">Nothing here yet.</p>'


# ---------------------------------------------------------------- home (paginated)

n_lang = len({r["lang"] for r in rows})
sub = f"{len(rows)} article{'s' if len(rows) != 1 else ''} in {n_lang} language{'s' if n_lang != 1 else ''}."
top_tags = sorted(tag_names, key=lambda t: (-len(tag_items[t]), t.lower()))[:8]
size = max(1, args.page_size)
chunks = [rows[i:i + size] for i in range(0, len(rows), size)] or [[]]
lists = sorted({x for r in rows for x in r["listl"]})
langs = sorted(by_lang)
for n, chunk in enumerate(chunks, start=1):
    depth = 0 if n == 1 else 1
    p = "../" * depth
    newer = (p or "./") if n == 2 else f"{p}page/{n - 1}" if n > 2 else ""
    older = f"{p}page/{n + 1}" if n < len(chunks) else ""
    pager = ""
    if newer or older:
        newer_html = f'<a href="{newer}" rel="prev">&larr; Newer</a>' if newer else ""
        older_html = f'<a href="{older}" rel="next">Older &rarr;</a>' if older else ""
        pager = (f'<nav class="pager" id="pager" aria-label="Pages"><span>{newer_html}</span>'
                 f'<span>Page {n} of {len(chunks)}</span><span>{older_html}</span></nav>')
    controls = ""
    if n == 1:
        opt = lambda items: "".join(f'<option value="{esc(i)}">{esc(i)}</option>' for i in items)
        controls = f"""<div class="controls">
<label class="field grow">Search<input type="search" id="q" placeholder="Titles, notes, tags" autocomplete="off"></label>
<label class="field">Sort<select id="sort">
<option value="added">Recently added</option><option value="title">Title A to Z</option>
<option value="views">Most viewed</option><option value="edited">Recently edited</option><option value="length">Longest</option>
</select></label>
<label class="field js-only">List<select id="list"><option value="">All lists</option>{opt(lists)}</select></label>
<label class="field js-only">Language<select id="lang"><option value="">All</option>{opt(langs)}</select></label>
</div>
<div class="taglinks"><a href="./" aria-current="page"><strong>All</strong></a>
{''.join(f'<a href="tag/{tag_slug[t]}">{esc(t)}</a>' for t in top_tags)}
<a class="more" href="tags">All tags &rarr;</a></div>
<p class="status" id="status" role="status" aria-live="polite"></p>"""
    body = f"""<div class="head"><h1>Bookmarks</h1><p class="lede">{esc(sub)}</p></div>
{controls}
<div id="results">{item_list(chunk, p)}</div>
<div id="more-wrap"></div>
{pager}"""
    scripts = f'<script src="{p}site.js" defer></script>'
    write("index.html" if n == 1 else f"page/{n}.html",
          page("Wikipedia Cabinet" if n == 1 else f"Bookmarks, page {n}", body, depth, "home", sub, scripts))

# ---------------------------------------------------------------- tags and categories

def index_page(href_for, names, counts, label_plural, blurb):
    ordered = sorted(names, key=lambda x: (-counts[x], x.lower()))
    lis = [f'<li><a href="{href_for(nme)}">{esc(nme)}</a><span class="n">{counts[nme]}</span></li>' for nme in ordered]
    body = f"""<div class="head"><h1>{label_plural}</h1><p class="lede">{blurb}</p></div>
<div class="controls"><label class="field grow">Filter<input type="search" id="filter" placeholder="Type to filter" autocomplete="off"></label></div>
<p class="status" id="filter-status" role="status" aria-live="polite"></p>
<ul class="index" id="index">
{chr(10).join(lis) if lis else '<li>None yet.</li>'}
</ul>"""
    write(f"{label_plural.lower()}.html", page(f"{label_plural}: Wikipedia Cabinet", body, 0, label_plural.lower(),
                                               blurb, '<script src="site.js" defer></script>'))


index_page(lambda t: f"tag/{tag_slug[t]}", tag_names, {t: len(v) for t, v in tag_items.items()}, "Tags",
           "Your own labels, from the <code>tags</code> column of each list.")
index_page(lambda c: f"category?name={cat_slug[c]}", cat_names, cat_counts, "Categories",
           "Wikipedia's categories, collected from your articles. Hidden maintenance categories are left out.")


def listing_page(name, items, slug):
    one = len(items) == 1
    body = f"""<div class="head"><p class="crumb"><a href="../tags">Tags</a> / {esc(name)}</p>
<h1>{esc(name)}</h1><p class="lede">{len(items)} article{'' if one else 's'}</p></div>
{item_list(items, '../')}"""
    write(f"tag/{slug}.html", page(f"{name}: tag, Wikipedia Cabinet", body, 1, "tags"))


for t in sorted(tag_names):
    listing_page(t, tag_items[t], tag_slug[t])

# One category page for all categories: /category?name=<slug> is drawn in the browser from categories.json,
# so a list with thousands of categories needs no per-category files.
write("category.html", page("Category: Wikipedia Cabinet", """<div id="cat-app">
<div class="head"><p class="crumb"><a href="categories">Categories</a> / <span id="cat-crumb"></span></p>
<h1 id="cat-title">Category</h1><p class="lede" id="cat-count"></p></div>
<noscript><p class="empty">Category pages need JavaScript. Browse <a href="categories">all categories</a> or open an article to see its categories.</p></noscript>
<div id="results"></div><div id="more-wrap"></div>
</div>""", 0, "categories", "Articles in one Wikipedia category.", '<script src="site.js" defer></script>'))
idx_of = {r["key"]: i for i, r in enumerate(rows)}
write("categories.json", json.dumps(
    {cat_slug[c]: {"n": c, "a": [idx_of[r["key"]] for r in cat_items[c]]} for c in sorted(cat_names)},
    ensure_ascii=False, separators=(",", ":")))


# ---------------------------------------------------------------- article pages

def sparkline(series, through):
    vals = [v for _, v in series]
    if not vals:
        return ""
    top, n = max(1, max(vals)), len(vals)
    pts = [((i / (n - 1) if n > 1 else .5) * 300, 58 - v / top * 52) for i, v in enumerate(vals)]
    d = "".join(f"{'L' if i else 'M'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(pts))
    label = f"Daily page views over {n} days to {through}: low {min(vals):,}, high {max(vals):,}, total {sum(vals):,}."
    return (f'<svg class="spark" viewBox="0 0 300 60" preserveAspectRatio="none" role="img" aria-label="{esc(label)}">'
            f'<path class="area" d="{d}L300,60L0,60Z"/><path class="line" d="{d}"/></svg>')


def wiki_url(lang, title):
    return f"https://{lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'), safe=':()!,~*')}"


def kv(pairs):
    return '<dl class="kv">' + "".join(f"<dt>{esc(k)}</dt><dd>{v}</dd>" for k, v in pairs if v) + "</dl>"


def related(r):
    scored = defaultdict(int)
    for t in r["tagl"]:
        for o in tag_items[t]:
            if o is not r:
                scored[o["key"]] += 1
    byk = {x["key"]: x for x in rows}
    return [byk[k] for k, _ in sorted(scored.items(), key=lambda kv_: (-kv_[1], byk[kv_[0]]["title"].lower()))[:5]]


def article_page(r):
    p = "../../"
    side = {}
    sc = data / r["sidecar"] if r["sidecar"] else None
    if sc and sc.exists():
        side = json.loads(sc.read_text(encoding="utf-8"))
    lang, url = r["lang"], r["url"] or wiki_url(r["lang"], r["title"])
    ok = r["status"] == "ok"
    parts = [f'<article class="article" lang="{esc(lang)}">',
             f'<p class="crumb"><a href="{p}">Bookmarks</a> / {esc(r["title"])}</p>',
             f"<h1>{esc(r['title'])}</h1>"]
    if r["short_description"]:
        parts.append(f'<p class="sub">{esc(r["short_description"])}</p>')
    img = ""
    if r["thumb_url"] and r["thumb_width"]:
        alt = f"{r['title']}: {r['short_description']}" if r["short_description"] else r["title"]
        lic = esc(r["image_license"] or "licence not recorded")
        if r["image_license_url"]:
            lic = f'<a href="{esc(r["image_license_url"])}">{lic}</a>'
        fp = f' · <a href="{esc(r["image_page_url"])}">file page</a>' if r["image_page_url"] else ""
        full = r["image_url"] or r["thumb_url"]
        img = (f'<figure><a href="{esc(full)}" target="_blank" rel="noopener" title="Open the full-size image in a new tab">'
               f'<img src="{esc(r["thumb_url"])}" width="{esc(r["thumb_width"])}" height="{esc(r["thumb_height"])}" '
               f'alt="{esc(alt)}" fetchpriority="high"></a><figcaption>Image: {esc(r["image_author"] or "unknown author")} · {lic}{fp}</figcaption></figure>')
    prose = ""
    if ok:
        text = (side.get("intro_text") or r["summary"] or "").strip()
        paras = [x.strip() for x in text.split("\n") if x.strip()] or ["No summary available."]
        prose = "".join(f"<p>{esc(x)}</p>" for x in paras)
    else:
        prose = (f"<p>This page was not available ({esc(r['status'])}). See <code>data/report.csv</code> "
                 f"for the reason.</p>")
    notes = "".join(f'<p class="note">{esc(x)}</p>' for x in (r["notes"].split(" || ") if r["notes"] else []))
    links = (f'<p><a href="{esc(url)}">Read “{esc(r["title"])}” on Wikipedia</a> · '
             f'<a href="{esc(url)}?action=history">history &amp; authors</a> · text under '
             f'<a href="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0</a></p>')
    parts.append(f'<div class="lead{" has-img" if img else ""}">{img}<div class="prose">{prose}{notes}{links}</div></div>')
    if r["tagl"]:
        parts.append('<h2 class="sec">Tags</h2><div class="pills">' +
                     "".join(f'<a href="{p}tag/{tag_slug[t]}">#{esc(t)}</a>' for t in r["tagl"]) + "</div>")
    if r["catl"]:
        parts.append('<h2 class="sec">Categories</h2><div class="pills">' + "".join(
            f'<a href="{p}category?name={cat_slug[c]}">{esc(c)}</a>' for c in r["catl"][:40]) + "</div>")
    facts = [("Language", esc(lang)), ("Lists", esc(", ".join(r["listl"]))), ("Added", esc(fmt_date(r["added"]))),
             ("Last edited", esc(fmt_date(r["last_edited"]))),
             ("Length", f"{int(r['length']):,} bytes" if r["length"] else ""),
             ("30-day views", f"{int(r['pageviews_total']):,}" if r["pageviews_total"] else ""),
             ("Backlinks (articles)", (f"{int(r['backlinks_count']):,}" + ("+ (capped)" if r["backlinks_capped"] == "true" else ""))
              if r["backlinks_count"] else ""),
             ("Outgoing links", r["links_count"]), ("Protection", esc(", ".join(split(r["protection"])))),
             ("Wikidata", f'<a href="https://www.wikidata.org/wiki/{esc(r["wikidata_id"])}">{esc(r["wikidata_id"])}</a>'
              if r["wikidata_id"] else ""),
             ("Coordinates", f'<a href="https://www.openstreetmap.org/?mlat={esc(r["lat"])}&amp;mlon={esc(r["lon"])}'
                             f'#map=10/{esc(r["lat"])}/{esc(r["lon"])}">{esc(r["lat"])}, {esc(r["lon"])}</a>' if r["lat"] else ""),
             ("Also saved as", esc(", ".join(x for x in split(r["requested_titles"]) if x != r["title"])))]
    parts.append('<h2 class="sec">At a glance</h2>' + kv(facts))
    pv = side.get("pageviews")
    if pv and pv.get("series"):
        parts.append(f'<h2 class="sec">Page views, last {len(pv["series"])} days</h2>{sparkline(pv["series"], pv.get("through", ""))}'
                     f'<p class="meta">All platforms, human users, through {esc(pv.get("through", ""))}.</p>')
    wd = side.get("wikidata") or {}
    wf = [f for f in wd.get("facts", []) if f.get("property") != "P18"]
    if wf:
        parts.append('<h2 class="sec">From Wikidata</h2>' + kv([(f["label"], esc("; ".join(f["values"]))) for f in wf]))
    secs = side.get("sections") or []
    if secs:
        parts.append('<h2 class="sec">Contents</h2><ol class="toc">' + "".join(
            f'<li class="l{int(s["level"])}"><a href="{esc(url)}#{esc(quote(s["anchor"], safe="_-.~"))}">{esc(s["number"])} {esc(s["line"])}</a></li>'
            for s in secs) + "</ol>")
    media = [m for m in (side.get("media") or []) if m.get("thumb")][:40]
    if media:
        def media_li(m):
            label = m["caption"] or re.sub(r"\.[A-Za-z0-9]+$", "", m["title"].replace("File:", "")).replace("_", " ")
            dims = f' width="{m["tw"]}" height="{m["th"]}"' if m.get("tw") and m.get("th") else ""
            full = m.get("orig") or wiki_url(lang, m["title"])
            fpage = m.get("page") or wiki_url(lang, m["title"])
            return (f'<li><a class="shot" href="{esc(full)}" target="_blank" rel="noopener" '
                    f'aria-label="{esc(label)} (full-size image, opens in a new tab)">'
                    f'<img src="{esc(m["thumb"])}"{dims} alt="" loading="lazy" decoding="async"></a>'
                    f'<a class="cap" href="{esc(fpage)}" target="_blank" rel="noopener">{esc(label)}'
                    f'<span class="sr"> (file page, opens in a new tab)</span></a></li>')
        parts.append(f'<h2 class="sec">Media ({len(side["media"])})</h2><ul class="gallery">' +
                     "".join(media_li(m) for m in media) + "</ul>")
    ll = side.get("language_links") or []
    if ll:
        parts.append(f'<h2 class="sec">Other languages ({len(ll)})</h2><div class="langs">' + "".join(
            f'<a href="{esc(wiki_url(x["lang"], x["title"]))}" hreflang="{esc(x["lang"])}" lang="{esc(x["lang"])}" '
            f'title="{esc(x["title"])}">{esc(x["lang"])}</a>' for x in ll[:60]) + "</div>")
    rel = related(r)
    if rel:
        parts.append('<h2 class="sec">More like this</h2><ul class="related">' + "".join(
            f'<li><a href="{p}{o["href"]}">{esc(o["title"])}</a> <span class="meta">{esc(o["short_description"])}</span></li>'
            for o in rel) + "</ul>")
    parts.append("</article>")
    write(r["href"] + ".html", page(f"{r['title']}: Wikipedia Cabinet", "\n".join(parts), 2, "home",
                                    r["short_description"] or r["summary"][:160], wide=False,
                                    extra_head=f'<link rel="preload" href="{p}fonts/newsreader-italic-latin.woff2" as="font" '
                                               f'type="font/woff2" crossorigin>'))


for r in rows:
    article_page(r)

# ---------------------------------------------------------------- search index, assets, 404

def num(s):
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


search = [{"t": r["title"], "d": r["short_description"], "l": r["lang"], "a": r["added"], "v": num(r["pageviews_total"]),
           "e": (r["last_edited"] or "")[:10], "n": num(r["length"]), "g": r["tagl"], "gs": [tag_slug[t] for t in r["tagl"]],
           "s": r["listl"], "u": r["href"],
           "i": r["thumb_url"], "st": r["status"], "dis": r["is_disambiguation"] == "true",
           "h": " ".join([r["title"], r["bookmark_title"], " ".join(split(r["requested_titles"])), r["short_description"],
                          r["summary"][:200], " ".join(r["tagl"]), r["notes"], " ".join(r["listl"]),
                          " ".join(r["catl"][:8])]).lower()} for r in rows]
write("search.json", json.dumps(search, ensure_ascii=False, separators=(",", ":")))

base = args.base_path if args.base_path.startswith("/") else "/" + args.base_path
base = base if base.endswith("/") else base + "/"
write("404.html", f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Page not found: Wikipedia Cabinet</title>{HEAD_SCRIPT}<link rel="stylesheet" href="{base}style.css"></head>
<body><div class="wrap"><header class="top"><a class="brand" href="{base}">Wikipedia Cabinet</a>
<nav aria-label="Main"><a href="{base}">Bookmarks</a><a href="{base}tags">Tags</a><a href="{base}categories">Categories</a></nav></header>
<main id="main"><div class="head"><h1>Page not found</h1><p class="lede">That page isn't in the cabinet. Try the
<a href="{base}">bookmark list</a>, <a href="{base}tags">tags</a> or <a href="{base}categories">categories</a>.</p></div></main></div></body></html>
""")

shutil.copytree(args.site, out, dirs_exist_ok=True)   # style.css, site.js, favicon.svg, fonts/
(out / "data").mkdir(exist_ok=True)
shutil.copy(data / "articles.csv", out / "data" / "articles.csv")

n_files = sum(1 for _ in out.rglob("*.html"))
print(f"Built {n_files} pages in {out}/: {len(rows)} articles, {len(tag_names)} tags, "
      f"{len(cat_names)} categories (one shared page), {len(chunks)} list page(s)")


if args.serve:
    import http.server, os
    from urllib.parse import unquote

    root = out.resolve()

    class Pages(http.server.SimpleHTTPRequestHandler):
        """Resolve URLs like GitHub Pages: /x -> x.html, /dir -> dir/index.html, otherwise 404.html."""

        def translate_path(self, path):
            rel = unquote(path.split("?")[0].split("#")[0]).lstrip("/")
            for cand in (root / rel, root / (rel + ".html"), root / rel / "index.html"):
                if cand.is_file():
                    return str(cand)
            return str(root / "404.html")

    os.chdir(root)
    print(f"Serving {root} at http://localhost:{args.serve}/  (Ctrl+C to stop)")
    try:
        http.server.ThreadingHTTPServer(("0.0.0.0", args.serve), Pages).serve_forever()
    except KeyboardInterrupt:
        pass
