# Experiments in Agents and Data Science

### Bank of England RSS taxonomy, `llms.txt` and weekly agent digests

This repository shows what an agent pipeline can do with one public dataset. Every week it reads all of the Bank of England's public RSS feeds, files each item into a subject taxonomy, and publishes the result in four forms: a browsable folder tree, a machine-readable dataset, an `llms.txt` map for AI models, and a Word document. It also writes a short "what's new this week" digest.

> **Unofficial project.** It is not affiliated with, endorsed by or maintained by the Bank of England. All titles, descriptions and links come from the Bank's public RSS feeds and remain the Bank's property. Please see the [Bank of England's legal and terms page](https://www.bankofengland.co.uk/legal). Theme labels are assigned automatically and may sometimes be wrong.

<!-- STATS:START -->
**Last refresh:** 2026-11-23 &nbsp;|&nbsp; **Feeds:** 8/8 OK &nbsp;|&nbsp; **Items archived:** 403 &nbsp;|&nbsp; **Published in the last 7 days:** 23 &nbsp;|&nbsp; [This week's digest](weekly/latest.md)

| Theme | Items |
|---|---:|
| [Monetary Policy](data/monetary-policy/index.md) | 90 |
| [Financial Stability](data/financial-stability/index.md) | 25 |
| [Prudential Regulation](data/prudential-regulation/index.md) | 88 |
| [Technology and AI](data/technology-ai/index.md) | 10 |
| [Payments and Digital Money](data/payments-digital-money/index.md) | 26 |
| [Markets and Operations](data/markets-operations/index.md) | 40 |
| [Banknotes](data/banknotes/index.md) | 8 |
| [Climate and Sustainability](data/climate-sustainability/index.md) | 3 |
| [Statistics and Data](data/statistics-data/index.md) | 30 |
| [Research and Analysis](data/research-analysis/index.md) | 42 |
| [Economy and Society](data/economy-society/index.md) | 17 |
| [Corporate and Governance](data/corporate-governance/index.md) | 15 |
| [General](data/general/index.md) | 9 |
<!-- STATS:END -->

## What's in the repo

| Path | What it is |
|---|---|
| [`llms.txt`](llms.txt) | A single [llms.txt](https://llmstxt.org) file: an H1 title, a summary, then one section per theme with a linked, one-line entry for every item. Point an LLM or agent at it to get a curated map of the Bank's output. |
| [`llms-full.txt`](llms-full.txt) | The same structure with full descriptions, dates and feed names for every item. |
| [`data/`](data/index.md) | The folder taxonomy: `data/<theme>/<content-type>/<date>-<slug>.md`, one Markdown file per item with YAML front matter, plus an `index.md` in every folder. |
| [`data/items.json`](data/items.json), [`data/items.csv`](data/items.csv) | The whole archive as a dataset: id, title, link, description, published date, theme, content type, feeds, first and last seen. |
| [`data/feeds.json`](data/feeds.json) | Which feeds were found and whether each one fetched successfully on the last run. |
| [`docs/BoE-Taxonomy.docx`](docs/BoE-Taxonomy.docx) | A Word document version of the taxonomy: purpose, source feeds, theme tree, counts, the latest ten items per theme and how the refresh works. |
| [`weekly/`](weekly/index.md) | Weekly digests (`weekly/YYYY-MM-DD.md`, plus [`weekly/latest.md`](weekly/latest.md)): items published in the past seven days grouped by theme, and events coming up. |
| [`scripts/build.py`](scripts/build.py) | The pipeline. It discovers feeds, fetches them, merges the archive, classifies items and renders every output. It is idempotent. |
| [`scripts/taxonomy.py`](scripts/taxonomy.py) | The taxonomy: content types and ordered, auditable keyword rules for themes. |
| [`automation/weekly.yml`](automation/weekly.yml) | The GitHub Actions workflow: runs every Monday at 07:00 UTC (and on demand), then commits the refreshed outputs. To switch it on, copy it to `.github/workflows/weekly.yml` (see below). |

## The dataset

The pipeline starts from the Bank's RSS index at <https://www.bankofengland.co.uk/rss> and finds every feed listed there. Today that means:

- **News**: press releases, letters, committee minutes and announcements
- **Speeches**: speeches and panels by MPC, FPC and PRA members and Bank staff
- **Publications**: reports, surveys, working papers and the Weekly Report
- **Statistics**: statistical releases (Money and Credit, effective interest rates, reserves and others)
- **Prudential regulation publications**: PRA consultation papers (CP), policy statements (PS), supervisory statements (SS), discussion papers (DP) and digests
- **Events**: conferences, workshops and Citizens' Forums
- **Explainers (Knowledge Bank)**: plain-English explainers
- **Bank Insights**: short analytical pieces by Bank staff

Each feed only shows its latest ~50 items. The pipeline merges every run into `data/items.json` by each item's stable GUID, so **the archive builds up a history week after week** that the feeds themselves don't keep.

## The taxonomy

Items are classified on two facets:

1. **Content type**: which feed the item came from (the second folder level).
2. **Theme**: a subject area (the first folder level), assigned by ordered keyword rules applied to the URL path, title and description. PRA publication codes (CP/PS/SS/DP) are always filed under Prudential Regulation.

Themes: Monetary Policy, Financial Stability, Prudential Regulation, Technology and AI, Payments and Digital Money, Markets and Operations, Banknotes, Climate and Sustainability, Statistics and Data, Research and Analysis, Economy and Society, Corporate and Governance, and General (for anything not matched).

The rules sit in one small Python file on purpose. Anyone can read why an item landed where it did, change a rule, and rerun the build. That simple approach also gives a baseline to compare an LLM classifier against (see the ideas below).

## The weekly agent pipeline

```
Monday 07:00 UTC ─▶ discover feeds from /rss ─▶ fetch and parse every feed
      ─▶ merge into the archive (dedupe by GUID, record first/last seen)
      ─▶ classify (theme × content type)
      ─▶ render: data/ tree + indexes, items.json/csv, llms.txt, llms-full.txt, BoE-Taxonomy.docx
      ─▶ write weekly/YYYY-MM-DD.md digest ─▶ commit and push
```

If one feed fails, the failure is recorded in `data/feeds.json` and the build carries on with the others. The digest is also added to the Actions job summary, so you can read each week's update straight from the run page.

### Switching on the weekly schedule

The workflow is stored at `automation/weekly.yml`. To enable it, add the same file at `.github/workflows/weekly.yml`. You can do this in the GitHub web editor, or push it with credentials that have the `workflow` scope. After that, the workflow runs every Monday and can be started by hand from the Actions tab.

### Run it yourself

```bash
pip install -r requirements.txt
python scripts/build.py              # fetch the feeds and rebuild everything
python scripts/build.py --offline    # re-render from data/items.json without fetching
```

## Showing what agents can do with this dataset

Some ideas for agents built on this repo:

- **Ask the Bank anything**: give an assistant `llms.txt` and it can answer questions like "What has the PRA said about credit unions this autumn?" with links to the original pages.
- **Personal policy briefings**: an agent reads `weekly/latest.md`, opens the linked speeches and reports, and writes a five-bullet briefing for a treasurer, a mortgage broker or a fintech founder.
- **Speech tone tracker**: score every MPC member's speeches for hawkish or dovish language over time and set the scores against Bank Rate decisions.
- **Regulatory change radar**: follow each PRA consultation paper through to its policy statement and flag implementation deadlines.
- **LLM versus rules classification**: re-label the archive with an LLM, compare it with the keyword taxonomy, and let an agent suggest rule changes as a pull request.
- **Release calendar agent**: learn the rhythm of the statistics releases (Money and Credit, Decision Maker Panel, the Weekly Report) and predict what's coming next week.
- **Topic trends**: track how often themes such as AI, stablecoins, tokenisation or climate appear in speeches and publications over the months.
- **Multi-channel publishing**: turn each weekly digest into a newsletter, a LinkedIn post or an audio briefing, with a person approving it first.

## Licence

Code is released under the [MIT licence](LICENSE). Data derived from the Bank of England's RSS feeds belongs to the Bank of England and is subject to [its terms](https://www.bankofengland.co.uk/legal).
