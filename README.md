# Wikipedia Cabinet

A personal Wikipedia bookmark viewer. You keep CSV lists of Wikipedia URLs. A `uv` script turns them into one merged CSV
plus a JSON file per article, and a static page shows them as index cards pinned on a desk. GitHub Actions refreshes the
data and publishes the site to GitHub Pages.

```
data/lists/*.csv  ->  wiki_bookmarks.py  ->  data/articles.csv  ->  site/ (viewer)  ->  GitHub Pages
                                             data/articles/<lang>/*.json
                                             data/report.csv
```

## The script

`wiki_bookmarks.py` reads every CSV in `data/lists/`, resolves each URL to a canonical (language, title), and fetches
article data from the Wikimedia APIs. Only stale articles are re-fetched. Pageviews refresh on every run.

```bash
uv run wiki_bookmarks.py                 # normal run (cache-aware)
uv run wiki_bookmarks.py --force         # re-fetch every article
uv run wiki_bookmarks.py --ttl-days 7    # treat static data older than 7 days as stale (default 30)
uv run wiki_bookmarks.py --help          # all options
```

Dependencies are declared inline (PEP 723), so there is nothing to install first.

### Add a new list

1. Add a CSV to `data/lists/`, for example `data/lists/reading.csv`. The file name (without `.csv`) becomes the list name.
2. Columns: `url` is required. Optional: `title`, `tags`, `note`, `added`.

   ```csv
   url,title,tags,note,added
   https://en.wikipedia.org/wiki/Ada_Lovelace,,"people, computing",First programmer?,2026-01-05
   https://de.m.wikipedia.org/wiki/S%C3%BC%C3%9Figkeit,,food,Non-English,2026-03-10
   ```

3. Any language edition works, plus mobile URLs (`en.m.wikipedia.org`), anchors, query strings, percent-encoding and
   redirects. Tags can be separated by commas, semicolons or pipes.
4. Commit it. The workflow runs on push and refreshes the site (see below).

An article that appears in several lists, or under several redirect titles, becomes one row. Its `lists` column holds
every list it came from, tags and notes are merged, and the earliest `added` date wins.

### What it writes

| File | Contents |
|---|---|
| `data/articles.csv` | One row per article, stable column order. Multi-value fields (`lists`, `tags`, `categories`, `language_codes`, `requested_titles`, `protection`) are pipe-joined. `notes` are joined with ` \|\| `. |
| `data/articles/<lang>/<title>.json` | The heavy data: HTML and plain summaries, links, external links, templates, redirects/aliases, language links, table of contents, media list, lead-image license and author, Wikidata facts, coordinates, daily pageviews. |
| `data/report.csv` | Every error, warning and notable event (bad URL, missing article, disambiguation page, redirect, no image, failed fetch). Bookmarks are never dropped silently. |

Main CSV columns: `key, lang, title, url, status, is_disambiguation, requested_titles, bookmark_title, lists, tags, notes,
added, pageid, wikidata_id, short_description, summary, thumb_*, image_*, categories, language_codes, length, last_revid,
last_edited, protection, lat, lon, backlinks_count, backlinks_capped, links_count, external_links_count, templates_count,
sections_count, media_count, pageviews_total, pageviews_days, pageviews_through, sidecar, static_fetched, schema`.

### How refresh works

- Each run resolves every requested title in batches of 50 (this follows redirects and reads the current revision ID).
- A row is re-fetched in full only if it is new, its last revision changed, it failed or was missing last time, its
  static data is older than `--ttl-days`, or you pass `--force`.
- Pageviews (30 daily values, plus the total) refresh for every article on every run.
- The cache is simply the committed `data/` folder, so there is nothing else to store.
- Output is sorted and column order is fixed, so commits show clean diffs. Sidecars of articles you remove from the lists
  are deleted.

### Being polite to Wikimedia

