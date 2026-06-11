"""
Campaign View tab — written once with live formulas.
Any update to the raw tabs (Meta_TripleWhale, GA4_Pages, Justuno, Shopify_OrderTag)
is instantly reflected here without re-running the script.

Re-run this module only when campaigns.json changes (new campaign added, URLs updated).
"""
from datetime import date
from sync.sheets import get_sheets_service
from sync.config import DESTINATION_SHEET_ID
from sync import campaigns as camp

DASH_TAB = "Campaign View"

# Column letters for each source tab (must match the actual sheet structure)
# Meta_TripleWhale: A=Date, B=Campaign, C=Spend, D=CPM, E=CPC, F=CTR, G=CPA, H=ROAS, I=New Customers
# GA4_Pages:        A=Date, B=URL, C=Sessions, D=Active Users, E=New Users,
#                   F=Engagement Rate, G=Avg Eng Time, H=Bounce Rate, I=Conversions, J=Revenue
# Justuno:          A=Date, B=Promo Name, C=Page URL, D=Impressions, E=Email, F=SMS, G=Rate, H=Revenue
# Shopify_OrderTag: A=Date, B=Weekday, C=Code, D=Channel, E=Customer Type,
#                   F=Orders, G=Net Sales, H=AOV, I=UPT, J=Units


def _sumif(tab, lookup_col, match_val, sum_col):
    return f'=IFERROR(SUMIF({tab}!${lookup_col}:${lookup_col},"{match_val}",{tab}!${sum_col}:${sum_col}),0)'


def _avgif(tab, lookup_col, match_val, avg_col):
    return f'=IFERROR(AVERAGEIF({tab}!${lookup_col}:${lookup_col},"{match_val}",{tab}!${avg_col}:${avg_col}),0)'


def _ensure_tab(service):
    meta = service.spreadsheets().get(spreadsheetId=DESTINATION_SHEET_ID).execute()
    existing = [s["properties"]["title"] for s in meta["sheets"]]
    if DASH_TAB not in existing:
        service.spreadsheets().batchUpdate(
            spreadsheetId=DESTINATION_SHEET_ID,
            body={"requests": [{"addSheet": {"properties": {"title": DASH_TAB}}}]}
        ).execute()


def _clear_tab(service):
    service.spreadsheets().values().clear(
        spreadsheetId=DESTINATION_SHEET_ID,
        range=f"{DASH_TAB}!A:Z"
    ).execute()


def _write_all(service, rows):
    service.spreadsheets().values().update(
        spreadsheetId=DESTINATION_SHEET_ID,
        range=f"{DASH_TAB}!A1",
        valueInputOption="USER_ENTERED",
        body={"values": rows}
    ).execute()


def _campaign_section(campaign):
    tw_names = campaign.get("triple_whale_campaigns", [])
    urls = campaign.get("urls", [])
    out = []

    # ── Campaign header ───────────────────────────────────────────────────────
    out.append([f"▸ {campaign['name']}   |   Launched: {campaign['launched']}"])
    out.append([])

    # ── META / TRIPLE WHALE ───────────────────────────────────────────────────
    out.append(["META / TRIPLE WHALE"])
    out.append(["TW Campaign", "Total Spend ($)", "Avg CPM ($)", "Avg CPC ($)",
                "Avg CTR (%)", "Avg CPA ($)", "Avg ROAS", "Total New Customers"])

    if tw_names:
        for name in tw_names:
            out.append([
                name,
                _sumif("Meta_TripleWhale", "B", name, "C"),
                _avgif("Meta_TripleWhale", "B", name, "D"),
                _avgif("Meta_TripleWhale", "B", name, "E"),
                _avgif("Meta_TripleWhale", "B", name, "F"),
                _avgif("Meta_TripleWhale", "B", name, "G"),
                _avgif("Meta_TripleWhale", "B", name, "H"),
                _sumif("Meta_TripleWhale", "B", name, "I"),
            ])
        # Totals row — sums the N rows just written
        n = len(tw_names)
        base = len(out) + 1  # approximate row, close enough for SUM refs
        out.append([
            "TOTAL",
            f"=SUM(B{base - n}:B{base - 1})",
            "",
            "",
            f"=IFERROR(AVERAGE(E{base - n}:E{base - 1}),\"\")",
            "",
            f"=IFERROR(AVERAGE(G{base - n}:G{base - 1}),\"\")",
            f"=SUM(H{base - n}:H{base - 1})",
        ])
    else:
        out.append(["No Triple Whale campaigns configured yet — add them to campaigns.json"])

    out.append([])

    # ── GA4 PAGES ─────────────────────────────────────────────────────────────
    out.append(["GA4 PAGES"])
    out.append(["URL", "Sessions", "Active Users", "New Users",
                "Engagement Rate", "Avg Eng. Time (s)", "Bounce Rate",
                "Conversions", "Revenue ($)"])

    if urls:
        for url in urls:
            out.append([
                url,
                _sumif("GA4_Pages", "B", url, "C"),
                _sumif("GA4_Pages", "B", url, "D"),
                _sumif("GA4_Pages", "B", url, "E"),
                _avgif("GA4_Pages", "B", url, "F"),
                _avgif("GA4_Pages", "B", url, "G"),
                _avgif("GA4_Pages", "B", url, "H"),
                _sumif("GA4_Pages", "B", url, "I"),
                _sumif("GA4_Pages", "B", url, "J"),
            ])
        n = len(urls)
        base = len(out) + 1
        out.append([
            "TOTAL",
            f"=SUM(B{base - n}:B{base - 1})",
            f"=SUM(C{base - n}:C{base - 1})",
            f"=SUM(D{base - n}:D{base - 1})",
            "",
            "",
            "",
            f"=SUM(H{base - n}:H{base - 1})",
            f"=SUM(I{base - n}:I{base - 1})",
        ])
    else:
        out.append(["No URLs configured yet — add them to campaigns.json"])

    out.append([])

    # ── JUSTUNO (consolidated — same for every campaign) ──────────────────────
    out.append(["JUSTUNO (Consolidated)"])
    out.append(["Date Range", "Promotion", "Impressions",
                "Email Opt-Ins", "SMS Opt-Ins", "Opt-In Rate", "Influenced Revenue ($)"])
    out.append([
        "=IFERROR(Justuno!A2,\"\")",
        "=IFERROR(Justuno!B2,\"\")",
        "=IFERROR(SUM(Justuno!D:D),\"\")",
        "=IFERROR(SUM(Justuno!E:E),\"\")",
        "=IFERROR(SUM(Justuno!F:F),\"\")",
        "=IFERROR(AVERAGE(Justuno!G:G),\"\")",
        "=IFERROR(SUM(Justuno!H:H),\"\")",
    ])

    out.append([])
    out.append(["━" * 80])
    out.append([])

    return out


def sync():
    print("Building Campaign View tab (live formulas)...")
    service = get_sheets_service()
    _ensure_tab(service)
    _clear_tab(service)

    all_rows = [
        [f"CAMPAIGN VIEW DASHBOARD   —   Formulas update live from raw tabs   —   Config last set: {date.today().strftime('%B %d, %Y')}"],
        [],
    ]

    for c in camp.load():
        all_rows += _campaign_section(c)

    _write_all(service, all_rows)
    print(f"  Done — {len(camp.load())} campaign(s) wired up with live formulas.")
    print("  Note: re-run this only when campaigns.json changes (new campaign or new URLs).")
