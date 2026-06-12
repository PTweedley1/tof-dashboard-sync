"""
Builds three tabs in the dashboard sheet:

  URL_Registry     — directory of every URL with metadata.
  Campaign_Summary — horizontal pivot: one column per concept, all sources.
  Concept_View     — interactive: pick a concept from a dropdown, see all its data.

Re-run only when campaigns.json changes (new campaign, new URLs, or new concept).
"""

from sync.sheets import get_sheets_service
from sync.config import DESTINATION_SHEET_ID
from sync import campaigns as camp

REGISTRY_TAB    = "URL_Registry"
SUMMARY_TAB     = "Campaign_Summary"
CONCEPT_VIEW_TAB = "Concept_View"


# ── helpers ──────────────────────────────────────────────────────────────────

def _ensure_tab(service, tab_name):
    """Create the tab if it doesn't exist. Returns the sheet's integer sheetId."""
    meta = service.spreadsheets().get(spreadsheetId=DESTINATION_SHEET_ID).execute()
    existing = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}
    if tab_name not in existing:
        result = service.spreadsheets().batchUpdate(
            spreadsheetId=DESTINATION_SHEET_ID,
            body={"requests": [{"addSheet": {"properties": {"title": tab_name}}}]}
        ).execute()
        return result["replies"][0]["addSheet"]["properties"]["sheetId"]
    return existing[tab_name]


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
    if not tw:
        return ""
    return f'=IFERROR(SUMIF(Meta_TripleWhale!$B:$B,"{tw}",Meta_TripleWhale!${col}:${col}),"")'


def _tw_avg(tw, col):
    if not tw:
        return ""
    return f'=IFERROR(AVERAGEIF(Meta_TripleWhale!$B:$B,"{tw}",Meta_TripleWhale!${col}:${col}),"")'


def _ga4_sum(urls, col):
    if not urls:
        return ""
    parts = [f'SUMIF(GA4_Pages!$B:$B,"{u}",GA4_Pages!${col}:${col})' for u in urls]
    return "=" + "+".join(parts)


def _ga4_avg(urls, col):
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

    last_col = chr(ord("B") + n - 1)

    def s(r):
        return f'=IFERROR(SUM(B{r}:{last_col}{r}),"")'

    def a(r):
        return f'=IFERROR(AVERAGE(B{r}:{last_col}{r}),"")'

    def pad(lst):
        row = list(lst)
        while len(row) < n + 2:
            row.append("")
        return row

    rows = [
        pad(["Campaign Summary — live formulas update automatically from GA4_Pages & Meta_TripleWhale. "
             "Re-run this script only when campaigns.json changes."]),
        pad([]),
        ["Metric"] + [c["name"] for c in concepts] + ["TOTAL / AVG"],
        ["Campaign"]    + [c["campaign"] for c in concepts] + [""],
        ["Launch Date"] + [c["launched"]  for c in concepts] + [""],
        ["Status"]      + ["Active" if c["urls"] else "Upcoming" for c in concepts] + [""],
        pad([]),
        pad(["━━  META / TRIPLE WHALE  ━━"]),
        ["TW Campaign Name"] + [c["tw"] or "TBD" for c in concepts] + [""],
        ["Total Spend ($)"]       + [_tw_sum(c["tw"], "C") for c in concepts] + [s(10)],
        ["Avg ROAS"]              + [_tw_avg(c["tw"], "H") for c in concepts] + [a(11)],
        ["Total New Customers"]   + [_tw_sum(c["tw"], "I") for c in concepts] + [s(12)],
        pad([]),
        pad(["━━  GA4 PAGES  ━━"]),
        ["Sessions"]             + [_ga4_sum(c["urls"], "C") for c in concepts] + [s(15)],
        ["Active Users"]         + [_ga4_sum(c["urls"], "D") for c in concepts] + [s(16)],
        ["New Users"]            + [_ga4_sum(c["urls"], "E") for c in concepts] + [s(17)],
        ["Conversions"]          + [_ga4_sum(c["urls"], "I") for c in concepts] + [s(18)],
        ["Revenue ($)"]          + [_ga4_sum(c["urls"], "J") for c in concepts] + [s(19)],
        ["Avg Engagement Rate"]  + [_ga4_avg(c["urls"], "F") for c in concepts] + [a(20)],
        ["Avg Bounce Rate"]      + [_ga4_avg(c["urls"], "H") for c in concepts] + [a(21)],
        pad([]),
        pad(["━━  JUSTUNO  (consolidated TOF-wide — not yet split by concept)  ━━"]),
        ["Impressions"]           + ['=IFERROR(Justuno!D6,"")'] + ["—"] * (n - 1) + ['=IFERROR(Justuno!D6,"")'],
        ["Email Opt-Ins"]         + ['=IFERROR(Justuno!E6,"")'] + ["—"] * (n - 1) + ['=IFERROR(Justuno!E6,"")'],
        ["SMS Opt-Ins"]           + ['=IFERROR(Justuno!F6,"")'] + ["—"] * (n - 1) + ['=IFERROR(Justuno!F6,"")'],
        ["Opt-In Rate"]           + ['=IFERROR(Justuno!G6,"")'] + ["—"] * (n - 1) + ['=IFERROR(Justuno!G6,"")'],
        ["Influenced Revenue ($)"]+ ['=IFERROR(Justuno!H6,"")'] + ["—"] * (n - 1) + ['=IFERROR(Justuno!H6,"")'],
    ]

    return rows