The script sends a descriptive `User-Agent` with this repo's URL, paces requests, uses bounded concurrency
(`--concurrency`, default 4), retries with backoff on 429 and 5xx errors (honouring `Retry-After`), and sends `maxlag=5`.
Wikimedia rate-limits shared IP addresses, so expect pauses: the first sample run of 7 articles took a few minutes.

### Known limits

- `backlinks_count` counts articles (namespace 0) and stops at 2,000 (`backlinks_capped=true`).
- Lead-image license and author come from the image file page (Wikimedia Commons or the local wiki). Articles with no lead
  image are listed in the report as `no_image`.
- Not included (parked in [`docs/TODO.md`](docs/TODO.md)): recent edit counts and top contributors, and article quality
  ratings. I did not find a verified endpoint for quality ratings.

## The viewer

Plain HTML, CSS and JavaScript in `site/`, no build step. It loads `data/articles.csv` in the browser and renders index
cards with mixed-size images and handwritten-style notes and tags.

- Search, filters (list, language, category, tags, with-image), and sorting (recently added, title, most viewed, recently
  edited, longest, shuffle). Filters are kept in the page URL.
- Cards render in batches as you scroll, and images load lazily, so thousands of rows stay smooth. A 3,000-row test loaded
  with no errors.
- Click a card to open it, then turn it over for the details (pageview chart, Wikidata facts, counts, contents, media,
  other languages). `F` flips, `←` and `→` move between cards, `Esc` closes. `#lang/Title` in the URL opens a card.
- Light and dark themes (follows your system, with a manual toggle) and a single-column mobile layout.
- Text is CC BY-SA 4.0 with a link to each source page and its history. Each image shows its author, license and file page.

### Preview in a browser-based editor

From the repo root, serve the files and open `/site/`:

```bash
uv run python -m http.server 8000
```

Then open the forwarded port 8000 at `/site/index.html` (in GitHub Codespaces, use the Ports tab). The viewer looks for
`data/` next to `index.html` (the deployed layout) and falls back to `../data/`.

## Automation

`.github/workflows/build.yml` ("Build and deploy"):

| Trigger | When |
|---|---|
| `push` to `main` | when `data/lists/**`, the script, `site/**` or the workflow changes |
| `schedule` | daily at 05:17 UTC (refreshes pageviews and picks up edits) |
| `workflow_dispatch` | manually |

Steps: run the script, commit `data/` if it changed (otherwise log "No data changes" and continue), assemble `site/` plus
`data/`, then deploy to Pages. Permissions are minimal: `contents: write` only in the build job, `pages: write` and
`id-token: write` only in the deploy job. Commits made with the built-in token do not retrigger workflows, and a
`concurrency` group stops two runs from racing.

### One-time setup (GitHub web UI)

1. Repo **Settings → Pages → Build and deployment → Source: GitHub Actions**
   ([GitHub docs](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)).
2. Only if the data commit step fails with a permissions error: repo **Settings → Actions → General → Workflow
   permissions**, and choose the read and write option
   ([GitHub docs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository)).
   The workflow already asks for `contents: write` itself, but an organization policy can cap it.

### Trigger a regeneration

Repo **Actions** tab → **Build and deploy** → **Run workflow**. Tick "Re-fetch every article" to ignore the cache.

## Layout

```
wiki_bookmarks.py        the script (uv, PEP 723)
data/lists/*.csv         your input lists (edit these)
data/articles.csv        generated
data/articles/           generated per-article JSON
data/report.csv          generated
site/                    the viewer (index.html, app.js, style.css)
docs/TODO.md             checklist and parked work
.github/workflows/       build.yml
```

`data/lists/example.csv` and `data/lists/travel.csv` are sample lists (normal, redirect, disambiguation, no image,
non-English, missing, bad URL, duplicate). Delete them when you add your own.

## Status

The script, sample data and viewer were tested in this repository's development session. The workflow has not yet run on
GitHub; its first run will confirm the Pages deployment.
