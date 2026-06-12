import json
import os
from collections import defaultdict
from datetime import date, timedelta
from google.oauth2 import service_account
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange, Dimension, Metric, RunReportRequest,
    FilterExpression, Filter
)
from sync.sheets import clear_and_write_rows
from sync.config import DESTINATION_SHEET_ID, DEST_TABS
from sync import campaigns as camp

PROPERTY_ID = "332137414"
DEST_TAB = DEST_TABS["ga4"]
START_DATE = "2026-05-01"

HEADER = ["Date Range", "URL", "Sessions", "Active Users", "New Users",
          "Engagement Rate", "Avg Eng. Time (s)", "Bounce Rate",
          "Conversions", "Revenue ($)"]


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


def _date_label(start: str, end: str) -> str:
    """Format a date range like 'May 1 – Jun 11'."""
    from datetime import datetime
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    return f"{s.strftime('%b %-d')} – {e.strftime('%b %-d')}"


def _aggregate(response, urls):
    """Aggregate daily GA4 rows into one total per URL."""
    totals = defaultdict(lambda: {
        "sessions": 0,
        "active_users": 0,
        "new_users": 0,
        "eng_rate_sum": 0.0,
        "eng_time_sum": 0.0,
        "bounce_rate_sum": 0.0,
        "conversions": 0,
        "revenue": 0.0,
        "day_count": 0,
    })

    for row in response.rows:
        url = row.dimension_values[1].value
        t = totals[url]
        t["sessions"] += int(row.metric_values[0].value)
        t["active_users"] += int(row.metric_values[1].value)
        t["new_users"] += int(row.metric_values[2].value)
        t["eng_rate_sum"] += float(row.metric_values[3].value)
        t["eng_time_sum"] += float(row.metric_values[4].value)
        t["bounce_rate_sum"] += float(row.metric_values[5].value)
        t["conversions"] += int(float(row.metric_values[6].value))
        t["revenue"] += float(row.metric_values[7].value)
        t["day_count"] += 1

    return totals


def sync():
    print("Syncing GA4...")

    urls = camp.all_urls()
    if not urls:
        print("  No URLs configured in campaigns.json — skipping GA4.")
        return

    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    date_label = _date_label(START_DATE, yesterday)

    print(f"  Fetching GA4 data from {START_DATE} to {yesterday}...")
    response = _fetch(START_DATE, yesterday, urls)

    totals = _aggregate(response, urls)

    # Build one output row per URL, in the same order as campaigns.json
    output_rows = [HEADER]
    for url in urls:
        if url not in totals:
            # URL had zero traffic — write zeroes so the row still appears
            output_rows.append([date_label, url, 0, 0, 0, "0.0%", 0, "0.0%", 0, 0.00])
            continue

        t = totals[url]
        n = t["day_count"]
        avg_eng = t["eng_rate_sum"] / n if n else 0
        avg_time = t["eng_time_sum"] / n if n else 0
        avg_bounce = t["bounce_rate_sum"] / n if n else 0

        output_rows.append([
            date_label,
            url,
            t["sessions"],
            t["active_users"],
            t["new_users"],
            f"{avg_eng:.1%}",
            round(avg_time, 1),
            f"{avg_bounce:.1%}",
            t["conversions"],
            round(t["revenue"], 2),
        ])

    clear_and_write_rows(DESTINATION_SHEET_ID, DEST_TAB, output_rows)
    print(f"  Wrote {len(output_rows) - 1} URL row(s) to '{DEST_TAB}' ({date_label}).")
