"""
Builds two tabs in the dashboard sheet:

  URL_Registry     — directory of every URL with metadata.
                     Adding a new campaign = add rows here + update campaigns.json.

  Campaign_Summary — horizontal pivot: one column per concept, rows = metrics.
                     All sources (TW, GA4, Justuno) at the same campaign-concept level.
                     Updates live via SUMIF/AVERAGEIF formulas.

Re-run only when campaigns.json changes (new campaign, new URLs, or new concept).
"""

from sync.sheets import get_sheets_service
from sync.config import DESTINATION_SHEET_ID
from sync import campaigns as camp

REGISTRY_TAB = "URL_Registry"
SUMMARY_TAB = "Campaign_Summary"


# ── helpers ──────────────────────────────────────────────────────────────────

def _ensure_tab(service, tab_name):
    meta = service.spreadsheets().get(spreadsheetId=DESTINATION_SHEET_ID).execute()
    existing = [s["properties"]["title"] for s in meta["sheets"]]
    if tab_name not in existing:
        service.spreadsheets().batchUpdate(
            spreadsheetId=DESTINATION_SHEET_ID,
            body={"requests": [{"addSheet": {"properties": {"title": tab_name}}}]}
        ).execute()


def _clear_write(service, tab_name, rows):
    service.spreadsheets().values().clear(
        spreadsheetId=DESTINATION_SHEET_ID, range=f"{tab_name}!A:Z"
    ).execute()
    service.spreadsheets().values().update(
        spreadsheetId=DESTINATION_SHEET_ID,
        range=f"{tab_name}!A1",
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()


def _tw_sum(tw, col):
    """SUMIF for a TW campaign name (string). Returns empty string if no name."""
    if not tw:
        return ""
    return f'=IFERROR(SUMIF(Meta_TripleWhale!$B:$B,"{tw}",Meta_TripleWhale!${col}:${col}),"")'


def _tw_avg(tw, col):
    if not tw:
        return ""
    return f'=IFERROR(AVERAGEIF(Meta_TripleWhale!$B:$B,"{tw}",Meta_TripleWhale!${col}:${col}),"")'


def _ga4_sum(urls, col):
    """Sum a GA4 column across all URLs belonging to this concept."""
    if not urls:
        return ""
    parts = [f'SUMIF(GA4_Pages!$B:$B,"{u}",GA4_Pages!${col}:${col})' for u in urls]
    return "=" + "+".join(parts)


def _ga4_avg(urls, col):
    """Unweighted average of a GA4 column across URLs in this concept."""
    if not urls:
        return ""
    parts = [f'AVERAGEIF(GA4_Pages!$B:$B,"{u}",GA4_Pages!${col}:${col})' for u in urls]
    return f'=IFERROR(AVERAGE({",".join(parts)}),"—")'


# ── URL_Registry ──────────────────────────────────────────────────────────────

def _registry_rows(campaigns):
    rows = [
        ["URL Registry — one row per URL. "
         "To add a new campaign: add rows here + add urls/concepts to campaigns.json."],
        [],
        ["URL ID", "Slug", "Concept", "TW Campaign", "Campaign", "Launch Date", "Status", "Notes"],
    ]
    for c in campaigns:
        for concept in c.get("concepts", []):
            urls = concept.get("urls", [])
            if urls:
                for url in urls:
                    slug_id = url.split("/")[-1].upper()
                    rows.append([
                        slug_id, url, concept["name"],
                        concept.get("tw_campaign", ""),
                        c["name"], c.get("launched", ""), "Active", "",
                    ])
            else:
                rows.append([
                    "TBD", "— add URLs before launch —", concept["name"],
                    concept.get("tw_campaign", ""),
                    c["name"], c.get("launched", ""), "Upcoming",
                    "Add URLs to campaigns.json to activate tracking",
                ])
    return rows


# ── Campaign_Summary ──────────────────────────────────────────────────────────

def _summary_rows(campaigns):
    # Flatten concepts across all campaigns in order
    concepts = []
    for c in campaigns:
        for concept in c.get("concepts", []):
            concepts.append({
                "name":     concept["name"],
                "tw":       concept.get("tw_campaign", ""),
                "urls":     concept.get("urls", []),
                "campaign": c["name"],
                "launched": c.get("launched", ""),
            })

    n = len(concepts)
    if n == 0:
        return [["No concepts configured in campaigns.json"]]

    last_col = chr(ord("B") + n - 1)   # last concept column letter

    def s(r):   # SUM across concept columns for row r
        return f'=IFERROR(SUM(B{r}:{last_col}{r}),"")'

    def a(r):   # AVERAGE across concept columns for row r
        return f'=IFERROR(AVERAGE(B{r}:{last_col}{r}),"")'

    def pad(lst):
        row = list(lst)
        while len(row) < n + 2:
            row.append("")
        return row

    # GA4 column map (matches COL_HEADERS order in ga4.py)
    # A=Date, B=URL, C=Sessions, D=Active Users, E=New Users,
    # F=Engagement Rate, G=Avg Eng Time, H=Bounce Rate, I=Conversions, J=Revenue

    rows = [
        pad(["Campaign Summary — live formulas update automatically from GA4_Pages & Meta_TripleWhale."
             "  Re-run this script only when campaigns.json changes."]),
        pad([]),
        # Row 3 — concept headers
        ["Metric"] + [c["name"] for c in concepts] + ["TOTAL / AVG"],
        # Row 4-6 — metadata
        ["Campaign"]    + [c["campaign"] for c in concepts] + [""],
        ["Launch Date"] + [c["launched"]  for c in concepts] + [""],
        ["Status"]      + ["Active" if c["urls"] else "Upcoming" for c in concepts] + [""],
        pad([]),
        # Row 8 — META / TW section
        pad(["━━  META / TRIPLE WHALE  ━━"]),
        ["TW Campaign Name"] + [c["tw"] or "TBD" for c in concepts] + [""],
        # Row 10
        ["Total Spend ($)"]      + [_tw_sum(c["tw"], "C") for c in concepts] + [s(10)],
        ["Avg ROAS"]              + [_tw_avg(c["tw"], "H") for c in concepts] + [a(11)],
        ["Total New Customers"]   + [_tw_sum(c["tw"], "I") for c in concepts] + [s(12)],
        pad([]),
        # Row 14 — GA4 section
        pad(["━━  GA4 PAGES  ━━"]),
        ["Sessions"]             + [_ga4_sum(c["urls"], "C") for c in concepts] + [s(15)],
        ["Active Users"]         + [_ga4_sum(c["urls"], "D") for c in concepts] + [s(16)],
        ["New Users"]            + [_ga4_sum(c["urls"], "E") for c in concepts] + [s(17)],
        ["Conversions"]          + [_ga4_sum(c["urls"], "I") for c in concepts] + [s(18)],
        ["Revenue ($)"]          + [_ga4_sum(c["urls"], "J") for c in concepts] + [s(19)],
        ["Avg Engagement Rate"]  + [_ga4_avg(c["urls"], "F") for c in concepts] + [a(20)],
        ["Avg Bounce Rate"]      + [_ga4_avg(c["urls"], "H") for c in concepts] + [a(21)],
        pad([]),
        # Row 23 — Justuno section (consolidated — not per concept)
        pad(["━━  JUSTUNO  (consolidated TOF-wide — not yet split by concept)  ━━"]),
        ["Impressions"]          + ['=IFERROR(Justuno!D6,"")'] + ["—"] * (n - 1) + ['=IFERROR(Justuno!D6,"")'],
        ["Email Opt-Ins"]        + ['=IFERROR(Justuno!E6,"")'] + ["—"] * (n - 1) + ['=IFERROR(Justuno!E6,"")'],
        ["SMS Opt-Ins"]          + ['=IFERROR(Justuno!F6,"")'] + ["—"] * (n - 1) + ['=IFERROR(Justuno!F6,"")'],
        ["Opt-In Rate"]          + ['=IFERROR(Justuno!G6,"")'] + ["—"] * (n - 1) + ['=IFERROR(Justuno!G6,"")'],
        ["Influenced Revenue ($)"]+ ['=IFERROR(Justuno!H6,"")'] + ["—"] * (n - 1) + ['=IFERROR(Justuno!H6,"")'],
    ]

    return rows


# ── main ──────────────────────────────────────────────────────────────────────

def sync():
    print("Building URL_Registry and Campaign_Summary...")
    service = get_sheets_service()
    campaigns = camp.load()

    # URL_Registry
    _ensure_tab(service, REGISTRY_TAB)
    _clear_write(service, REGISTRY_TAB, _registry_rows(campaigns))
    url_count = sum(
        max(len(c.get("urls", [])), 1)
        for camp_obj in campaigns
        for c in camp_obj.get("concepts", [])
    )
    print(f"  URL_Registry: {url_count} row(s)")

    # Campaign_Summary
    _ensure_tab(service, SUMMARY_TAB)
    _clear_write(service, SUMMARY_TAB, _summary_rows(campaigns))
    concept_count = sum(len(c.get("concepts", [])) for c in campaigns)
    print(f"  Campaign_Summary: {concept_count} concept column(s)")

    print("  Note: re-run only when campaigns.json changes.")
