import json
import os
from collections import defaultdict
from datetime import date, timedelta, datetime
from google.oauth2 import service_account
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange, Dimension, Metric, RunReportRequest,
    FilterExpression, Filter
)
from sync.sheets import get_sheets_service, _get_sheet_id, _reset_tab_formatting
from sync.config import DESTINATION_SHEET_ID, DEST_TABS
from sync import campaigns as camp

PROPERTY_ID = "332137414"
DEST_TAB = DEST_TABS["ga4"]

INSTRUCTIONS = (
    "Instructions: Pull from GA4 Exploration. "
    "One row per URL per pull (or per day if tracking daily). "
    "Yellow = inputs, green = formula."
)
COL_HEADERS = [
    "Date", "URL", "Sessions", "Active Users", "New Users",
    "Engagement Rate", "Avg Eng. Time (s)", "Bounce Rate",
    "Conversions", "Revenue ($)"
]


def _get_client():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw:
        info = json.loads(raw)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/analytics.readonly"]
        )
    else:
        creds = service_account.Credentials.from_service_account_file(
            "service_account.json",
            scopes=["https://www.googleapis.com/auth/analytics.readonly"]
        )
    return BetaAnalyticsDataClient(credentials=creds)


def _fetch(start_date: str, end_date: str, urls: list):
    """One API call per date range; returns one aggregated row per landing page."""
    client = _get_client()
    request = RunReportRequest(
        property=f"properties/{PROPERTY_ID}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[Dimension(name="landingPage")],
        metrics=[
            Metric(name="sessions"),
            Metric(name="activeUsers"),
            Metric(name="newUsers"),
            Metric(name="userEngagementDuration"),
            Metric(name="keyEvents"),
            Metric(name="totalRevenue"),
            Metric(name="bounceRate"),
            Metric(name="engagementRate"),
        ],
        dimension_filter=FilterExpression(
            filter=Filter(
                field_name="landingPage",
                in_list_filter=Filter.InListFilter(values=urls),
            )
        ),
        limit=1000,
    )
    return client.run_report(request)


def _date_label(start: str, end: str) -> str:
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    return f"{s.strftime('%b %-d')}-{e.strftime('%b %-d')} {e.year}"


def _write_formatted_tab(service, data_rows, last_updated_label):
    """Rebuild the GA4_Pages tab with Amrata's original header structure and formatting."""
    sheet_id_num = _get_sheet_id(service, DESTINATION_SHEET_ID, DEST_TAB)

    # 1. Remove all merges and clear all formatting
    if sheet_id_num is not None:
        _reset_tab_formatting(service, DESTINATION_SHEET_ID, sheet_id_num)

    # 2. Clear all values
    service.spreadsheets().values().clear(
        spreadsheetId=DESTINATION_SHEET_ID,
        range=f"{DEST_TAB}!A:Z",
    ).execute()

    # 3. Write all values
    all_rows = [
        ["GA4 — PAGE PERFORMANCE (Amrata owns this tab)"],   # row 1
        ["Last Updated:", last_updated_label],               # row 2
        [INSTRUCTIONS],                                      # row 3
        [],                                                  # row 4 blank
        COL_HEADERS,                                         # row 5
    ] + data_rows                                            # rows 6+

    service.spreadsheets().values().update(
        spreadsheetId=DESTINATION_SHEET_ID,
        range=f"{DEST_TAB}!A1",
        valueInputOption="USER_ENTERED",
        body={"values": all_rows},
    ).execute()

    if sheet_id_num is None:
        return

    n_data = len(data_rows)
    dark_blue = {"red": 0.122, "green": 0.302, "blue": 0.475}  # #1f4e79
    white     = {"red": 1.0,   "green": 1.0,   "blue": 1.0}
    yellow    = {"red": 1.0,   "green": 0.949, "blue": 0.8}    # #fff2cc

    def cell_fmt(bg, fg=None, bold=False, italic=False, h_align=None):
        fmt = {"backgroundColor": bg}
        tf = {}
        if fg:
            tf["foregroundColor"] = fg
        if bold:
            tf["bold"] = True
        if italic:
            tf["italic"] = True
        if tf:
            fmt["textFormat"] = tf
        if h_align:
            fmt["horizontalAlignment"] = h_align
        return {"userEnteredFormat": fmt}

    def row_of(fmt, n_cols=10):
        return {"values": [fmt] * n_cols}

    requests = [
        # Merge row 1 across all 10 columns
        {"mergeCells": {
            "range": {"sheetId": sheet_id_num,
                      "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": 10},
            "mergeType": "MERGE_ALL",
        }},
        # Row 1: dark blue bg, white bold centered
        {"updateCells": {
            "range": {"sheetId": sheet_id_num,
                      "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": 10},
            "rows": [row_of(cell_fmt(dark_blue, fg=white, bold=True, h_align="CENTER"))],
            "fields": "userEnteredFormat",
        }},
        # Row 2 col A: bold label
        {"updateCells": {
            "range": {"sheetId": sheet_id_num,
                      "startRowIndex": 1, "endRowIndex": 2,
                      "startColumnIndex": 0, "endColumnIndex": 1},
            "rows": [{"values": [cell_fmt(white, bold=True)]}],
            "fields": "userEnteredFormat",
        }},
        # Row 2 cols B-E: yellow date value
        {"updateCells": {
            "range": {"sheetId": sheet_id_num,
                      "startRowIndex": 1, "endRowIndex": 2,
                      "startColumnIndex": 1, "endColumnIndex": 5},
            "rows": [{"values": [cell_fmt(yellow)] * 4}],
            "fields": "userEnteredFormat",
        }},
        # Row 3: italic instructions
        {"updateCells": {
            "range": {"sheetId": sheet_id_num,
                      "startRowIndex": 2, "endRowIndex": 3,
                      "startColumnIndex": 0, "endColumnIndex": 10},
            "rows": [row_of(cell_fmt(white, italic=True))],
            "fields": "userEnteredFormat",
        }},
        # Row 5: dark blue column headers, white bold centered
        {"updateCells": {
            "range": {"sheetId": sheet_id_num,
                      "startRowIndex": 4, "endRowIndex": 5,
                      "startColumnIndex": 0, "endColumnIndex": 10},
            "rows": [row_of(cell_fmt(dark_blue, fg=white, bold=True, h_align="CENTER"))],
            "fields": "userEnteredFormat",
        }},
    ]

    # Data rows: yellow background only — use specific field path so we don't
    # overwrite the auto-applied number formats (%, $) that Sheets sets when
    # it parses USER_ENTERED values like "38.5%" or "$5,078.22"
    if n_data > 0:
        requests.append({"updateCells": {
            "range": {"sheetId": sheet_id_num,
                      "startRowIndex": 5, "endRowIndex": 5 + n_data,
                      "startColumnIndex": 0, "endColumnIndex": 10},
            "rows": [row_of({"userEnteredFormat": {"backgroundColor": yellow}})] * n_data,
            "fields": "userEnteredFormat.backgroundColor",
        }})

    service.spreadsheets().batchUpdate(
        spreadsheetId=DESTINATION_SHEET_ID,
        body={"requests": requests},
    ).execute()


