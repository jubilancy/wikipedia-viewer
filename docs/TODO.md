# To-do

Scope trimmed by request: no revision-history stats, no top contributors, no edit counts, no article-quality score.
Those are parked at the bottom.

## Verified endpoints (live JSON checked 2026-10-15)

- [x] Action API `query`: info, pageprops, description, extracts, pageimages, coordinates, revisions, categories, links, extlinks, templates, langlinks, linkshere, redirects
- [x] Action API `parse` (`prop=sections`) for the table of contents
- [x] REST `page/summary` and `page/media-list`
- [x] Commons/wiki `imageinfo` + `extmetadata` for image license and author
- [x] Pageviews per-article daily (`wikimedia.org/api/rest_v1/metrics/pageviews`)
- [x] Wikidata `wbgetentities`
- [ ] Redirect, non-English, disambiguation and coordinates samples (checked by the first script run)

## Build

- [x] Design agreed (see the plan in the session; summarized in README)
- [ ] `wiki_bookmarks.py` (uv script, PEP 723, inline deps)
- [ ] Sample list `data/lists/example.csv` (normal, redirect, disambiguation, no image, non-English, missing)
- [ ] Run sample, review `data/articles.csv` + `data/report.csv`
- [ ] Second run: confirm only stale rows re-fetch and output is diff-clean except pageviews
- [ ] Viewer in `site/` (cabinet of curiosities x zettelkasten)
- [ ] Browser test (desktop, mobile, dark mode, keyboard)
- [ ] Look up current versions of checkout / setup-uv / Pages actions, then `.github/workflows/build.yml`
- [ ] README (add a list, run with `uv run`, trigger a run)
- [ ] Commit, push, draft PR
- [ ] Settings -> Pages -> Source: GitHub Actions (you do this once in the web UI)

## Parked (not requested right now)

- [ ] Recent edit count and top contributors (`prop=revisions` with `rvlimit`)
- [ ] REST edit-count endpoint (my first URL was malformed; recheck before use)
- [ ] Article quality/assessment (the LiftWing URL I guessed returned 404 on GET; find the real model endpoint first)
