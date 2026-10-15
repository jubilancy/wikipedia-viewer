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
- [x] Redirect, non-English, disambiguation and coordinates samples (confirmed by the first sample run)

## Build

- [x] Design agreed (see the plan in the session; summarized in README)
- [x] `wiki_bookmarks.py` (uv script, PEP 723, inline deps)
- [x] Sample lists `data/lists/example.csv` + `travel.csv`
- [x] Run sample, review `data/articles.csv` + `data/report.csv`
- [x] Second run: 0 articles re-fetched, only pageview columns refresh
- [x] Viewer in `site/` (cabinet of curiosities x zettelkasten)
- [x] Browser test: desktop, mobile dark, dialog flip, search, 3,000-row load (no errors). Keyboard flow checked in code only; see README notes
- [ ] Look up current versions of checkout / setup-uv / Pages actions, then `.github/workflows/build.yml`
- [ ] README (add a list, run with `uv run`, trigger a run)
- [ ] Commit, push, draft PR
- [ ] Settings -> Pages -> Source: GitHub Actions (you do this once in the web UI)

## Parked (not requested right now)

- [ ] Recent edit count and top contributors (`prop=revisions` with `rvlimit`)
- [ ] REST edit-count endpoint (my first URL was malformed; recheck before use)
- [ ] Article quality/assessment (the LiftWing URL I guessed returned 404 on GET; find the real model endpoint first)
