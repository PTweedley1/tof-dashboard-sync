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

REGISTRY_TAB     = "URL_Registry"
SUMMARY_TAB      = "Campaign_Summary"
CONCEPT_VIEW_TAB = "Concept_View"

# ── color palette ─────────────────────────────────────────────────────────────

def _rgb(hex_str):
    """Convert '#RRGGBB' to Sheets API color dict."""
    h = hex_str.lstrip("#")
    return {
        "red":   int(h[0:2], 16) / 255,
        "green": int(h[2:4], 16) / 255,
        "blue":  int(h[4:6], 16) / 255,
    }

C_DARK      = _rgb("2D3047")   # section header bg (dark navy)
C_SELECTOR  = _rgb("4472C4")   # B1 selector bg (blue)
C_META      = _rgb("EEF2F8")   # metadata rows bg (light blue-gray)
C_ALT       = _rgb("F7F8FA")   # alternating metric row bg
C_WHITE     = _rgb("FFFFFF")
C_TEXT_DARK = _rgb("1A1A2E")   # body text
C_BORDER    = _rgb("CDD5E0")   # subtle border


# ── helpers ──────────────────────────────────────────────────────────────────

def _ensure_tab(service, tab_name):
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
        pad(["Campaign Summary — live formulas. Re-run script only when campaigns.json changes."]),
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


# ── Concept_View rows ─────────────────────────────────────────────────────────

def _concept_view_rows(first_concept_name):
    """
    Layout (1-indexed sheet rows → 0-indexed API rows):
      Row 1  (idx 0):  selector
      Row 2  (idx 1):  blank
      Row 3  (idx 2):  Campaign
      Row 4  (idx 3):  Launch Date
      Row 5  (idx 4):  Status
      Row 6  (idx 5):  TW Campaign
      Row 7  (idx 6):  blank
      Row 8  (idx 7):  ── META / TW ──
      Row 9  (idx 8):  Total Spend
      Row 10 (idx 9):  Avg ROAS
      Row 11 (idx 10): Total New Customers
      Row 12 (idx 11): blank
      Row 13 (idx 12): ── GA4 ──
      Row 14 (idx 13): Sessions
      Row 15 (idx 14): Active Users
      Row 16 (idx 15): New Users
      Row 17 (idx 16): Conversions
      Row 18 (idx 17): Revenue
      Row 19 (idx 18): Avg Engagement Rate
      Row 20 (idx 19): Avg Bounce Rate
      Row 21 (idx 20): blank
      Row 22 (idx 21): ── JUSTUNO ──
      Row 23 (idx 22): Impressions
      Row 24 (idx 23): Email Opt-Ins
      Row 25 (idx 24): SMS Opt-Ins
      Row 26 (idx 25): Opt-In Rate
      Row 27 (idx 26): Influenced Revenue
    """

    def val(cs_row):
        return (
            f"=IFERROR(INDEX(Campaign_Summary!$B${cs_row}:$Z${cs_row},"
            f"MATCH($B$1,Campaign_Summary!$B$3:$Z$3,0)),\"—\")"
        )

    def date_val(cs_row):
        # Wrap in TEXT() so the date serial renders as a human-readable string
        return (
            f'=IFERROR(TEXT(INDEX(Campaign_Summary!$B${cs_row}:$Z${cs_row},'
            f'MATCH($B$1,Campaign_Summary!$B$3:$Z$3,0)),"MMM D, YYYY"),"—")'
        )

    return [
        ["Selected Concept  →", first_concept_name],           # idx 0
        [],                                                     # idx 1
        ["Campaign",    val(4)],                                # idx 2
        ["Launch Date", date_val(5)],                          # idx 3  ← TEXT() fixes serial
        ["Status",      val(6)],                                # idx 4
        ["TW Campaign", val(9)],                                # idx 5
        [],                                                     # idx 6
        ["META / TRIPLE WHALE", ""],                            # idx 7  section header
        ["Total Spend ($)",     val(10)],                       # idx 8
        ["Avg ROAS",            val(11)],                       # idx 9
        ["Total New Customers", val(12)],                       # idx 10
        [],                                                     # idx 11
        ["GA4 PAGES", ""],                                      # idx 12 section header
        ["Sessions",            val(15)],                       # idx 13
        ["Active Users",        val(16)],                       # idx 14
        ["New Users",           val(17)],                       # idx 15
        ["Conversions",         val(18)],                       # idx 16
        ["Revenue ($)",         val(19)],                       # idx 17
        ["Avg Engagement Rate", val(20)],                       # idx 18
        ["Avg Bounce Rate",     val(21)],                       # idx 19
        [],                                                     # idx 20
        ["JUSTUNO  (TOF-wide total)", ""],                      # idx 21 section header
        ["Impressions",            '=IFERROR(Justuno!D6,"—")'], # idx 22
        ["Email Opt-Ins",          '=IFERROR(Justuno!E6,"—")'], # idx 23
        ["SMS Opt-Ins",            '=IFERROR(Justuno!F6,"—")'], # idx 24
        ["Opt-In Rate",            '=IFERROR(Justuno!G6,"—")'], # idx 25
        ["Influenced Revenue ($)", '=IFERROR(Justuno!H6,"—")'], # idx 26
    ]


