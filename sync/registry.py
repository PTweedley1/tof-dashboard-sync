"""
Builds four tabs in the dashboard sheet:

  URL_Registry     — directory of every URL with metadata.
  Campaign_Summary — horizontal pivot: one column per concept, all sources.
  Concept_View     — interactive: pick a concept from a dropdown, see all its data.
  Shopify_Orders   — paste-in tab: Discount Code | Orders | Revenue ($).
                     Headers written once; user data never overwritten.

Re-run only when campaigns.json changes (new campaign, new URLs, or new concept).
"""

from sync.sheets import get_sheets_service
from sync.config import DESTINATION_SHEET_ID
from sync import campaigns as camp

REGISTRY_TAB      = "URL_Registry"
SUMMARY_TAB       = "Campaign_Summary"
CONCEPT_VIEW_TAB  = "Concept_View"
SHOPIFY_TAB       = "Shopify_Orders"

# ── color palette ─────────────────────────────────────────────────────────────

def _rgb(hex_str):
    h = hex_str.lstrip("#")
    return {"red": int(h[0:2],16)/255, "green": int(h[2:4],16)/255, "blue": int(h[4:6],16)/255}

C_DARK     = _rgb("2D3047")
C_SELECTOR = _rgb("4472C4")
C_META     = _rgb("EEF2F8")
C_ALT      = _rgb("F7F8FA")
C_WHITE    = _rgb("FFFFFF")
C_TEXT     = _rgb("1A1A2E")


# ── helpers ───────────────────────────────────────────────────────────────────

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


def _shopify_orders(codes):
    """Total orders across all discount codes for this campaign."""
    if not codes:
        return ""
    parts = [f'SUMIF({SHOPIFY_TAB}!$A:$A,"{c}",{SHOPIFY_TAB}!$B:$B)' for c in codes]
    return "=" + "+".join(parts)


def _shopify_revenue(codes):
    """Total revenue across all discount codes for this campaign."""
    if not codes:
        return ""
    parts = [f'SUMIF({SHOPIFY_TAB}!$A:$A,"{c}",{SHOPIFY_TAB}!$C:$C)' for c in codes]
    return "=" + "+".join(parts)


def _shopify_aov(codes):
    """AOV = total revenue / total orders across all discount codes."""
    if not codes:
        return ""
    rev = "+".join([f'SUMIF({SHOPIFY_TAB}!$A:$A,"{c}",{SHOPIFY_TAB}!$C:$C)' for c in codes])
    ord_ = "+".join([f'SUMIF({SHOPIFY_TAB}!$A:$A,"{c}",{SHOPIFY_TAB}!$B:$B)' for c in codes])
    return f'=IFERROR(({rev})/({ord_}),"—")'


def _shopify_total(all_codes, fn):
    """Deduplicated total across all campaigns — avoids double-counting."""
    unique = list(dict.fromkeys(all_codes))
    return fn(unique) if unique else ""


# ── URL_Registry ──────────────────────────────────────────────────────────────

def _registry_rows(campaigns):
    rows = [
        ["URL Registry — one row per URL. "
         "To add a campaign: add rows here + add urls/concepts to campaigns.json."],
        [],
        ["URL ID", "Slug", "Concept", "TW Campaign", "Campaign", "Launch Date", "Status", "Notes"],
    ]
    for c in campaigns:
        for concept in c.get("concepts", []):
            urls = concept.get("urls", [])
            if urls:
                for url in urls:
                    rows.append([
                        url.split("/")[-1].upper(), url, concept["name"],
                        concept.get("tw_campaign", ""), c["name"],
                        c.get("launched", ""), "Active", "",
                    ])
            else:
                rows.append([
                    "TBD", "— add URLs before launch —", concept["name"],
                    concept.get("tw_campaign", ""), c["name"],
                    c.get("launched", ""), "Upcoming",
                    "Add URLs to campaigns.json to activate tracking",
                ])
    return rows


