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
- [x] Browser test: desktop, mobile dark, dialog flip, search, 3,000-row load (no errors). keyboard flow (Enter, arrows, F, Esc, deep link) also tested; fixed dialog focus
- [x] Looked up current action versions live (checkout v7, setup-uv v10.3.0 exact, upload-pages-artifact v5, deploy-pages v5) and wrote `.github/workflows/build.yml`. Not yet run on GitHub.
- [x] README (add a list, run with `uv run`, trigger a run)
- [x] Commit, push, draft PR ([#1](https://github.com/jubilancy/wikipedia-viewer/pull/1))
- [ ] You: Settings -> Pages -> Build and deployment -> Source: GitHub Actions (once, in the web UI)
- [ ] First workflow run on GitHub (merge the PR to `main`, or run it from the Actions tab) to confirm the Pages deploy

## Journal restyle (second change)

- [x] Design: 3 directions in Claude Design, Journal chosen (saved as separate Design artifacts)
- [x] `build_site.py`: static pages, clean extension-less URLs (`/tag/food`, `/article/<lang>/<title>`, `/category?name=<slug>`)
- [x] `/tags` and `/categories` pages, article-style detail pages, paginated home, search.json
- [x] Categories drawn by one `/category?name=<slug>` page from `categories.json` (no per-category files); tags stay real pages
- [x] Link check: 0 broken of 1,195 internal references on the sample data
- [ ] After deploy: confirm `/tag/food` loads without `.html` on the live site (extension-less `/index` already returns 200)

## Parked (not requested right now)

- [ ] Recent edit count and top contributors (`prop=revisions` with `rvlimit`)
- [ ] REST edit-count endpoint (my first URL was malformed; recheck before use)
- [ ] Article quality/assessment (the LiftWing URL I guessed returned 404 on GET; find the real model endpoint first)