# ── Concept_View formatting ───────────────────────────────────────────────────

def _format_concept_view(service, sheet_id):
    """Apply visual formatting to the Concept_View tab in a single batchUpdate call."""

    def rng(r0, r1, c0=0, c1=2):
        return {"sheetId": sheet_id,
                "startRowIndex": r0, "endRowIndex": r1,
                "startColumnIndex": c0, "endColumnIndex": c1}

    def fill(r0, r1, c0, c1, bg, fg=None, bold=False, font_size=None, h_align=None):
        fmt = {"backgroundColor": bg}
        tf = {"bold": bold, "foregroundColor": fg or C_TEXT_DARK}
        if font_size:
            tf["fontSize"] = font_size
        fmt["textFormat"] = tf
        if h_align:
            fmt["horizontalAlignment"] = h_align
        fields = "userEnteredFormat(backgroundColor,textFormat"
        if h_align:
            fields += ",horizontalAlignment"
        fields += ")"
        return {"repeatCell": {"range": rng(r0, r1, c0, c1),
                               "cell": {"userEnteredFormat": fmt},
                               "fields": fields}}

    def num_fmt(row_idx, pattern):
        return {"repeatCell": {
            "range": rng(row_idx, row_idx + 1, 1, 2),
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": pattern}}},
            "fields": "userEnteredFormat.numberFormat",
        }}

    requests = []

    # ── column widths ─────────────────────────────────────────────────────────
    requests.append({"updateDimensionProperties": {
        "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
        "properties": {"pixelSize": 260}, "fields": "pixelSize",
    }})
    requests.append({"updateDimensionProperties": {
        "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2},
        "properties": {"pixelSize": 200}, "fields": "pixelSize",
    }})

    # ── row 1 height ──────────────────────────────────────────────────────────
    requests.append({"updateDimensionProperties": {
        "range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
        "properties": {"pixelSize": 44}, "fields": "pixelSize",
    }})

    # ── freeze row 1 ─────────────────────────────────────────────────────────
    requests.append({"updateSheetProperties": {
        "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
        "fields": "gridProperties.frozenRowCount",
    }})

    # ── row 1: selector ───────────────────────────────────────────────────────
    # A1: dark label
    requests.append(fill(0, 1, 0, 1, C_DARK, C_WHITE, bold=True, font_size=12))
    # B1: blue selector cell
    requests.append(fill(0, 1, 1, 2, C_SELECTOR, C_WHITE, bold=True, font_size=12))

    # ── metadata rows 3-6 (idx 2-5) ──────────────────────────────────────────
    requests.append(fill(2, 6, 0, 2, C_META))
    requests.append(fill(2, 6, 0, 1, C_META, bold=True))  # bold labels

    # ── section headers: idx 7, 12, 21 ───────────────────────────────────────
    for i in [7, 12, 21]:
        requests.append(fill(i, i + 1, 0, 2, C_DARK, C_WHITE, bold=True))

    # ── metric rows: alternating white / light gray ───────────────────────────
    metric_rows = [8, 9, 10, 13, 14, 15, 16, 17, 18, 19, 22, 23, 24, 25, 26]
    for j, idx in enumerate(metric_rows):
        bg = C_ALT if j % 2 == 0 else C_WHITE
        requests.append(fill(idx, idx + 1, 0, 1, bg, bold=True))            # label bold
        requests.append(fill(idx, idx + 1, 1, 2, bg, h_align="RIGHT"))      # value right-aligned

    # ── number formats ────────────────────────────────────────────────────────
    number_fmts = [
        (8,  '$#,##0.00'),   # Total Spend
        (9,  '0.00"x"'),     # Avg ROAS
        (10, '#,##0'),       # Total New Customers
        (13, '#,##0'),       # Sessions
        (14, '#,##0'),       # Active Users
        (15, '#,##0'),       # New Users
        (16, '#,##0'),       # Conversions
        (17, '$#,##0.00'),   # Revenue
        (18, '0.0%'),        # Avg Engagement Rate
        (19, '0.0%'),        # Avg Bounce Rate
        (22, '#,##0'),       # Impressions
        (23, '#,##0'),       # Email Opt-Ins
        (24, '#,##0'),       # SMS Opt-Ins
    ]
    for row_idx, pattern in number_fmts:
        requests.append(num_fmt(row_idx, pattern))

    service.spreadsheets().batchUpdate(
        spreadsheetId=DESTINATION_SHEET_ID,
        body={"requests": requests},
    ).execute()


# ── dropdown ──────────────────────────────────────────────────────────────────

def _set_dropdown(service, sheet_id, concept_names):
    service.spreadsheets().batchUpdate(
        spreadsheetId=DESTINATION_SHEET_ID,
        body={"requests": [{
            "setDataValidation": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0, "endRowIndex": 1,
                    "startColumnIndex": 1, "endColumnIndex": 2,
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
    service   = get_sheets_service()
    campaigns = camp.load()

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
    _format_concept_view(service, cv_sheet_id)
    print(f"  Concept_View: {len(concept_names)} concepts in dropdown, formatting applied")

    print("  Note: re-run only when campaigns.json changes.")