# ── Campaign_Summary ──────────────────────────────────────────────────────────
#
# Row map (1-indexed — Concept_View val() references these):
#   3  headers       9  TW Campaign Name   15 Sessions        21 Avg Bounce Rate
#   4  Campaign      10 Total Spend        16 Active Users     22 blank
#   5  Launch Date   11 Avg ROAS           17 New Users        23 Justuno header
#   6  Status        12 New Customers      18 Conversions      24 Impressions
#   7  blank         13 blank              19 Revenue          25 Email Opt-Ins
#   8  TW header     14 GA4 header         20 Avg Eng Rate     26 SMS Opt-Ins
#                                                              27 Opt-In Rate
#                                                              28 Influenced Rev
#                                                              29 blank
#                                                              30 Shopify header
#                                                              31 Orders
#                                                              32 Revenue
#                                                              33 AOV

def _summary_rows(campaigns):
    concepts = []
    for c in campaigns:
        for concept in c.get("concepts", []):
            concepts.append({
                "name":           concept["name"],
                "tw":             concept.get("tw_campaign", ""),
                "urls":           concept.get("urls", []),
                "campaign":       c["name"],
                "launched":       c.get("launched", ""),
                "discount_codes": c.get("discount_codes", []),
            })

    n = len(concepts)
    if n == 0:
        return [["No concepts configured in campaigns.json"]]

    last_col = chr(ord("B") + n - 1)
    all_codes = list(dict.fromkeys(
        code for c in concepts for code in c["discount_codes"]
    ))

    def s(r):
        return f'=IFERROR(SUM(B{r}:{last_col}{r}),"")'

    def a(r):
        return f'=IFERROR(AVERAGE(B{r}:{last_col}{r}),"")'

    def pad(lst):
        row = list(lst)
        while len(row) < n + 2:
            row.append("")
        return row

    return [
        pad(["Campaign Summary — live formulas. Re-run script only when campaigns.json changes."]),
        pad([]),
        ["Metric"] + [c["name"] for c in concepts] + ["TOTAL / AVG"],          # row 3
        ["Campaign"]    + [c["campaign"] for c in concepts] + [""],             # row 4
        ["Launch Date"] + [c["launched"]  for c in concepts] + [""],            # row 5
        ["Status"]      + ["Active" if c["urls"] else "Upcoming" for c in concepts] + [""],  # row 6
        pad([]),                                                                 # row 7
        pad(["━━  META / TRIPLE WHALE  ━━"]),                                   # row 8
        ["TW Campaign Name"] + [c["tw"] or "TBD" for c in concepts] + [""],    # row 9
        ["Total Spend ($)"]     + [_tw_sum(c["tw"],"C") for c in concepts] + [s(10)],  # row 10
        ["Avg ROAS"]            + [_tw_avg(c["tw"],"H") for c in concepts] + [a(11)],  # row 11
        ["Total New Customers"] + [_tw_sum(c["tw"],"I") for c in concepts] + [s(12)],  # row 12
        pad([]),                                                                 # row 13
        pad(["━━  GA4 PAGES  ━━"]),                                             # row 14
        ["Sessions"]            + [_ga4_sum(c["urls"],"C") for c in concepts] + [s(15)],  # row 15
        ["Active Users"]        + [_ga4_sum(c["urls"],"D") for c in concepts] + [s(16)],  # row 16
        ["New Users"]           + [_ga4_sum(c["urls"],"E") for c in concepts] + [s(17)],  # row 17
        ["Conversions"]         + [_ga4_sum(c["urls"],"I") for c in concepts] + [s(18)],  # row 18
        ["Revenue ($)"]         + [_ga4_sum(c["urls"],"J") for c in concepts] + [s(19)],  # row 19
        ["Avg Engagement Rate"] + [_ga4_avg(c["urls"],"F") for c in concepts] + [a(20)],  # row 20
        ["Avg Bounce Rate"]     + [_ga4_avg(c["urls"],"H") for c in concepts] + [a(21)],  # row 21
        pad([]),                                                                 # row 22
        pad(["━━  JUSTUNO  (consolidated TOF-wide)  ━━"]),                      # row 23
        ["Impressions"]            + ['=IFERROR(Justuno!D6,"")'] + ["—"]*(n-1) + ['=IFERROR(Justuno!D6,"")'],  # row 24
        ["Email Opt-Ins"]          + ['=IFERROR(Justuno!E6,"")'] + ["—"]*(n-1) + ['=IFERROR(Justuno!E6,"")'],  # row 25
        ["SMS Opt-Ins"]            + ['=IFERROR(Justuno!F6,"")'] + ["—"]*(n-1) + ['=IFERROR(Justuno!F6,"")'],  # row 26
        ["Opt-In Rate"]            + ['=IFERROR(Justuno!G6,"")'] + ["—"]*(n-1) + ['=IFERROR(Justuno!G6,"")'],  # row 27
        ["Influenced Revenue ($)"] + ['=IFERROR(Justuno!H6,"")'] + ["—"]*(n-1) + ['=IFERROR(Justuno!H6,"")'],  # row 28
        pad([]),                                                                 # row 29
        pad(["━━  SHOPIFY  (campaign-level via discount codes)  ━━"]),          # row 30
        # Concepts share campaign-level codes — same value across concepts in same campaign.
        # TOTAL uses deduplicated codes to avoid double-counting.
        ["Orders (campaign)"]      + [_shopify_orders(c["discount_codes"]) for c in concepts] + [_shopify_total(all_codes, _shopify_orders)],  # row 31
        ["Revenue ($) (campaign)"] + [_shopify_revenue(c["discount_codes"]) for c in concepts] + [_shopify_total(all_codes, _shopify_revenue)],  # row 32
        ["AOV"]                    + [_shopify_aov(c["discount_codes"]) for c in concepts] + [_shopify_total(all_codes, _shopify_aov)],          # row 33
    ]