# ── Concept_View ──────────────────────────────────────────────────────────────

def _concept_view_rows(first_concept_name):
    """
    Build rows for the Concept_View tab.
    B1 = dropdown selector (set via data validation separately).
    All value cells use INDEX/MATCH to pull the matching column from Campaign_Summary.
    """

    def val(cs_row):
        # Look up B1's value in Campaign_Summary header row 3, return that column's value
        return (
            f'=IFERROR(INDEX(Campaign_Summary!$B${cs_row}:$Z${cs_row},'
            f'MATCH($B$1,Campaign_Summary!$B$3:$Z$3,0)),"—")'
        )

    rows = [
        # Row 1 — selector
        ["Selected Concept →", first_concept_name],
        [],
        # Row 3 — concept metadata
        ["Campaign",    f'=IFERROR(INDEX(Campaign_Summary!$B$4:$Z$4,MATCH($B$1,Campaign_Summary!$B$3:$Z$3,0)),"—")'],
        ["Launch Date", f'=IFERROR(INDEX(Campaign_Summary!$B$5:$Z$5,MATCH($B$1,Campaign_Summary!$B$3:$Z$3,0)),"—")'],
        ["Status",      f'=IFERROR(INDEX(Campaign_Summary!$B$6:$Z$6,MATCH($B$1,Campaign_Summary!$B$3:$Z$3,0)),"—")'],
        ["TW Campaign", f'=IFERROR(INDEX(Campaign_Summary!$B$9:$Z$9,MATCH($B$1,Campaign_Summary!$B$3:$Z$3,0)),"—")'],
        [],
        # Row 8 — TW metrics
        ["━━  META / TRIPLE WHALE  ━━", ""],
        ["Total Spend ($)",    val(10)],
        ["Avg ROAS",           val(11)],
        ["Total New Customers",val(12)],
        [],
        # Row 13 — GA4 metrics
        ["━━  GA4 PAGES  ━━", ""],
        ["Sessions",            val(15)],
        ["Active Users",        val(16)],
        ["New Users",           val(17)],
        ["Conversions",         val(18)],
        ["Revenue ($)",         val(19)],
        ["Avg Engagement Rate", val(20)],
        ["Avg Bounce Rate",     val(21)],
        [],
        # Row 22 — Justuno (consolidated, not per-concept)
        ["━━  JUSTUNO  (TOF-wide total — not split by concept)  ━━", ""],
        ["Impressions",            '=IFERROR(Justuno!D6,"—")'],
        ["Email Opt-Ins",          '=IFERROR(Justuno!E6,"—")'],
        ["SMS Opt-Ins",            '=IFERROR(Justuno!F6,"—")'],
        ["Opt-In Rate",            '=IFERROR(Justuno!G6,"—")'],
        ["Influenced Revenue ($)", '=IFERROR(Justuno!H6,"—")'],
    ]
    return rows


def _set_dropdown(service, sheet_id, concept_names):
    """Set B1 in Concept_View to a dropdown restricted to concept names."""
    service.spreadsheets().batchUpdate(
        spreadsheetId=DESTINATION_SHEET_ID,
        body={"requests": [{
            "setDataValidation": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 1,  # column B
                    "endColumnIndex": 2,
                },
                "rule": {
                    "condition": {
                        "type": "ONE_OF_LIST",
                        "values": [{"userEnteredValue": n} for n in concept_names],
                    },
                    "showCustomUi": True,
                    "strict": True,
                },
            }
        }]}
    ).execute()


# ── main ──────────────────────────────────────────────────────────────────────

def sync():
    print("Building URL_Registry, Campaign_Summary, and Concept_View...")
    service  = get_sheets_service()
    campaigns = camp.load()

    # Flatten concept list for use across tabs
    concepts = [
        concept
        for c in campaigns
        for concept in c.get("concepts", [])
    ]
    concept_names = [c["name"] for c in concepts]

    # URL_Registry
    _ensure_tab(service, REGISTRY_TAB)
    _clear_write(service, REGISTRY_TAB, _registry_rows(campaigns))
    url_count = sum(max(len(c.get("urls", [])), 1) for c in concepts)
    print(f"  URL_Registry: {url_count} row(s)")

    # Campaign_Summary
    _ensure_tab(service, SUMMARY_TAB)
    _clear_write(service, SUMMARY_TAB, _summary_rows(campaigns))
    print(f"  Campaign_Summary: {len(concepts)} concept column(s)")

    # Concept_View
    first_name = concept_names[0] if concept_names else ""
    cv_sheet_id = _ensure_tab(service, CONCEPT_VIEW_TAB)
    _clear_write(service, CONCEPT_VIEW_TAB, _concept_view_rows(first_name))
    if concept_names:
        _set_dropdown(service, cv_sheet_id, concept_names)
    print(f"  Concept_View: dropdown set to {concept_names}")

    print("  Note: re-run only when campaigns.json changes.")
