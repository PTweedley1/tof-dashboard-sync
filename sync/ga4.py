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


def _fetch(run_date: str, urls: list):
    client = _get_client()
    request = RunReportRequest(
        property=f"properties/{PROPERTY_ID}",
        date_ranges=[DateRange(start_date=run_date, end_date=run_date)],
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

    if yesterday in existing_dates:
        print(f"  GA4_Pages is already up to date (has {yesterday}).")
        return

    response = _fetch(yesterday, urls)

    new_rows = []
    for row in response.rows:
        page_path = row.dimension_values[1].value
        campaign_name = camp.campaign_for_url(page_path)
        eng_rate = float(row.metric_values[3].value)
        bounce_rate = float(row.metric_values[5].value)

        new_rows.append([
            yesterday,
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

    if new_rows:
        append_rows(DESTINATION_SHEET_ID, DEST_TAB, new_rows)
        print(f"  Added {len(new_rows)} row(s) for {yesterday} to '{DEST_TAB}'.")
    else:
        print(f"  No GA4 data found for {yesterday} on campaign pages.")