# ── Concept_View rows ─────────────────────────────────────────────────────────

def _concept_view_rows(first_concept_name):
    def val(cs_row):
        return (
            f"=IFERROR(INDEX(Campaign_Summary!$B${cs_row}:$Z${cs_row},"
            f"MATCH($B$1,Campaign_Summary!$B$3:$Z$3,0)),\"—\")"
        )

    def date_val(cs_row):
        return (
            f'=IFERROR(TEXT(INDEX(Campaign_Summary!$B${cs_row}:$Z${cs_row},'
            f'MATCH($B$1,Campaign_Summary!$B$3:$Z$3,0)),"MMM D, YYYY"),"—")'
        )

    return [
        ["Selected Concept  →", first_concept_name],   # idx 0
        [],                                             # idx 1
        ["Campaign",    val(4)],                        # idx 2
        ["Launch Date", date_val(5)],                   # idx 3
        ["Status",      val(6)],                        # idx 4
        ["TW Campaign", val(9)],                        # idx 5
        [],                                             # idx 6
        ["META / TRIPLE WHALE", ""],                    # idx 7  — section header
        ["Total Spend ($)",     val(10)],               # idx 8
        ["Avg ROAS",            val(11)],               # idx 9
        ["Total New Customers", val(12)],               # idx 10
        [],                                             # idx 11
        ["GA4 PAGES", ""],                              # idx 12 — section header
        ["Sessions",            val(15)],               # idx 13
        ["Active Users",        val(16)],               # idx 14
        ["New Users",           val(17)],               # idx 15
        ["Conversions",         val(18)],               # idx 16
        ["Revenue ($)",         val(19)],               # idx 17
        ["Avg Engagement Rate", val(20)],               # idx 18
        ["Avg Bounce Rate",     val(21)],               # idx 19
        [],                                             # idx 20
        ["JUSTUNO  (TOF-wide total)", ""],              # idx 21 — section header
        ["Impressions",            '=IFERROR(Justuno!D6,"—")'],  # idx 22
        ["Email Opt-Ins",          '=IFERROR(Justuno!E6,"—")'],  # idx 23
        ["SMS Opt-Ins",            '=IFERROR(Justuno!F6,"—")'],  # idx 24
        ["Opt-In Rate",            '=IFERROR(Justuno!G6,"—")'],  # idx 25
        ["Influenced Revenue ($)", '=IFERROR(Justuno!H6,"—")'],  # idx 26
        [],                                             # idx 27
        ["SHOPIFY  (campaign total via discount codes)", ""],  # idx 28 — section header
        ["Orders",   val(31)],                          # idx 29
        ["Revenue ($)", val(32)],                       # idx 30
        ["AOV",      val(33)],                          # idx 31
    ]


