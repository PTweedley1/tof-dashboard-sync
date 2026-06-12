import os
import requests
from datetime import date, timedelta, datetime
from sync.sheets import get_sheets_service
from sync.config import DESTINATION_SHEET_ID, DEST_TABS
from sync import campaigns as camp

FIREBASE_API_KEY = "AIzaSyA6M6uSJutnZIQ5ri7M5jJWW-fdOA6q3zk"
PRIMARY_SOURCE = "5307cb03ba334c1a8bc9b91814ba2d80"
DEST_TAB = DEST_TABS["justuno"]

DATA_POINTS = ["impressions", "emails", "sms", "lead-capture-rate", "influenced-revenue"]


def _ordinal(n):
    if 11 <= n <= 13:
        return f"{n}th"
    return f"{n}" + {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _get_id_token():
    """Exchange stored refresh token for a short-lived Firebase ID token."""
    resp = requests.post(
        f"https://securetoken.googleapis.com/v1/token?key={FIREBASE_API_KEY}",
        data={
            "grant_type": "refresh_token",
            "refresh_token": os.environ["JUSTUNO_REFRESH_TOKEN"],
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["id_token"]


def _fetch(id_token, data_point, start_date, end_date):
    """Fetch one metric value from the Justuno custom-dashboard-summary endpoint."""
    resp = requests.get(
        "https://api.justuno.com/v1/analytics/custom-dashboard-summary",
        params={
            "startDate": start_date,
            "endDate": end_date,
            "timezone": "America/Los_Angeles",
            "dataPoint": data_point,
            "primarySource": PRIMARY_SOURCE,
            "primarySourceType": "experiences",
        },
        headers={"Firebase-Token": id_token},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["current"]


def sync():
    print("Syncing Justuno...")

    if not os.environ.get("JUSTUNO_REFRESH_TOKEN"):
        print("  JUSTUNO_REFRESH_TOKEN not set — skipping.")
        return

    campaigns = camp.load()
    start_date = min(
        (c.get("launched", "2026-01-01") for c in campaigns),
        default="2026-01-01",
    )
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")

    id_token = _get_id_token()

    impressions, emails, sms, rate, revenue = [
        _fetch(id_token, dp, start_date, yesterday) for dp in DATA_POINTS
    ]

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(yesterday, "%Y-%m-%d")

    # Row 6 date label: "24th-June 11th"
    row_date = f"{_ordinal(start_dt.day)}-{end_dt.strftime('%B')} {_ordinal(end_dt.day)}"
    # Row 2 last-updated label: "Apr 24- June 11th, 2026"
    last_updated = f"{start_dt.strftime('%b')} {_ordinal(start_dt.day)}- {end_dt.strftime('%B')} {_ordinal(end_dt.day)}, {end_dt.year}"

    service = get_sheets_service()
    service.spreadsheets().values().batchUpdate(
        spreadsheetId=DESTINATION_SHEET_ID,
        body={
            "valueInputOption": "USER_ENTERED",
            "data": [
                {"range": f"{DEST_TAB}!B2",   "values": [[last_updated]]},
                {"range": f"{DEST_TAB}!A6",   "values": [[row_date]]},
                {"range": f"{DEST_TAB}!D6:H6", "values": [[
                    int(float(impressions)),
                    int(float(emails)),
                    int(float(sms)),
                    f"{float(rate) * 100:.2f}%",
                    f"${float(revenue):,.2f}",
                ]]},
            ],
        },
    ).execute()

    print(
        f"  Updated row 6: {row_date} | {int(float(impressions))} impressions, "
        f"{int(float(emails))} email, {int(float(sms))} SMS, "
        f"{float(rate)*100:.2f}%, ${float(revenue):,.2f}"
    )
