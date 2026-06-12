import json
import os
from datetime import date, timedelta
from google.oauth2 import service_account
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange, Dimension, Metric, RunReportRequest,
    FilterExpression, Filter
)
from sync.sheets import get_existing_dates, append_rows
from sync.config import DESTINATION_SHEET_ID, DEST_TABS
from sync import campaigns as camp

PROPERTY_ID = "332137414"
DEST_TAB = DEST_TABS["ga4"]
START_DATE = "2026-05-01"


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
    client = _get_client()
    request = RunReportRequest(
        property=f"properties/{PROPERTY_ID}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[
            Dimension(name="date"),
            Dimension(name="pagePath"),
        ],
        metrics=[
            Metric(name="sessions"),
            Metric(name="activeUsers"),
            Metric(name="newUsers"),
            Metric(name="engagementRate"),
            Metric(name="averageSessionDuration"),
            Metric(name="bounceRate"),
            Metric(name="conversions"),
            Metric(name="purchaseRevenue"),
        ],
        dimension_filter=FilterExpression(
            filter=Filter(
                field_name="pagePath",
                in_list_filter=Filter.InListFilter(values=urls),
            )
        ),
        limit=100000,
    )
    return client.run_report(request)


def _format_date(ga_date: str) -> str:
    # GA4 returns dates as YYYYMMDD → convert to YYYY-MM-DD
    return f"{ga_date[:4]}-{ga_date[4:6]}-{ga_date[6:]}"


def sync():
    print("Syncing GA4...")

    urls = camp.all_urls()
    if not urls:
        print("  No URLs configured in campaigns.json — skipping GA4.")
        return

    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    existing_dates = get_existing_dates(DESTINATION_SHEET_ID, DEST_TAB)

    print(f"  Fetching GA4 data from {START_DATE} to {yesterday}...")
    response = _fetch(START_DATE, yesterday, urls)

    new_rows = []
    for row in response.rows:
        row_date = _format_date(row.dimension_values[0].value)
        if row_date in existing_dates:
            continue  # already in sheet, skip

        page_path = row.dimension_values[1].value
        eng_rate = float(row.metric_values[3].value)
        bounce_rate = float(row.metric_values[5].value)

        new_rows.append([
            row_date,
            page_path,                    # URL
            row.metric_values[0].value,   # Sessions
            row.metric_values[1].value,   # Active Users
            row.metric_values[2].value,   # New Users
            f"{eng_rate:.1%}",            # Engagement Rate
            round(float(row.metric_values[4].value), 1),  # Avg Eng. Time (s)
            f"{bounce_rate:.1%}",         # Bounce Rate
            row.metric_values[6].value,   # Conversions
            round(float(row.metric_values[7].value), 2),  # Revenue ($)
        ])

    # Sort by date so rows land in chronological order
    new_rows.sort(key=lambda r: r[0])

    if new_rows:
        append_rows(DESTINATION_SHEET_ID, DEST_TAB, new_rows)
        dates_added = sorted({r[0] for r in new_rows})
        print(f"  Added {len(new_rows)} row(s) across {len(dates_added)} date(s) to '{DEST_TAB}'.")
        print(f"  Date range covered: {dates_added[0]} → {dates_added[-1]}")
    else:
        print(f"  GA4_Pages already has all data from {START_DATE} to {yesterday}.")
