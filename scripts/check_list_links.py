#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""
check_list_links.py - check every Wikipedia URL in a list CSV against the live API before it is added to the site.

Reports, for each CSV in data/lists/ (or the files you name): articles that do not exist, disambiguation pages,
redirects (requested title -> final title), and several rows that end up as the same article (their tags are merged
by wiki_bookmarks.py). English Wikipedia only; rows in other languages are listed as skipped.

Usage:
    uv run scripts/check_list_links.py "data/lists/Middle Ages.csv"
    uv run scripts/check_list_links.py data/lists/*.csv

This is a small read-only helper that prints to the screen and changes nothing, so it does not write a results log.
"""
import csv, sys, time
from urllib.parse import unquote, urlsplit

import requests

UA = "wikipedia-viewer/0.1 (https://github.com/jubilancy/wikipedia-viewer)"
session = requests.Session()
session.headers["User-Agent"] = UA


def api(params):
    """GET the English Wikipedia API, waiting out 429/5xx using Retry-After."""
    for attempt in range(8):
        r = session.get("https://en.wikipedia.org/w/api.php", params=params, timeout=60)
        if r.status_code == 429 or r.status_code >= 500:
            wait = int(r.headers.get("Retry-After", 0)) or 2 ** (attempt + 1)
            print(f"  (rate limited, waiting {wait}s)", file=sys.stderr)
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()
    raise SystemExit("gave up after repeated rate limiting")


def check(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    items, skipped = [], []
    for r in rows:
        u = urlsplit(r["url"].strip())
        if u.hostname != "en.wikipedia.org" or not u.path.startswith("/wiki/"):
            skipped.append(r["url"])
            continue
        items.append((r.get("title") or r["url"], unquote(u.path[len("/wiki/"):]).replace("_", " ")))
    print(f"\n== {path}: {len(rows)} rows, {len(items)} English article links, {len(skipped)} skipped")
    if skipped:
        print("   skipped (not en.wikipedia.org/wiki/...):", skipped)

    uniq = sorted({t for _, t in items})
    resolved = {}
    for i in range(0, len(uniq), 50):
        batch = uniq[i:i + 50]
        q = api({"action": "query", "format": "json", "formatversion": 2, "titles": "|".join(batch), "redirects": 1,
                 "prop": "pageprops", "ppprop": "disambiguation", "maxlag": 5})["query"]
        hop = {x["from"]: x["to"] for k in ("normalized", "redirects") for x in q.get(k, [])}
        pages = {p["title"]: p for p in q["pages"]}
        for t in batch:
            cur, n = t, 0
            while cur in hop and n < 10:
                cur, n = hop[cur], n + 1
            resolved[t] = (cur, pages.get(cur, {}))

    missing, disamb, redirects, groups = [], [], [], {}
    for label, t in items:
        cur, p = resolved[t]
        if p.get("missing") or p.get("invalid"):
            missing.append((label, t))
        if "disambiguation" in p.get("pageprops", {}):
            disamb.append((label, cur))
        if cur != t:
            redirects.append((label, t, cur))
        groups.setdefault(cur, []).append(label)
    print(f"   MISSING ({len(missing)}): {missing or '(none)'}")
    print(f"   DISAMBIGUATION ({len(disamb)}): {disamb or '(none)'}")
    print(f"   REDIRECTS ({len(redirects)}):" + ("" if redirects else " (none)"))
    for label, a, b in redirects:
        print(f"      {label}: {a} -> {b}")
    shared = {k: v for k, v in groups.items() if len(v) > 1}
    print(f"   SAME ARTICLE ON SEVERAL ROWS ({len(shared)}): {shared or '(none)'}")
    print(f"   -> {len(groups)} distinct articles after redirects")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for p in sys.argv[1:]:
        check(p)