# ── Concept_View formatting ───────────────────────────────────────────────────

def _format_concept_view(service, sheet_id):
    def rng(r0, r1, c0=0, c1=2):
        return {"sheetId": sheet_id,
                "startRowIndex": r0, "endRowIndex": r1,
                "startColumnIndex": c0, "endColumnIndex": c1}

    def fill(r0, r1, c0, c1, bg, fg=None, bold=False, font_size=None, h_align=None):
        fmt = {"backgroundColor": bg,
               "textFormat": {"bold": bold, "foregroundColor": fg or C_TEXT}}
        if font_size:
            fmt["textFormat"]["fontSize"] = font_size
        if h_align:
            fmt["horizontalAlignment"] = h_align
        fields = "userEnteredFormat(backgroundColor,textFormat"
        if h_align:
            fields += ",horizontalAlignment"
        fields += ")"
        return {"repeatCell": {"range": rng(r0, r1, c0, c1),
                               "cell": {"userEnteredFormat": fmt}, "fields": fields}}

    def num_fmt(row_idx, pattern):
        return {"repeatCell": {
            "range": rng(row_idx, row_idx+1, 1, 2),
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": pattern}}},
            "fields": "userEnteredFormat.numberFormat",
        }}

    requests = [
        # Column widths
        {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1}, "properties": {"pixelSize": 280}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2}, "properties": {"pixelSize": 200}, "fields": "pixelSize"}},
        # Row 1 height
        {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 0, "endIndex": 1}, "properties": {"pixelSize": 44}, "fields": "pixelSize"}},
        # Freeze row 1
        {"updateSheetProperties": {"properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}}, "fields": "gridProperties.frozenRowCount"}},
        # Row 1: A1 dark label, B1 blue selector
        fill(0, 1, 0, 1, C_DARK, C_WHITE, bold=True, font_size=12),
        fill(0, 1, 1, 2, C_SELECTOR, C_WHITE, bold=True, font_size=12),
        # Metadata rows 3-6 (idx 2-5)
        fill(2, 6, 0, 2, C_META),
        fill(2, 6, 0, 1, C_META, bold=True),
        # Section headers: idx 7, 12, 21, 28
        *[fill(i, i+1, 0, 2, C_DARK, C_WHITE, bold=True) for i in [7, 12, 21, 28]],
    ]

    # Metric rows: alternating white/gray
    metric_rows = [8, 9, 10, 13, 14, 15, 16, 17, 18, 19, 22, 23, 24, 25, 26, 29, 30, 31]
    for j, idx in enumerate(metric_rows):
        bg = C_ALT if j % 2 == 0 else C_WHITE
        requests.append(fill(idx, idx+1, 0, 1, bg, bold=True))
        requests.append(fill(idx, idx+1, 1, 2, bg, h_align="RIGHT"))

    # Number formats
    for row_idx, pattern in [
        (8,  '$#,##0.00'),   # Total Spend
        (9,  '0.00"x"'),     # Avg ROAS
        (10, '#,##0'),       # Total New Customers
        (13, '#,##0'),       # Sessions
        (14, '#,##0'),       # Active Users
        (15, '#,##0'),       # New Users
        (16, '#,##0'),       # Conversions
        (17, '$#,##0.00'),   # Revenue (GA4)
        (18, '0.0%'),        # Avg Engagement Rate
        (19, '0.0%'),        # Avg Bounce Rate
        (22, '#,##0'),       # Impressions
        (23, '#,##0'),       # Email Opt-Ins
        (24, '#,##0'),       # SMS Opt-Ins
        (29, '#,##0'),       # Shopify Orders
        (30, '$#,##0.00'),   # Shopify Revenue
        (31, '$#,##0.00'),   # Shopify AOV
    ]:
        requests.append(num_fmt(row_idx, pattern))

    service.spreadsheets().batchUpdate(
        spreadsheetId=DESTINATION_SHEET_ID, body={"requests": requests}
    ).execute()


# ── dropdown ──────────────────────────────────────────────────────────────────

def _set_dropdown(service, sheet_id, concept_names):
    service.spreadsheets().batchUpdate(
        spreadsheetId=DESTINATION_SHEET_ID,
        body={"requests": [{"setDataValidation": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 1, "endColumnIndex": 2},
            "rule": {"condition": {"type": "ONE_OF_LIST",
                                   "values": [{"userEnteredValue": n} for n in concept_names]},
                     "showCustomUi": True, "strict": True},
        }}]}
    ).execute()


