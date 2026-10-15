#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""
Turn CSV lists of Wikipedia URLs into data for the bookmark viewer.

Reads data/lists/*.csv (a `url` column, optional `title`, `tags`, `note`, `added`),
resolves every URL to a canonical (language, title), and fetches article data from the
Wikimedia APIs. Writes:

    data/articles.csv          one row per article, stable column order
    data/articles/<lang>/*.json  heavy per-article data (links, TOC, media, pageviews, ...)
    data/report.csv            every failure, warning and notable event (nothing is dropped silently)

Only stale rows are re-fetched (new, edited since last run, errored, or older than --ttl-days).
Pageviews refresh on every run.

    uv run wiki_bookmarks.py                       # normal run
    uv run wiki_bookmarks.py --force               # re-fetch everything
    uv run wiki_bookmarks.py --lists data/lists --out data --ttl-days 30 --concurrency 4
"""
import argparse, csv, html, json, re, sys, threading, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

import requests

VERSION = "0.1"
SCHEMA = 1  # bump to force a re-fetch of cached rows after changing what is stored
UA = f"wikipedia-viewer/{VERSION} (https://github.com/jubilancy/wikipedia-viewer)"

COLUMNS = [
    "key", "lang", "title", "url", "status", "is_disambiguation",
    "requested_titles", "bookmark_title", "lists", "tags", "notes", "added",
    "pageid", "wikidata_id", "short_description", "summary",
    "thumb_url", "thumb_width", "thumb_height",
    "image_url", "image_width", "image_height", "image_file",
    "image_license", "image_license_url", "image_author", "image_page_url",
    "categories", "language_codes",
    "length", "last_revid", "last_edited", "protection", "lat", "lon",
    "backlinks_count", "backlinks_capped", "links_count", "external_links_count",
    "templates_count", "sections_count", "media_count",
    "pageviews_total", "pageviews_days", "pageviews_through",
    "sidecar", "static_fetched", "schema",
]

# Wikidata properties shown as "facts", in display order.
WD_PROPS = ["P31", "P106", "P569", "P19", "P570", "P20", "P27", "P17", "P131", "P571", "P576",
            "P577", "P50", "P136", "P856", "P1082", "P2048", "P2044", "P18"]

http_lock = threading.Lock()
next_slot = 0.0
local = threading.local()
MIN_INTERVAL = 0.15
WIKI_SAFE = ":/()!,~*'"
WIKI_SAFE = ":/()!,~*'"


class FetchError(Exception):
    pass


# ---------------------------------------------------------------- HTTP

def get_json(url, params=None, allow_404=False):
    """GET JSON politely: paced requests, shared pause on 429/5xx (honours Retry-After), 6 attempts."""
    global next_slot
    if not hasattr(local, "s"):
        local.s = requests.Session()
        local.s.headers["User-Agent"] = UA
    last = "no attempt"
    for attempt in range(6):
        with http_lock:
            now = time.monotonic()
            slot = max(now, next_slot)
            next_slot = slot + MIN_INTERVAL
        if slot > now:
            time.sleep(slot - now)
        try:
            r = local.s.get(url, params=params, timeout=60)
        except (requests.ConnectionError, requests.Timeout) as e:
            last, wait = f"{type(e).__name__}", 2 ** (attempt + 1)
        else:
            if r.status_code == 404 and allow_404:
                return None
            if r.status_code == 429 or r.status_code >= 500:
                last = f"HTTP {r.status_code}"
                try:
                    wait = int(r.headers.get("Retry-After", 0)) or 2 ** (attempt + 2)
                except ValueError:
                    wait = 2 ** (attempt + 2)
            elif r.status_code >= 400:
                raise FetchError(f"HTTP {r.status_code} for {r.url}")
            else:
                data = r.json()
                err = data.get("error") if isinstance(data, dict) else None
                if err and err.get("code") == "maxlag":
                    last = "maxlag"
                    wait = int(r.headers.get("Retry-After", 5))
                elif err:
                    raise FetchError(f"{err.get('code')}: {err.get('info')}")
                else:
                    return data
        with http_lock:  # everyone pauses, not just this thread
            next_slot = max(next_slot, time.monotonic() + wait)
    raise FetchError(f"gave up after retries ({last}) for {url}")


def action(lang, **params):
    params.update(action="query", format="json", formatversion=2, maxlag=5)
    return get_json(f"https://{lang}.wikipedia.org/w/api.php", params)


def action_all(lang, params, max_requests=60):
    """Run an Action API query for one page and follow `continue`, merging list props.
    Returns (page, truncated)."""
    page, cont, n = {}, {}, 0
    while True:
        data = action(lang, **params, **cont)
        pages = data.get("query", {}).get("pages", [])
        if pages:
            for k, v in pages[0].items():
                if isinstance(v, list):
                    page.setdefault(k, []).extend(v)
                else:
                    page.setdefault(k, v)
        n += 1
        if "continue" not in data:
            return page, False
        if n >= max_requests:
            return page, True
        cont = data["continue"]


# ---------------------------------------------------------------- helpers

def strip_html(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()


def us(title):
    return title.replace(" ", "_")


def safe_filename(title):
    return re.sub(r'[/\\:*?"<>|%#]', lambda m: f"%{ord(m.group()):02X}", us(title)) + ".json"


def pipe(items):
    return "|".join(str(i) for i in items)


class BadUrl(Exception):
    pass


HOST_RE = re.compile(r"(?:(?P<lang>[a-z][a-z0-9-]*)\.)?(?:m\.)?wikipedia\.org")


def normalize_url(raw):
    """Any Wikipedia article URL -> (lang, title with spaces). Drops query/anchor, decodes percent-encoding."""
    s = raw.strip()
    if not re.match(r"^[a-z][a-z0-9+.-]*://", s, re.I):
        s = "https://" + s
    u = urlsplit(s)
    m = HOST_RE.fullmatch((u.hostname or "").lower())
    if not m or not m.group("lang") or m.group("lang") in ("www", "m"):
        raise BadUrl("not a language-specific Wikipedia URL")
    lang = m.group("lang")
    if u.path.startswith("/wiki/"):
        title = u.path[len("/wiki/"):]
    elif u.path in ("/w/index.php", "/index.php") and "title" in parse_qs(u.query):
        title = parse_qs(u.query)["title"][0]
    else:
        raise BadUrl("not an article URL (expected /wiki/Title or index.php?title=...)")
    title = re.sub(r"\s+", " ", unquote(title).replace("_", " ")).strip()
    if not title:
        raise BadUrl("empty title")
    if title.lower().startswith("special:"):
        raise BadUrl("special pages are not supported")
    return lang, title


# ---------------------------------------------------------------- input

def split_multi(s):
    return [t.strip() for t in re.split(r"[|;,]", s or "") if t.strip()]


def read_lists(folder, report):
    inputs = []
    files = sorted(Path(folder).glob("*.csv"))
    for f in files:
        with open(f, newline="", encoding="utf-8-sig") as fh:
            rd = csv.DictReader(fh)
            if not rd.fieldnames or "url" not in [h.strip().lower() for h in rd.fieldnames]:
                report.append(("error", f.stem, 0, "", "", "no_url_column", f"{f.name} has no `url` column"))
                continue
            for i, row in enumerate(rd, start=2):
                row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
                if not any(row.values()):
                    continue
                raw = row.get("url", "")
                try:
                    lang, title = normalize_url(raw)
                except BadUrl as e:
                    report.append(("error", f.stem, i, raw, "", "bad_url", str(e)))
                    continue
                inputs.append({"list": f.stem, "line": i, "raw": raw, "lang": lang, "title": title,
                               "bookmark_title": row.get("title", ""), "tags": split_multi(row.get("tags")),
                               "note": row.get("note", ""), "added": row.get("added", "")})
    return files, inputs


# ---------------------------------------------------------------- resolve (cheap pass)

def resolve_titles(lang, titles):
    """Batched info query with redirects. Returns {requested_title: page dict or {'invalid':True,...}}."""
    out = {}
    titles = sorted(set(titles))
    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        data = action(lang, titles="|".join(batch), redirects=1, prop="info|pageprops",
                      ppprop="disambiguation|wikibase_item")
        q = data["query"]
        hop = {}
        for k in ("normalized", "converted", "redirects"):
            for r in q.get(k, []):
                hop.setdefault(r["from"], []).append((k, r))
        by_title = {p["title"]: p for p in q.get("pages", [])}
        for t in batch:
            cur, via, seen = t, [], 0
            while cur in hop and seen < 10:
                k, r = hop[cur].pop(0) if hop[cur] else (None, None)
                if r is None:
                    break
                cur, seen = r["to"], seen + 1
                if k == "redirects":
                    via.append(r["to"])
            page = dict(by_title.get(cur, {"title": cur, "invalid": True}))
            page["_redirected_to"] = via[-1] if via else ""
            out[t] = page
    return out


# ---------------------------------------------------------------- per-article fetch

def wd_value(dv, labels):
    t, v = dv.get("type"), dv.get("value")
    if t == "wikibase-entityid":
        return labels.get(v["id"], v["id"])
    if t == "time":
        s = v["time"].lstrip("+")
        prec = v.get("precision", 11)
        return s[:4] if prec <= 9 else s[:7] if prec == 10 else s[:10]
    if t == "quantity":
        unit = v.get("unit", "")
        uid = unit.rsplit("/", 1)[-1] if unit.startswith("http") else ""
        return f"{v['amount'].lstrip('+')} {labels.get(uid, uid)}".strip()
    if t == "monolingualtext":
        return v["text"]
    if t == "globecoordinate":
        return f"{v['latitude']:.4f}, {v['longitude']:.4f}"
    return str(v)


def fetch_wikidata(qid, notes):
    d = get_json("https://www.wikidata.org/w/api.php",
                 {"action": "wbgetentities", "ids": qid, "props": "labels|descriptions|claims|sitelinks",
                  "languages": "en", "format": "json"})
    ent = d["entities"][qid]
    claims = {p: ent.get("claims", {}).get(p, []) for p in WD_PROPS}
    ids = set(WD_PROPS)
    for stmts in claims.values():
        for s in stmts:
            dv = s.get("mainsnak", {}).get("datavalue")
            if dv and dv["type"] == "wikibase-entityid":
                ids.add(dv["value"]["id"])
            if dv and dv["type"] == "quantity" and dv["value"].get("unit", "").startswith("http"):
                ids.add(dv["value"]["unit"].rsplit("/", 1)[-1])
    labels, idl = {}, sorted(ids)
    for i in range(0, len(idl), 50):
        ld = get_json("https://www.wikidata.org/w/api.php",
                      {"action": "wbgetentities", "ids": "|".join(idl[i:i + 50]), "props": "labels",
                       "languages": "en", "format": "json"})
        for k, e in ld["entities"].items():
            labels[k] = e.get("labels", {}).get("en", {}).get("value", k)
    facts = []
    for p in WD_PROPS:
        vals = []
        for s in claims[p]:
            if s.get("rank") == "deprecated":
                continue
            dv = s.get("mainsnak", {}).get("datavalue")
            if dv:
                vals.append(wd_value(dv, labels))
        if vals:
            facts.append({"property": p, "label": labels.get(p, p), "values": vals[:10]})
    return {"id": qid, "label": ent.get("labels", {}).get("en", {}).get("value", ""),
            "description": ent.get("descriptions", {}).get("en", {}).get("value", ""),
            "sitelink_count": len(ent.get("sitelinks", {})), "facts": facts}


def fetch_article(lang, title, page):
    """Full static fetch for one article. Returns (row_fields, sidecar, report_items)."""
    notes, side, row = [], {}, {}
    t_us = quote(us(title), safe="")
    props = dict(titles=title, prop="info|pageprops|description|extracts|pageimages|coordinates|revisions|"
                 "categories|links|extlinks|templates|langlinks|redirects",
                 inprop="protection|url", exintro=1, explaintext=1, exlimit=1,
                 piprop="thumbnail|original|name", pithumbsize=480, coprimary="primary", colimit=1,
                 cllimit="max", clshow="!hidden", pllimit="max", plnamespace=0, ellimit="max",
                 tllimit="max", lllimit="max", rdlimit="max", rvprop="ids|timestamp")
    p, trunc = action_all(lang, props)
    if trunc:
        notes.append(("warning", "truncated_lists", "link/category lists were cut at the request cap"))
    pp = p.get("pageprops", {})
    cats = sorted(c["title"].split(":", 1)[-1] for c in p.get("categories", []))
    links = sorted({x["title"] for x in p.get("links", [])})
    ext = sorted({x["url"] for x in p.get("extlinks", [])})
    tmpl = sorted(x["title"].split(":", 1)[-1] for x in p.get("templates", []))
    langs = sorted((x["lang"], x["title"]) for x in p.get("langlinks", []))
    aliases = sorted(x["title"] for x in p.get("redirects", []))
    rev = (p.get("revisions") or [{}])[0]
    prot = [f"{x['type']}={x['level']}" for x in p.get("protection", [])]
    coords = (p.get("coordinates") or [{}])[0]

    # backlinks: count only, capped
    bl_page, bl_capped = action_all(lang, dict(titles=title, prop="linkshere", lhlimit="max",
                                               lhnamespace=0, lhprop="pageid"), max_requests=4)
    backlinks = len(bl_page.get("linkshere", []))

    # summary (REST)
    summ = get_json(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{t_us}?redirect=false",
                    allow_404=True) or {}
    if not summ:
        notes.append(("warning", "no_summary", "REST summary returned 404"))
    is_dis = "disambiguation" in pp or summ.get("type") == "disambiguation"

    # table of contents
    sections = []
    try:
        pd = get_json(f"https://{lang}.wikipedia.org/w/api.php",
                      {"action": "parse", "page": title, "prop": "sections", "format": "json",
                       "formatversion": 2, "maxlag": 5})
        sections = [{"number": s["number"], "level": int(s["level"]), "line": strip_html(s["line"]),
                     "anchor": s["anchor"]} for s in pd.get("parse", {}).get("sections", [])]
    except FetchError as e:
        notes.append(("warning", "toc_failed", str(e)))

    # media list (REST)
    media = []
    try:
        ml = get_json(f"https://{lang}.wikipedia.org/api/rest_v1/page/media-list/{t_us}", allow_404=True) or {}
        for it in ml.get("items", []):
            src = (it.get("srcset") or [{}])[0].get("src", "")
            media.append({"title": it.get("title", ""), "type": it.get("type", ""),
                          "section_id": it.get("section_id"), "lead": bool(it.get("leadImage")),
                          "caption": (it.get("caption") or {}).get("text", ""),
                          "thumb": ("https:" + src) if src.startswith("//") else src})
    except FetchError as e:
        notes.append(("warning", "media_failed", str(e)))

    # lead image license/author
    img = {}
    fname = p.get("pageimage")
    if fname:
        try:
            idata = action(lang, titles="File:" + fname, prop="imageinfo",
                           iiprop="extmetadata|size|mime|url", iiextmetadatafilter=
                           "LicenseShortName|LicenseUrl|Artist|Credit|ImageDescription|Attribution|UsageTerms")
            ii = (idata["query"]["pages"][0].get("imageinfo") or [{}])[0]
            em = {k: v.get("value", "") for k, v in ii.get("extmetadata", {}).items()}
            img = {"file": fname, "page_url": ii.get("descriptionurl", ""), "mime": ii.get("mime", ""),
                   "license": em.get("LicenseShortName") or em.get("UsageTerms", ""),
                   "license_url": em.get("LicenseUrl", ""), "author_html": em.get("Artist", ""),
                   "author": strip_html(em.get("Artist", "")), "credit_html": em.get("Credit", ""),
                   "attribution": strip_html(em.get("Attribution", "")),
                   "description": strip_html(em.get("ImageDescription", ""))}
        except FetchError as e:
            notes.append(("warning", "image_license_failed", str(e)))
    else:
        notes.append(("info", "no_image", "article has no lead image"))

    # Wikidata
    wd = {}
    qid = pp.get("wikibase_item")
    if qid:
        try:
            wd = fetch_wikidata(qid, notes)
        except (FetchError, KeyError) as e:
            notes.append(("warning", "wikidata_failed", str(e)))

    th, orig = p.get("thumbnail") or {}, p.get("original") or {}
    row = {
        "pageid": p.get("pageid", ""), "wikidata_id": qid or "", "is_disambiguation": str(is_dis).lower(),
        "short_description": p.get("description", ""), "summary": summ.get("extract", ""),
        "thumb_url": th.get("source", ""), "thumb_width": th.get("width", ""), "thumb_height": th.get("height", ""),
        "image_url": orig.get("source", ""), "image_width": orig.get("width", ""),
        "image_height": orig.get("height", ""), "image_file": img.get("file", ""),
        "image_license": img.get("license", ""), "image_license_url": img.get("license_url", ""),
        "image_author": img.get("author", ""), "image_page_url": img.get("page_url", ""),
        "categories": pipe(cats), "language_codes": pipe(l for l, _ in langs),
        "length": p.get("length", ""), "last_revid": p.get("lastrevid", ""),
        "last_edited": rev.get("timestamp", ""), "protection": pipe(prot),
        "lat": coords.get("lat", ""), "lon": coords.get("lon", ""),
        "backlinks_count": backlinks, "backlinks_capped": str(bl_capped).lower(),
        "links_count": len(links), "external_links_count": len(ext), "templates_count": len(tmpl),
        "sections_count": len(sections), "media_count": len(media),
        "url": p.get("canonicalurl", ""),
    }
    side = {
        "key": f"{lang}/{us(title)}", "lang": lang, "title": title,
        "summary_text": summ.get("extract", ""), "summary_html": summ.get("extract_html", ""),
        "intro_text": p.get("extract", ""), "page_url": p.get("canonicalurl", ""),
        "display_title": summ.get("displaytitle", ""), "protection": prot, "aliases": aliases,
        "categories": cats, "links": links, "external_links": ext, "templates": tmpl,
        "language_links": [{"lang": l, "title": t} for l, t in langs],
        "backlinks": {"count": backlinks, "capped": bl_capped, "namespace": 0},
        "sections": sections, "media": media, "lead_image": img,
        "thumbnail": th, "original_image": orig, "coordinates": p.get("coordinates", []),
        "wikidata": wd,
    }
    return row, side, notes


def fetch_pageviews(lang, title, days):
    end = datetime.now(timezone.utc).date() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    url = (f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{lang}.wikipedia/all-access/user/"
           f"{quote(us(title), safe='')}/daily/{start:%Y%m%d}/{end:%Y%m%d}")
    d = get_json(url, allow_404=True)
    got = {it["timestamp"][:8]: it["views"] for it in (d or {}).get("items", [])}
    series = []
    for i in range(days):
        day = start + timedelta(days=i)
        series.append([day.isoformat(), got.get(f"{day:%Y%m%d}", 0)])
    return series, end.isoformat(), d is None


# ---------------------------------------------------------------- main

def main():
    global MIN_INTERVAL
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lists", default="data/lists", help="folder of input CSVs")
    ap.add_argument("--out", default="data", help="output folder")
    ap.add_argument("--ttl-days", type=int, default=30, help="re-fetch static data older than this")
    ap.add_argument("--force", action="store_true", help="re-fetch everything")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--pageview-days", type=int, default=30)
    args = ap.parse_args()

    out = Path(args.out)
    report = []  # (severity, list, line, input, key, code, message)
    files, inputs = read_lists(args.lists, report)
    if not files:
        print(f"No CSV files in {args.lists}", file=sys.stderr)
        return 2
    print(f"{len(files)} lists, {len(inputs)} bookmark rows")

    # 1. resolve every requested title (batched, follows redirects)
    resolved = {}
    by_lang = defaultdict(set)
    for r in inputs:
        by_lang[r["lang"]].add(r["title"])
    for lang, titles in sorted(by_lang.items()):
        try:
            for t, p in resolve_titles(lang, titles).items():
                resolved[(lang, t)] = p
        except FetchError as e:
            for t in titles:
                resolved[(lang, t)] = {"title": t, "_error": str(e)}

    # 2. merge by (lang, resolved title)
    arts = {}
    for r in inputs:
        p = resolved[(r["lang"], r["title"])]
        title = p["title"]
        key = f"{r['lang']}/{us(title)}"
        a = arts.setdefault(key, {"lang": r["lang"], "title": title, "page": p, "requested": set(),
                                  "lists": set(), "tags": set(), "notes": [], "added": [], "bt": []})
        a["requested"].add(r["title"])
        a["lists"].add(r["list"])
        a["tags"].update(r["tags"])
        if r["note"] and r["note"] not in a["notes"]:
            a["notes"].append(r["note"])
        if r["added"]:
            a["added"].append(r["added"])
        if r["bookmark_title"]:
            a["bt"].append(r["bookmark_title"])
        if p.get("_error"):
            report.append(("error", r["list"], r["line"], r["raw"], key, "resolve_failed", p["_error"]))
        elif p.get("invalid") or p.get("special"):
            report.append(("error", r["list"], r["line"], r["raw"], key, "invalid_title", "invalid title"))
        elif p.get("missing"):
            report.append(("error", r["list"], r["line"], r["raw"], key, "missing_article",
                           "article does not exist"))
        elif p.get("_redirected_to"):
            report.append(("info", r["list"], r["line"], r["raw"], key, "redirect",
                           f"{r['title']} -> {title}"))
        elif r["title"] != title:
            report.append(("info", r["list"], r["line"], r["raw"], key, "normalized", f"{r['title']} -> {title}"))
    dupes = len(inputs) - len(arts)
    if dupes:
        report.append(("info", "", 0, "", "", "merged_duplicates",
                       f"{dupes} bookmark rows merged into existing articles"))

    # 3. load cache and decide what is stale
    prev = {}
    csv_path = out / "articles.csv"
    if csv_path.exists():
        with open(csv_path, newline="", encoding="utf-8") as fh:
            prev = {r["key"]: r for r in csv.DictReader(fh)}
    today = date.today()
    todo = []
    for key, a in sorted(arts.items()):
        pg, old = a["page"], prev.get(key)
        a["status"] = ("error" if pg.get("_error") else "invalid" if pg.get("invalid") or pg.get("special")
                       else "missing" if pg.get("missing") else "ok")
        side_ok = old and (out / old["sidecar"]).exists() if old else False
        try:
            age = (today - date.fromisoformat(old["static_fetched"])).days if old else 10 ** 6
        except (ValueError, KeyError):
            age = 10 ** 6
        a["stale"] = a["status"] == "ok" and (
            args.force or not old or not side_ok or old.get("status") != "ok"
            or str(pg.get("lastrevid", "")) != old.get("last_revid") or age >= args.ttl_days
            or old.get("schema") != str(SCHEMA))
        if a["stale"]:
            todo.append(key)
    print(f"{len(arts)} articles, {len(todo)} to fetch, {len(arts) - len(todo)} cached")

    # 4. fetch stale articles + pageviews for every ok article
    MIN_INTERVAL = max(0.05, 0.6 / max(1, args.concurrency))

    def work(key):
        a = arts[key]
        lang, title = a["lang"], a["title"]
        res = {"row": None, "side": None, "notes": [], "err": None, "pv": None, "pv_missing": False}
        try:
            if a["stale"]:
                res["row"], res["side"], res["notes"] = fetch_article(lang, title, a["page"])
            if a["status"] == "ok":
                res["pv"] = fetch_pageviews(lang, title, args.pageview_days)
        except Exception as e:  # never crash the run, never drop the bookmark
            res["err"] = f"{type(e).__name__}: {e}"
        return key, res

    results = {}
    keys = [k for k, a in sorted(arts.items()) if a["status"] == "ok"]
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        for n, (key, res) in enumerate(ex.map(work, keys), 1):
            results[key] = res
            print(f"  [{n}/{len(keys)}] {key}{'  (fetched)' if arts[key]['stale'] else ''}"
                  f"{'  ERROR ' + res['err'] if res['err'] else ''}", flush=True)

    # 5. assemble rows + sidecars
    rows, keep_sidecars = [], set()
    for key, a in sorted(arts.items()):
        lang, title = a["lang"], a["title"]
        sidecar = f"articles/{lang}/{safe_filename(title)}"
        old = prev.get(key)
        row = {c: "" for c in COLUMNS}
        res = results.get(key)
        side = None
        if res and res["row"]:
            row.update(res["row"])
            side = res["side"]
            row["static_fetched"] = today.isoformat()
            row["status"] = "ok"
            for sev, code, msg in res["notes"]:
                report.append((sev, "", 0, "", key, code, msg))
            if row["is_disambiguation"] == "true":
                report.append(("warning", "", 0, "", key, "disambiguation",
                               "article is a disambiguation page"))
        elif old and a["status"] == "ok":  # cached and still fresh, or fetch failed
            row.update({c: old.get(c, "") for c in COLUMNS})
            p = out / sidecar
            if p.exists():
                side = json.loads(p.read_text(encoding="utf-8"))
            if res and res["err"]:
                row["status"] = "error"
        else:
            row["status"] = a["status"] if a["status"] != "ok" else "error"
        if res and res["err"]:
            report.append(("error", "", 0, "", key, "fetch_failed", res["err"]))
        row.update({"key": key, "lang": lang, "title": title, "sidecar": sidecar, "schema": SCHEMA,
                    "requested_titles": pipe(sorted(a["requested"])),
                    "bookmark_title": a["bt"][0] if a["bt"] else "", "lists": pipe(sorted(a["lists"])),
                    "tags": pipe(sorted(a["tags"], key=str.lower)), "notes": " || ".join(a["notes"]),
                    "added": min(a["added"]) if a["added"] else ""})
        if not row["url"]:
            row["url"] = f"https://{lang}.wikipedia.org/wiki/" + quote(us(title), safe=WIKI_SAFE)
        if res and res["pv"]:
            series, through, no_data = res["pv"]
            row["pageviews_total"] = sum(v for _, v in series)
            row["pageviews_days"] = len(series)
            row["pageviews_through"] = through
            if side is not None:
                side["pageviews"] = {"granularity": "daily", "access": "all-access", "agent": "user",
                                     "through": through, "series": series}
            if no_data:
                report.append(("info", "", 0, "", key, "no_pageviews", "pageviews API had no data for the range"))
        if side is not None:
            side["bookmark"] = {k: row[k] for k in ("requested_titles", "bookmark_title", "lists", "tags",
                                                   "notes", "added")}
            path = out / sidecar
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(side, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                            encoding="utf-8")
            keep_sidecars.add(path.resolve())
        rows.append(row)

    # 6. write outputs (stable order) and prune sidecars of articles no longer listed
    out.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["key"]))
    for old_file in (out / "articles").glob("*/*.json") if (out / "articles").exists() else []:
        if old_file.resolve() not in keep_sidecars:
            old_file.unlink()
            report.append(("info", "", 0, "", "", "pruned_sidecar", f"removed {old_file.relative_to(out)}"))
    with open(out / "report.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["severity", "list", "line", "input", "key", "code", "message"])
        order = {"error": 0, "warning": 1, "info": 2}
        for r in sorted(report, key=lambda r: (order[r[0]], r[1], r[2], r[4], r[5], r[6])):
            w.writerow(r)

    counts = defaultdict(int)
    for r in report:
        counts[r[0]] += 1
    print(f"\nWrote {len(rows)} rows to {csv_path}; report: {dict(counts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