def sync():
    print("Syncing GA4...")

    campaigns = camp.load()
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")

    # Build url → start_date map
    url_start = {}
    for c in campaigns:
        launch = c.get("launched", "2026-01-01")
        overrides = c.get("url_start_dates", {})
        for url in c.get("urls", []):
            url_start[url] = overrides.get(url, launch)

    if not url_start:
        print("  No URLs configured in campaigns.json — skipping GA4.")
        return

    # Group URLs by start date; one API call per group
    by_start = defaultdict(list)
    for url, start in url_start.items():
        by_start[start].append(url)

    results = {}
    for start_date, urls in sorted(by_start.items()):
        print(f"  Fetching {len(urls)} URL(s) from {start_date} to {yesterday}...")
        response = _fetch(start_date, yesterday, urls)
        for row in response.rows:
            url = row.dimension_values[0].value
            sessions = int(row.metric_values[0].value)
            eng_time_total = float(row.metric_values[3].value)
            results[url] = {
                "start": start_date,
                "sessions":    sessions,
                "active":      int(row.metric_values[1].value),
                "new":         int(row.metric_values[2].value),
                "avg_eng":     round(eng_time_total / sessions, 1) if sessions else 0,
                "key_events":  int(float(row.metric_values[4].value)),
                "revenue":     round(float(row.metric_values[5].value), 2),
                "bounce":      float(row.metric_values[6].value),
                "eng_rate":    float(row.metric_values[7].value),
            }

    # Build data rows in campaigns.json URL order
    data_rows = []
    earliest_start = min(url_start.values())
    for c in campaigns:
        overrides = c.get("url_start_dates", {})
        launch = c.get("launched", "2026-01-01")
        for url in c.get("urls", []):
            start = overrides.get(url, launch)
            label = _date_label(start, yesterday)
            if url not in results:
                data_rows.append([label, url, 0, 0, 0, "0.0%", 0, "0.0%", 0, "$0.00"])
                continue
            r = results[url]
            data_rows.append([
                label,
                url,
                r["sessions"],
                r["active"],
                r["new"],
                f"{r['eng_rate']:.1%}",
                r["avg_eng"],
                f"{r['bounce']:.1%}",
                r["key_events"],
                f"${r['revenue']:,.2f}",
            ])

    last_updated = _date_label(earliest_start, yesterday)
    service = get_sheets_service()
    _write_formatted_tab(service, data_rows, last_updated)
    print(f"  Wrote {len(data_rows)} row(s) to '{DEST_TAB}' with formatting.")
