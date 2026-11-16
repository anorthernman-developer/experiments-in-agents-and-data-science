"""Taxonomy for the Bank of England RSS dataset.

Two facets:
  * content type  - which BoE feed an item came from (news, speeches, ...)
  * theme         - a subject area, assigned by transparent keyword rules

Rules are ordered; the first theme whose keywords match the item's URL path
or title wins. Everything is deliberately simple and explainable so it can be
audited, extended, or swapped out for an LLM classifier later.
"""

CONTENT_TYPES = {
    "news": ("News", "Press releases, letters, minutes and announcements."),
    "speeches": ("Speeches", "Speeches and panels by Bank of England policymakers and staff."),
    "publications": ("Publications", "Reports, papers, surveys, working papers and weekly reports."),
    "statistics": ("Statistics", "Statistical releases such as Money and Credit and effective interest rates."),
    "prudential-regulation-publications": (
        "Prudential Regulation (PRA)",
        "PRA consultation papers, policy statements, discussion papers and digests.",
    ),
    "events": ("Events", "Conferences, workshops and Citizens' Panels hosted or attended by the Bank."),
    "knowledgebank": ("Explainers (Knowledge Bank)", "Plain-English explainers on economics and the Bank."),
    "bank-insights": ("Bank Insights", "Short analytical pieces from Bank staff."),
}

# slug, title, description, keywords (matched case-insensitively against "url-path title")
THEMES = [
    ("monetary-policy", "Monetary Policy",
     "Bank Rate, the MPC, inflation, the Monetary Policy Report, the Agents and the Asset Purchase Facility.",
     ["monetary-policy", "monetary policy", "bank rate", "mpc", "inflation", "agents-summary",
      "decision-maker-panel", "asset-purchase", "quantitative", "interest rate", "price stability",
      "cost of living", "cost-of-living", "wage", "labour market", "gilt purchase", "deflation",
      "debt", "financial conditions", "mpr briefing", " qt ", " apf", "monetary economics"]),
    ("financial-stability", "Financial Stability",
     "The FPC, systemic risk, stress testing, resolution and financial resilience.",
     ["financial-stability", "financial stability", "financial-policy-committee", "fpc", "systemic-risk",
      "stress test", "stress-test", "resolution", "macroprudential", "non-bank", "nbfi", "resilience",
      "financial system", "safer"]),
    ("prudential-regulation", "Prudential Regulation",
     "PRA rules and supervision of banks, building societies, credit unions and insurers.",
     ["prudential-regulation", "pra ", "pra-", "credit union", "credit-union", "insurer", "insurance",
      "solvency", "basel", "capital requirement", "large exposures", "regulatory digest", "pra’s", "pra's",
      "the pra", "supervision", "part viii", "regulatory", "enforcement", "banking regime", "deposit protection",
      "fscs", "what is capital", "regulate banks", "risks do banks", "competition", "islamic finance",
      "silicon valley bank", "mutual", "cp", "ps", "ss"]),
    ("technology-ai", "Technology and AI", "Artificial intelligence, cyber resilience, data and technology.",
     [" ai ", " ai:", " ai?", "-ai-", "artificial intelligence", "machine learning", "cyber", "technolog",
      "operational resilience", "data and analytics", "quantum"]),
    ("payments-digital-money", "Payments and Digital Money",
     "RTGS/CHAPS, payments innovation, digital pound, stablecoins and tokenisation.",
     ["payment", "rtgs", "chaps", "digital pound", "digital-pound", "stablecoin", "tokenis", "tokeniz",
      "meridian", "cbdc", "fintech", "wholesale-experiments", "crypto", "dlt", "digital asset",
      "future of money", "what is money", "money changed", "money depend"]),
    ("markets-operations", "Markets and Operations",
     "Sterling markets, the Bank's balance sheet, reserves, SONIA, gilts and the Weekly Report.",
     ["markets", "market operations", "sterling", "sonia", "weekly-report", "weekly report", "reserves",
      "liquidity", "balance sheet", "repo ", "repo-rate", "gilt", "foreign exchange", "fx ", "fxjsc",
      "securities lending", "money market", "market notice"]),
    ("banknotes", "Banknotes", "Banknotes, cash and the note circulation scheme.",
     ["banknote", "bank note", "cash", "polymer", "notes-in-circulation"]),
    ("climate-sustainability", "Climate and Sustainability", "Climate-related financial risk and sustainability.",
     ["climate", "sustainab", "net zero", "net-zero", "nature-related", "transition plan"]),
    ("statistics-data", "Statistics and Data", "Official statistics, surveys and data releases.",
     ["statistics", "survey", "money and credit", "effective interest", "quarterly statistics"]),
    ("research-analysis", "Research and Analysis",
     "Staff working papers, Bank Insights, technical papers and economic research.",
     ["working-paper", "staff working", "bank-insights", "research", "macro-technical", "/paper/",
      "quarterly-bulletin", "quarterly bulletin", "macroeconom", "monetary economics",
      "asset pricing", "capital flows", "econdat", "bear conference", "phd", "workshop"]),
    ("economy-society", "Economy and Society", "The wider economy, households, growth, diversity and outreach.",
     ["economy", "household", "growth", "productivity", "diversity", "inclusion", "citizens", "people in",
      "education", "schools", "brexit", "trade", "football", "housing"]),
    ("corporate-governance", "Corporate and Governance",
     "The Bank as an institution: Court, appointments, annual reports, careers and history.",
     ["court", "appointment", "appointed", "annual report", "annual-report", "governance", "museum",
      "careers", "history", "independent evaluation", "independence", "interview transcript",
      "office space", "select committee", "lords", "public accounts committee", "literature",
      "pays for the bank", "internship"]),
]
DEFAULT_THEME = ("general", "General", "Items that do not match a more specific theme.")

import re

_PRA_CODE = re.compile(r"\b(CP|PS|SS|DP)\d+/\d+\b")


def classify(item):
    """Return the theme slug for an item dict with 'link', 'title', 'description', 'feeds'."""
    path = item["link"].split("bankofengland.co.uk", 1)[-1].lower()
    text = f" {path} {item['title'].lower()} {item.get('description', '').lower()} "
    head = f" {path} {item['title'].lower()} "
    if _PRA_CODE.search(item["title"]) or "prudential-regulation-publications" in item.get("feeds", []):
        return "prudential-regulation"
    for pass_text in (head, text):
        for slug, _t, _d, kws in THEMES:
            for kw in kws:
                if kw in ("cp", "ps", "ss"):
                    continue  # handled by regex above
                if kw in pass_text:
                    return slug
    if "statistics" in item.get("feeds", []):
        return "statistics-data"
    if "bank-insights" in item.get("feeds", []):
        return "research-analysis"
    return DEFAULT_THEME[0]


def theme_meta():
    meta = {slug: (title, desc) for slug, title, desc, _ in THEMES}
    meta[DEFAULT_THEME[0]] = DEFAULT_THEME[1:]
    return meta
