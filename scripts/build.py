#!/usr/bin/env python3
"""Rebuild the Bank of England RSS taxonomy, llms.txt, Word document and weekly digest.

Usage:
    python scripts/build.py                # fetch feeds, merge archive, render everything
    python scripts/build.py --offline      # re-render from data/items.json without fetching
    python scripts/build.py --date 2026-11-16

The script is idempotent: running it twice on the same day with the same feed
content produces the same files. Items are accumulated in data/items.json so the
archive grows beyond the ~50 items each RSS feed exposes.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from taxonomy import CONTENT_TYPES, THEMES, DEFAULT_THEME, classify, theme_meta  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
WEEKLY = ROOT / "weekly"
DOCS = ROOT / "docs"
BASE = "https://www.bankofengland.co.uk"
RSS_INDEX = f"{BASE}/rss"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36 (experiments-in-agents-and-data-science; +github)")
LONDON = ZoneInfo("Europe/London")
REPO_URL = "https://github.com/anorthernman-developer/experiments-in-agents-and-data-science"
BOE_TERMS = "https://www.bankofengland.co.uk/legal"


# ----------------------------------------------------------------------------- fetch
def http_get(url: str, tries: int = 3) -> bytes:
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise last  # type: ignore[misc]


def discover_feeds() -> tuple[list[dict], str | None]:
    """Scrape the /rss index page for feed links. Falls back to the known list."""
    try:
        page = http_get(RSS_INDEX).decode("utf-8", "replace")
        found = []
        for href, label in re.findall(r'<a[^>]*href="(/rss/[a-z0-9\-]+)"[^>]*>(.*?)</a>', page, re.S):
            slug = href.rsplit("/", 1)[-1]
            label = html.unescape(re.sub(r"<[^>]+>", "", label)).strip()
            if slug not in [f["slug"] for f in found]:
                found.append({"slug": slug, "label": label, "url": BASE + href})
        if found:
            return found, None
        err = "no feed links found on index page"
    except Exception as e:  # noqa: BLE001
        err = f"index fetch failed: {e}"
    return ([{"slug": s, "label": v[0], "url": f"{BASE}/rss/{s}"} for s, v in CONTENT_TYPES.items()], err)


def parse_date(s: str | None) -> str | None:
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s.strip())
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:  # noqa: BLE001
        return None


def parse_feed(xml_bytes: bytes, slug: str) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    out = []
    for it in root.iter("item"):
        cats = [c.text.strip() for c in it.findall("category") if c.text]
        title = html.unescape((it.findtext("title") or "").strip())
        link = (it.findtext("link") or "").strip()
        out.append({
            "guid": (it.findtext("guid") or link).strip().strip("{}").lower(),
            "title": title,
            "link": link,
            "description": html.unescape(re.sub(r"<[^>]+>", "", it.findtext("description") or "")).strip(),
            "published": parse_date(it.findtext("pubDate")),
            "rss_categories": cats,
            "feeds": [slug],
        })
    return out


# ----------------------------------------------------------------------------- helpers
def slugify(s: str, n: int = 70) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:n].rstrip("-") or "item"


def london(iso: str | None, fmt: str = "%d %b %Y") -> str:
    if not iso:
        return "undated"
    d = dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    return d.astimezone(LONDON).strftime(fmt)


def sort_key(it):
    return (it.get("published") or "", it["title"])


def md_escape(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")


# ----------------------------------------------------------------------------- merge
def load_archive() -> dict:
    p = DATA / "items.json"
    if p.exists():
        return {it["id"]: it for it in json.loads(p.read_text(encoding="utf-8"))["items"]}
    return {}


def merge(archive: dict, fetched: list[dict], run_date: str) -> list[str]:
    new_ids = []
    for it in fetched:
        iid = it["guid"] or slugify(it["link"])
        it["id"] = iid
        if iid in archive:
            old = archive[iid]
            for k in ("title", "link", "description", "published", "rss_categories"):
                if it.get(k):
                    old[k] = it[k]
            old["feeds"] = sorted(set(old["feeds"]) | set(it["feeds"]))
            old["last_seen"] = run_date
        else:
            it["first_seen"] = run_date
            it["last_seen"] = run_date
            archive[iid] = it
            new_ids.append(iid)
    for it in archive.values():
        it["theme"] = classify(it)
        it["content_type"] = it["feeds"][0]
    return new_ids


# ----------------------------------------------------------------------------- render: data tree
def item_path(it) -> Path:
    date = (it.get("published") or "0000-00-00")[:10]
    return DATA / it["theme"] / it["content_type"] / f"{date}-{slugify(it['title'], 60)}-{it['id'][:8]}.md"


def render_tree(items: list[dict]):
    tm = theme_meta()
    keep = set()
    for it in items:
        p = item_path(it)
        it["path"] = str(p.relative_to(ROOT))
        keep.add(p)
        ct_label = CONTENT_TYPES.get(it["content_type"], (it["content_type"],))[0]
        fm = {
            "id": it["id"], "title": it["title"], "link": it["link"], "published": it.get("published"),
            "theme": it["theme"], "content_type": it["content_type"], "feeds": it["feeds"],
            "first_seen": it["first_seen"],
        }
        body = "---\n" + "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in fm.items()) + "\n---\n\n"
        body += f"# {it['title']}\n\n"
        body += f"- **Published:** {london(it.get('published'), '%d %B %Y, %H:%M')} (UK time)\n"
        body += f"- **Theme:** {tm[it['theme']][0]}\n- **Content type:** {ct_label}\n"
        body += f"- **Source:** [{it['link']}]({it['link']})\n\n"
        if it.get("description"):
            body += f"> {it['description']}\n\n"
        body += "_Unofficial index entry generated from the public Bank of England RSS feeds._\n"
        write(p, body)
    # remove stale item files (e.g. after a re-classification)
    for p in DATA.glob("*/*/*.md"):
        if p.name != "index.md" and p not in keep:
            p.unlink()
    for d in sorted(DATA.glob("*/*"), reverse=True):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    for d in DATA.glob("*"):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()

    by_theme = defaultdict(list)
    for it in items:
        by_theme[it["theme"]].append(it)
    for theme, its in by_theme.items():
        title, desc = tm[theme]
        by_ct = defaultdict(list)
        for it in its:
            by_ct[it["content_type"]].append(it)
        lines = [f"# {title}\n", f"{desc}\n", f"**{len(its)} items** across {len(by_ct)} content types.\n"]
        for ct, cits in sorted(by_ct.items()):
            ct_label = CONTENT_TYPES.get(ct, (ct,))[0]
            lines.append(f"\n## {ct_label} ({len(cits)})\n")
            lines.append("| Date (UK) | Title | Source |\n|---|---|---|")
            for it in sorted(cits, key=sort_key, reverse=True):
                rel = Path(it["path"]).relative_to(f"data/{theme}")
                lines.append(f"| {london(it.get('published'))} | [{md_escape(it['title'])}]({rel.as_posix()}) | [boe]({it['link']}) |")
            ct_lines = [f"# {title} / {ct_label}\n", "| Date (UK) | Title | Source |\n|---|---|---|"]
            for it in sorted(cits, key=sort_key, reverse=True):
                ct_lines.append(f"| {london(it.get('published'))} | [{md_escape(it['title'])}]({Path(it['path']).name}) | [boe]({it['link']}) |")
            write(DATA / theme / ct / "index.md", "\n".join(ct_lines) + "\n")
        write(DATA / theme / "index.md", "\n".join(lines) + "\n")

    # root data index
    lines = ["# Bank of England RSS taxonomy - data index\n",
             "Folder layout: `data/<theme>/<content-type>/<date>-<slug>.md`.\n",
             "| Theme | Items | Description |\n|---|---|---|"]
    for slug, title, desc, _ in THEMES + [(DEFAULT_THEME[0], DEFAULT_THEME[1], DEFAULT_THEME[2], None)]:
        if by_theme.get(slug):
            lines.append(f"| [{title}]({slug}/index.md) | {len(by_theme[slug])} | {desc} |")
    write(DATA / "index.md", "\n".join(lines) + "\n")
    return by_theme


def write_exports(items, feeds_status, run_date):
    payload = {"generated": run_date, "source": RSS_INDEX, "count": len(items),
               "items": [{k: it[k] for k in ("id", "title", "link", "description", "published", "theme",
                                              "content_type", "feeds", "rss_categories", "first_seen",
                                              "last_seen", "path")} for it in items]}
    write(DATA / "items.json", json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    p = DATA / "items.csv"
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "published", "title", "theme", "content_type", "feeds", "link", "description",
                    "first_seen", "path"])
        for it in items:
            w.writerow([it["id"], it.get("published") or "", it["title"], it["theme"], it["content_type"],
                        ";".join(it["feeds"]), it["link"], it.get("description", ""), it["first_seen"], it["path"]])
    write(DATA / "feeds.json", json.dumps(feeds_status, indent=2, ensure_ascii=False) + "\n")


# ----------------------------------------------------------------------------- llms.txt
def render_llms(items, by_theme, feeds_status, run_date):
    tm = theme_meta()
    raw = f"https://raw.githubusercontent.com/anorthernman-developer/experiments-in-agents-and-data-science/main"
    hdr = [
        "# Bank of England RSS Taxonomy (Experiments in Agents and Data Science)\n",
        "> An unofficial, agent-maintained index of everything published through the Bank of England's public "
        "RSS feeds (news, speeches, publications, statistics, PRA publications, events, explainers and Bank "
        f"Insights), organised into a subject taxonomy and refreshed weekly. {len(items)} items; last updated "
        f"{run_date}. Not affiliated with the Bank of England; all content and links belong to the Bank.\n",
        "Each entry links to the original page on bankofengland.co.uk. Themes are assigned by transparent keyword "
        "rules (see scripts/taxonomy.py). Machine-readable data: data/items.json and data/items.csv.\n",
        "## Dataset\n",
        f"- [items.json]({raw}/data/items.json): every archived item with theme, content type, dates and link",
        f"- [items.csv]({raw}/data/items.csv): the same data as CSV",
        f"- [Latest weekly digest]({raw}/weekly/latest.md): what is new this week, grouped by theme",
        f"- [llms-full.txt]({raw}/llms-full.txt): every item with its description in one file",
        "\n## Source feeds\n",
    ]
    for f in feeds_status["feeds"]:
        hdr.append(f"- [{f['label']}]({f['url']}): {CONTENT_TYPES.get(f['slug'], ('', 'Bank of England feed'))[1]}"
                   + ("" if f["status"] == "ok" else f" (last fetch failed: {f['error']})"))
    body, full = [], []
    order = [t[0] for t in THEMES] + [DEFAULT_THEME[0]]
    for slug in order:
        its = sorted(by_theme.get(slug, []), key=sort_key, reverse=True)
        if not its:
            continue
        title, desc = tm[slug]
        body.append(f"\n## {title}\n\n{desc}\n")
        full.append(f"\n## {title}\n\n{desc}\n")
        for it in its:
            ct = CONTENT_TYPES.get(it["content_type"], (it["content_type"],))[0]
            d = it.get("description") or ct
            short = d if len(d) <= 160 else d[:157].rstrip() + "..."
            body.append(f"- [{it['title']}]({it['link']}): {london(it.get('published'))}, {ct}. {short}")
            full.append(f"### {it['title']}\n\n- URL: {it['link']}\n- Published: "
                        f"{london(it.get('published'), '%d %B %Y %H:%M')} (UK time)\n- Content type: {ct}\n"
                        f"- Feeds: {', '.join(it['feeds'])}\n\n{it.get('description') or ''}\n")
    write(ROOT / "llms.txt", "\n".join(hdr + body) + "\n\n## Optional\n\n"
          f"- [Repository]({REPO_URL}): source code, workflow and Word taxonomy document\n"
          f"- [Bank of England legal and terms]({BOE_TERMS}): terms governing the original content\n")
    write(ROOT / "llms-full.txt", "\n".join(hdr) + "\n" + "\n".join(full) + "\n")


# ----------------------------------------------------------------------------- weekly digest
def render_weekly(items, new_ids, run_date):
    tm = theme_meta()
    run = dt.date.fromisoformat(run_date)
    start = run - dt.timedelta(days=7)
    new_set = set(new_ids)

    def pub_date(it):
        return dt.date.fromisoformat(london(it.get("published"), "%Y-%m-%d")) if it.get("published") else None

    week = [it for it in items if pub_date(it) and start <= pub_date(it) <= run and it["content_type"] != "events"]
    upcoming = sorted([it for it in items if it["content_type"] == "events" and pub_date(it) and
                       run <= pub_date(it) <= run + dt.timedelta(days=28)], key=sort_key)
    # items first seen in this window (stable across same-day reruns, unlike "new this run")
    newly_archived = [it for it in items if it["id"] in new_set or start < dt.date.fromisoformat(it["first_seen"]) <= run]
    by_theme = defaultdict(list)
    for it in week:
        by_theme[it["theme"]].append(it)
    lines = [f"# Bank of England: what's new, week to {run.strftime('%A %d %B %Y')}\n",
             f"Window: {start.strftime('%d %b')} to {run.strftime('%d %b %Y')} (UK time). "
             f"{len(week)} items published in the window; {len(newly_archived)} items newly added to the archive "
             f"in the window; archive now holds {len(items)} items.\n"]
    counts = Counter(it["theme"] for it in week)
    if counts:
        lines.append("**At a glance:** " + ", ".join(f"{tm[k][0]} {v}" for k, v in counts.most_common()) + ".\n")
    order = [t[0] for t in THEMES] + [DEFAULT_THEME[0]]
    for slug in order:
        its = sorted(by_theme.get(slug, []), key=sort_key, reverse=True)
        if not its:
            continue
        lines.append(f"\n## {tm[slug][0]} ({len(its)})\n")
        for it in its:
            ct = CONTENT_TYPES.get(it["content_type"], (it["content_type"],))[0]
            lines.append(f"- **{london(it.get('published'), '%a %d %b')}**: [{it['title']}]({it['link']}) _({ct})_")
    if upcoming:
        lines.append("\n## Coming up (next four weeks)\n")
        for it in upcoming:
            lines.append(f"- **{london(it.get('published'), '%a %d %b %Y')}**: [{it['title']}]({it['link']})")
    lines.append("\n---\n_Generated automatically by `scripts/build.py` from the public Bank of England RSS feeds. "
                 "Unofficial; not affiliated with the Bank of England._\n")
    text = "\n".join(lines) + "\n"
    write(WEEKLY / f"{run_date}.md", text)
    write(WEEKLY / "latest.md", text)
    digests = sorted(p.stem for p in WEEKLY.glob("????-??-??.md"))
    write(WEEKLY / "index.md", "# Weekly digests\n\n" + "\n".join(f"- [{d}]({d}.md)" for d in reversed(digests)) + "\n")
    return week, upcoming, counts


# ----------------------------------------------------------------------------- Word document
def render_docx(items, by_theme, feeds_status, run_date, week_counts):
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor, Cm

    tm = theme_meta()
    NAVY = RGBColor(0x1A, 0x2B, 0x4C)
    doc = Document()
    for s in doc.sections:
        s.left_margin = s.right_margin = Cm(2.2)
        s.top_margin = s.bottom_margin = Cm(2.0)
    st = doc.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(10.5)
    for name in ("Heading 1", "Heading 2", "Heading 3", "Title"):
        doc.styles[name].font.color.rgb = NAVY
        doc.styles[name].font.name = "Calibri"

    def hyperlink(par, url, text):
        part = par.part
        r_id = part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
                              is_external=True)
        h = OxmlElement("w:hyperlink")
        h.set(qn("r:id"), r_id)
        r = OxmlElement("w:r")
        rpr = OxmlElement("w:rPr")
        c = OxmlElement("w:color"); c.set(qn("w:val"), "1F5FA8"); rpr.append(c)
        u = OxmlElement("w:u"); u.set(qn("w:val"), "single"); rpr.append(u)
        r.append(rpr)
        t = OxmlElement("w:t"); t.text = text; t.set(qn("xml:space"), "preserve"); r.append(t)
        h.append(r)
        par._p.append(h)

    def shade(cell, hexcol):
        tcpr = cell._tc.get_or_add_tcPr()
        sh = OxmlElement("w:shd"); sh.set(qn("w:val"), "clear"); sh.set(qn("w:color"), "auto"); sh.set(qn("w:fill"), hexcol)
        tcpr.append(sh)

    def table(headers, rows, widths=None):
        t = doc.add_table(rows=1, cols=len(headers))
        t.style = "Light Grid Accent 1"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for i, h in enumerate(headers):
            c = t.rows[0].cells[i]; c.text = ""
            run = c.paragraphs[0].add_run(h); run.bold = True; run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            shade(c, "1A2B4C")
        for row in rows:
            cells = t.add_row().cells
            for i, v in enumerate(row):
                if isinstance(v, tuple):
                    cells[i].text = ""
                    hyperlink(cells[i].paragraphs[0], v[1], v[0])
                else:
                    cells[i].text = str(v)
        if widths:
            t.autofit = False
            for i, w in enumerate(widths):
                t.columns[i].width = Cm(w)
            for row in t.rows:
                for i, w in enumerate(widths):
                    row.cells[i].width = Cm(w)
        return t

    # title page
    for _ in range(6):
        doc.add_paragraph()
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("Experiments in Agents and Data Science"); r.font.size = Pt(14); r.font.color.rgb = RGBColor(0x55, 0x66, 0x80)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("Bank of England RSS Taxonomy"); r.bold = True; r.font.size = Pt(30); r.font.color.rgb = NAVY
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("A document and folder taxonomy of the Bank's news, speeches, publications, statistics and "
                  "regulatory output, maintained weekly by an automated agent pipeline")
    r.font.size = Pt(12); r.italic = True
    doc.add_paragraph()
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run(f"Edition: {dt.date.fromisoformat(run_date).strftime('%d %B %Y')}   |   {len(items)} items   |   "
              f"{len(feeds_status['feeds'])} feeds").font.size = Pt(11)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    hyperlink(p, REPO_URL, REPO_URL)
    doc.add_paragraph()
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("Unofficial project using public Bank of England RSS data. Not affiliated with or endorsed by "
                  "the Bank of England. All content belongs to the Bank of England.")
    r.font.size = Pt(9); r.font.color.rgb = RGBColor(0x77, 0x77, 0x77)
    doc.add_page_break()

    doc.add_heading("1. Purpose", level=1)
    doc.add_paragraph(
        "The Bank of England publishes a steady stream of material: Monetary Policy Committee decisions, speeches, "
        "Prudential Regulation Authority papers, statistical releases, research and events. This document sets out a "
        "single, consistent taxonomy for that material so it can be browsed by people, queried by analysts and "
        "consumed by AI agents (through llms.txt). It is regenerated automatically every week from the Bank's "
        "public RSS feeds.")
    for b in ["Browse: a folder tree in the repository, data/<theme>/<content-type>/, one Markdown entry per item.",
              "Analyse: data/items.json and data/items.csv hold the full archive with theme, type and dates.",
              "Ask an AI: llms.txt and llms-full.txt give language models a compact, linked map of the dataset.",
              "Stay current: a weekly digest in weekly/ summarises what is new, grouped by theme."]:
        doc.add_paragraph(b, style="List Bullet")

    doc.add_heading("2. Source feeds", level=1)
    doc.add_paragraph(f"Feeds are discovered automatically from the Bank's RSS index page ({RSS_INDEX}).")
    table(["Feed", "URL", "Items", "Status"],
          [(f["label"], (f["url"], f["url"]), f.get("items", 0), f["status"] if f["status"] == "ok" else f"failed: {f['error']}")
           for f in feeds_status["feeds"]], widths=[3.6, 9.4, 1.8, 1.8])

    doc.add_heading("3. Taxonomy", level=1)
    doc.add_paragraph("Every item is classified on two facets. Content type records which feed it came from. Theme "
                      "is a subject area assigned by ordered, auditable keyword rules applied to the URL path, title "
                      "and description (scripts/taxonomy.py).")
    doc.add_heading("3.1 Theme tree", level=2)
    order = [t[0] for t in THEMES] + [DEFAULT_THEME[0]]
    for slug in order:
        its = by_theme.get(slug, [])
        p = doc.add_paragraph(style="List Bullet")
        r = p.add_run(f"{tm[slug][0]}  "); r.bold = True
        p.add_run(f"data/{slug}/  ({len(its)} items)").font.color.rgb = RGBColor(0x55, 0x66, 0x80)
        cts = Counter(it["content_type"] for it in its)
        for ct, n in sorted(cts.items()):
            doc.add_paragraph(f"{CONTENT_TYPES.get(ct, (ct,))[0]}: data/{slug}/{ct}/  ({n})", style="List Bullet 2")
    doc.add_heading("3.2 Content types", level=2)
    ct_counts = Counter(it["content_type"] for it in items)
    table(["Content type", "Description", "Items"],
          [(v[0], v[1], ct_counts.get(k, 0)) for k, v in CONTENT_TYPES.items()], widths=[4, 10.5, 2])
    doc.add_heading("3.3 Theme definitions and counts", level=2)
    table(["Theme", "Folder", "Scope", "Items", "This week"],
          [(tm[s][0], f"data/{s}/", tm[s][1], len(by_theme.get(s, [])), week_counts.get(s, 0)) for s in order],
          widths=[3.3, 3.6, 7.2, 1.3, 1.6])

    doc.add_heading("4. Latest items by theme", level=1)
    doc.add_paragraph("The ten most recent items in each theme. Titles link to the original Bank of England page.")
    for slug in order:
        its = sorted(by_theme.get(slug, []), key=sort_key, reverse=True)
        if not its:
            continue
        doc.add_heading(f"{tm[slug][0]} ({len(its)})", level=2)
        table(["Date (UK)", "Title", "Type"],
              [(london(it.get("published")), (it["title"], it["link"]), CONTENT_TYPES.get(it["content_type"], (it["content_type"],))[0])
               for it in its[:10]], widths=[2.4, 11, 3.2])

    doc.add_heading("5. How the weekly refresh works", level=1)
    for i, s in enumerate([
        "Every Monday at 07:00 UTC (07:00 UK time in winter, 08:00 in summer) a GitHub Actions workflow starts; it can also be run on demand.",
        "scripts/build.py reads the RSS index page and discovers every listed feed.",
        "Each feed is fetched and parsed; items are merged into the archive (data/items.json) by their stable GUID, so history accumulates beyond the 50 items each feed exposes.",
        "Each item is classified into a theme and content type, and the folder tree, indexes, CSV, llms.txt, llms-full.txt and this Word document are regenerated.",
        "A digest (weekly/YYYY-MM-DD.md and weekly/latest.md) lists what was published in the past seven days, grouped by theme, plus upcoming events.",
        "The workflow commits any changes back to the repository. If a feed fails, it is recorded in data/feeds.json and the rest of the build continues."], 1):
        doc.add_paragraph(s, style="List Number")
    doc.add_heading("6. Notes and terms", level=1)
    p = doc.add_paragraph("This is an unofficial experiment. It is not affiliated with, endorsed by or maintained by "
                          "the Bank of England. Item titles, descriptions and links come from the Bank's public RSS "
                          "feeds and remain the property of the Bank of England; refer to the Bank's terms at ")
    hyperlink(p, BOE_TERMS, BOE_TERMS)
    p.add_run(". Theme assignments are automatic and may be imperfect.")
    # footer
    fp = doc.sections[0].footer.paragraphs[0]
    fp.text = "Bank of England RSS Taxonomy - unofficial - Experiments in Agents and Data Science"
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fp.runs[0].font.size = Pt(8)
    # deterministic core properties
    cp = doc.core_properties
    cp.title = "Bank of England RSS Taxonomy"; cp.author = "Experiments in Agents and Data Science"
    stamp = dt.datetime.fromisoformat(run_date + "T00:00:00")
    cp.created = cp.modified = stamp; cp.last_modified_by = "build.py"; cp.revision = 1
    DOCS.mkdir(parents=True, exist_ok=True)
    out = DOCS / "BoE-Taxonomy.docx"
    doc.save(out)
    # normalise zip entry timestamps so identical content gives an identical file (idempotent commits)
    import io, zipfile
    y, m, d = (int(x) for x in run_date.split("-"))
    src = zipfile.ZipFile(out)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for info in src.infolist():
            zi = zipfile.ZipInfo(info.filename, date_time=(y, m, d, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, src.read(info.filename))
    src.close()
    out.write_bytes(buf.getvalue())


# ----------------------------------------------------------------------------- README stats
def render_readme_stats(items, by_theme, feeds_status, run_date, week):
    p = ROOT / "README.md"
    if not p.exists():
        return
    tm = theme_meta()
    ok = sum(1 for f in feeds_status["feeds"] if f["status"] == "ok")
    lines = ["<!-- STATS:START -->",
             f"**Last refresh:** {run_date} &nbsp;|&nbsp; **Feeds:** {ok}/{len(feeds_status['feeds'])} OK "
             f"&nbsp;|&nbsp; **Items archived:** {len(items)} &nbsp;|&nbsp; **Published in the last 7 days:** {len(week)} "
             "&nbsp;|&nbsp; [This week's digest](weekly/latest.md)", "",
             "| Theme | Items |", "|---|---:|"]
    for slug in [t[0] for t in THEMES] + [DEFAULT_THEME[0]]:
        if by_theme.get(slug):
            lines.append(f"| [{tm[slug][0]}](data/{slug}/index.md) | {len(by_theme[slug])} |")
    lines.append("<!-- STATS:END -->")
    text = p.read_text(encoding="utf-8")
    text = re.sub(r"<!-- STATS:START -->.*?<!-- STATS:END -->", "\n".join(lines), text, flags=re.S)
    write(p, text)


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="skip fetching; re-render from data/items.json")
    ap.add_argument("--date", default=dt.datetime.now(LONDON).date().isoformat())
    a = ap.parse_args()
    run_date = a.date
    archive = load_archive()
    feeds_status = {"index": RSS_INDEX, "run_date": run_date, "feeds": []}
    fetched = []
    if a.offline:
        prev = DATA / "feeds.json"
        if prev.exists():
            feeds_status = json.loads(prev.read_text(encoding="utf-8"))
    else:
        feeds, err = discover_feeds()
        if err:
            feeds_status["index_error"] = err
        for f in feeds:
            entry = dict(f)
            try:
                its = parse_feed(http_get(f["url"]), f["slug"])
                entry.update(status="ok", items=len(its), error=None)
                fetched.extend(its)
            except Exception as e:  # noqa: BLE001
                entry.update(status="failed", items=0, error=f"{type(e).__name__}: {e}")
            feeds_status["feeds"].append(entry)
            print(f"{f['slug']:40s} {entry['status']:6s} {entry['items']}", file=sys.stderr)
        if not fetched and not archive:
            sys.exit("No items fetched and no archive to fall back on.")
    new_ids = merge(archive, fetched, run_date)
    items = sorted(archive.values(), key=sort_key, reverse=True)
    by_theme = render_tree(items)
    write_exports(items, feeds_status, run_date)
    render_llms(items, by_theme, feeds_status, run_date)
    week, upcoming, counts = render_weekly(items, new_ids, run_date)
    render_docx(items, by_theme, feeds_status, run_date, counts)
    render_readme_stats(items, by_theme, feeds_status, run_date, week)
    print(json.dumps({"items": len(items), "new": len(new_ids), "this_week": len(week),
                      "themes": {k: len(v) for k, v in by_theme.items()}}, indent=1))


if __name__ == "__main__":
    main()
