from datetime import date
from sync.sheets import get_sheets_service
from sync.config import DESTINATION_SHEET_ID
from sync import campaigns as camp


DASH_TAB = "Campaign View"

# Column indices in each source tab (0-based)
TW_DATE, TW_CAMPAIGN, TW_SPEND, TW_CPM, TW_CPC, TW_CTR, TW_CPA, TW_ROAS, TW_NCP = range(9)
GA4_DATE, GA4_URL, GA4_SESSIONS, GA4_USERS, GA4_NEW, GA4_ENG, GA4_TIME, GA4_BOUNCE, GA4_CONV, GA4_REV = range(10)
JU_DATE, JU_PROMO, JU_PAGE, JU_IMPR, JU_EMAIL, JU_SMS, JU_RATE, JU_REV = range(8)


def _read_tab(service, tab, cell_range="A:Z"):
    result = service.spreadsheets().values().get(
        spreadsheetId=DESTINATION_SHEET_ID,
        range=f"{tab}!{cell_range}"
    ).execute()
    rows = result.get("values", [])
    return rows[1:] if rows else []  # skip header


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


def _write(service, rows, start_row=1):
    if not rows:
        return
    service.spreadsheets().values().update(
        spreadsheetId=DESTINATION_SHEET_ID,
        range=f"{DASH_TAB}!A{start_row}",
        valueInputOption="USER_ENTERED",
        body={"values": rows}
    ).execute()
    return start_row + len(rows)


def _safe(rows, row_idx, col_idx, default=""):
    try:
        val = rows[row_idx][col_idx]
        return val if val != "" else default
    except IndexError:
        return default


def _parse_num(val):
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        cleaned = val.replace("$", "").replace(",", "").replace("%", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    return 0.0


def _build_campaign_section(campaign, tw_rows, ga4_rows, ju_rows):
    """Build rows for one campaign's section in the dashboard."""
    out = []
    tw_names = campaign.get("triple_whale_campaigns", [])
    urls = campaign.get("urls", [])

    # Section header
    out.append([f"▸ {campaign['name']}  |  Launched: {campaign['launched']}"])
    out.append([])

    # ── META / TRIPLE WHALE ──────────────────────────────────────────────────
    out.append(["META / TRIPLE WHALE"])
    out.append(["TW Campaign", "Total Spend ($)", "Avg CPM ($)", "Avg CPC ($)",
                "Avg CTR", "Avg CPA ($)", "Avg ROAS", "Total New Customers"])

    tw_campaign_rows = [r for r in tw_rows if len(r) > TW_CAMPAIGN and r[TW_CAMPAIGN] in tw_names]

    if tw_campaign_rows:
        # Group by TW campaign name
        by_name = {}
        for r in tw_campaign_rows:
            name = r[TW_CAMPAIGN]
            if name not in by_name:
                by_name[name] = []
            by_name[name].append(r)

        total_spend = 0
        for name, rows in by_name.items():
            spend = sum(_parse_num(_safe(rows, i, TW_SPEND)) for i in range(len(rows)))
            cpm   = sum(_parse_num(_safe(rows, i, TW_CPM))   for i in range(len(rows))) / len(rows)
            cpc   = sum(_parse_num(_safe(rows, i, TW_CPC))   for i in range(len(rows))) / len(rows)
            ctr   = sum(_parse_num(_safe(rows, i, TW_CTR))   for i in range(len(rows))) / len(rows)
            cpa   = sum(_parse_num(_safe(rows, i, TW_CPA))   for i in range(len(rows))) / len(rows)
            roas  = sum(_parse_num(_safe(rows, i, TW_ROAS))  for i in range(len(rows))) / len(rows)
            ncp   = sum(_parse_num(_safe(rows, i, TW_NCP))   for i in range(len(rows)))
            total_spend += spend
            out.append([name, f"${spend:,.2f}", f"${cpm:.2f}", f"${cpc:.2f}",
                        f"{ctr:.2f}%", f"${cpa:.2f}", f"{roas:.3f}", int(ncp)])

        total_ncp = sum(_parse_num(_safe(tw_campaign_rows, i, TW_NCP)) for i in range(len(tw_campaign_rows)))
        out.append(["TOTAL", f"${total_spend:,.2f}", "", "", "", "", "", int(total_ncp)])
    else:
        out.append(["No Meta data yet for this campaign."])

    out.append([])

    # ── GA4 PAGES ────────────────────────────────────────────────────────────
    out.append(["GA4 PAGES"])
    out.append(["URL", "Sessions", "Active Users", "New Users",
                "Engagement Rate", "Avg Eng. Time (s)", "Bounce Rate",
                "Conversions", "Revenue ($)"])

    ga4_campaign_rows = [r for r in ga4_rows if len(r) > GA4_URL and r[GA4_URL] in urls]

    if ga4_campaign_rows:
        for r in ga4_campaign_rows:
            out.append([
                _safe([r], 0, GA4_URL),
                _safe([r], 0, GA4_SESSIONS),
                _safe([r], 0, GA4_USERS),
                _safe([r], 0, GA4_NEW),
                _safe([r], 0, GA4_ENG),
                _safe([r], 0, GA4_TIME),
                _safe([r], 0, GA4_BOUNCE),
                _safe([r], 0, GA4_CONV),
                _safe([r], 0, GA4_REV),
            ])
        total_sessions = sum(_parse_num(_safe([r], 0, GA4_SESSIONS)) for r in ga4_campaign_rows)
        total_rev      = sum(_parse_num(_safe([r], 0, GA4_REV))      for r in ga4_campaign_rows)
        total_conv     = sum(_parse_num(_safe([r], 0, GA4_CONV))      for r in ga4_campaign_rows)
        out.append(["TOTAL", f"{int(total_sessions):,}", "", "", "", "", "",
                    int(total_conv), f"${total_rev:,.2f}"])
    else:
        out.append(["No GA4 data yet for this campaign."])

    out.append([])

    # ── JUSTUNO (consolidated across all campaigns) ──────────────────────────
    out.append(["JUSTUNO (Campaign-Level Total)"])
    out.append(["Date Range", "Promotion", "Impressions",
                "Email Opt-Ins", "SMS Opt-Ins", "Opt-In Rate", "Influenced Revenue ($)"])
    if ju_rows:
        for r in ju_rows:
            out.append([
                _safe([r], 0, JU_DATE),
                _safe([r], 0, JU_PROMO),
                _safe([r], 0, JU_IMPR),
                _safe([r], 0, JU_EMAIL),
                _safe([r], 0, JU_SMS),
                _safe([r], 0, JU_RATE),
                _safe([r], 0, JU_REV),
            ])
    else:
        out.append(["No Justuno data yet."])

    out.append([])
    out.append(["─" * 60])
    out.append([])

    return out


def sync():
    print("Building Campaign View tab...")
    service = get_sheets_service()
    _ensure_tab(service)
    _clear_tab(service)

    tw_rows   = _read_tab(service, "Meta_TripleWhale")
    ga4_rows  = _read_tab(service, "GA4_Pages")
    ju_rows   = _read_tab(service, "Justuno")

    all_rows = [
        [f"Campaign View   |   Last updated: {date.today().strftime('%B %d, %Y')}"],
        [],
    ]

    for campaign in camp.load():
        all_rows += _build_campaign_section(campaign, tw_rows, ga4_rows, ju_rows)

    _write(service, all_rows)
    print(f"  Campaign View tab updated with {len(camp.load())} campaign(s).")