# ── Shopify_Orders tab ────────────────────────────────────────────────────────

def _init_shopify_tab(service):
    """Create Shopify_Orders with headers only if it doesn't have data yet."""
    _ensure_tab(service, SHOPIFY_TAB)
    existing = service.spreadsheets().values().get(
        spreadsheetId=DESTINATION_SHEET_ID, range=f"{SHOPIFY_TAB}!A1"
    ).execute()
    if "values" in existing:
        return  # already has data — never overwrite
    service.spreadsheets().values().update(
        spreadsheetId=DESTINATION_SHEET_ID,
        range=f"{SHOPIFY_TAB}!A1",
        valueInputOption="USER_ENTERED",
        body={"values": [
            ["Shopify Orders — paste data starting at row 4. "
             "Export from: Shopify Admin → Analytics → Reports → Sales by discount code."],
            [],
            ["Discount Code", "Orders", "Revenue ($)"],
        ]},
    ).execute()
    print(f"  {SHOPIFY_TAB}: created with headers (paste your export starting at row 4)")


# ── main ──────────────────────────────────────────────────────────────────────

def sync():
    print("Building registry tabs...")
    service   = get_sheets_service()
    campaigns = camp.load()

    concepts = [
        concept
        for c in campaigns
        for concept in c.get("concepts", [])
    ]
    concept_names = [c["name"] for c in concepts]

    _ensure_tab(service, REGISTRY_TAB)
    _clear_write(service, REGISTRY_TAB, _registry_rows(campaigns))
    url_row_count = sum(max(len(c.get("urls", [])), 1) for c in concepts)
    print(f"  URL_Registry: {url_row_count} row(s)")

    _ensure_tab(service, SUMMARY_TAB)
    _clear_write(service, SUMMARY_TAB, _summary_rows(campaigns))
    print(f"  Campaign_Summary: {len(concepts)} concept column(s)")

    first_name  = concept_names[0] if concept_names else ""
    cv_sheet_id = _ensure_tab(service, CONCEPT_VIEW_TAB)
    _clear_write(service, CONCEPT_VIEW_TAB, _concept_view_rows(first_name))
    if concept_names:
        _set_dropdown(service, cv_sheet_id, concept_names)
    _format_concept_view(service, cv_sheet_id)
    print(f"  Concept_View: {len(concept_names)} concepts in dropdown")

    _init_shopify_tab(service)

    print("  Done. Re-run only when campaigns.json changes.")
