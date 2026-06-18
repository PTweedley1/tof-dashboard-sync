"""
Import Justuno per-URL data from a CSV export into Master_Justuno.

Usage:
    python3 -m sync.justuno_csv ~/Downloads/"Custom TOF By Landing URL.csv"

The CSV must be a Justuno "Custom TOF By Landing URL" export with columns:
    Session Landing Url, Impressions, Email opt ins, SMS opt ins,
    Total Opt In Rate, Influenced Revenue

Writes aggregated totals to Master_Justuno rows 4-10 (one row per known page slug).
"""

import csv
import re
import sys
from collections import defaultdict

from sync.config import DESTINATION_SHEET_ID
from sync.sheets import get_sheets_service

# Pages in the exact order they appear in Master_Justuno rows 4-10.
# Use a list (not a dict) so order is deterministic and matching is exact.
PAGE_ORDER = [
    "/pages/problem-absorption-av1",
    "/pages/problem-absorption-av2",
    "/pages/proof-outcome-av1",
    "/pages/proof-outcome-av2",
    "/pages/authority-delivery-a",
    "/pages/authority-delivery-av2",
    "/pages/5-reasons-your-skin-is-not-improving",
]

# Set for O(1) exact lookup
KNOWN_SLUGS = set(PAGE_ORDER)


def _extract_slug(raw_url: str) -> str:
    """Strip scheme, domain, query params and hash; return bare path slug."""
    url = re.sub(r"^https?://", "", raw_url.strip())
    url = re.sub(r"^[^/]+", "", url)            # remove domain
    path = re.split(r"[?#]", url)[0].rstrip("/")
    return path


def _safe_int(v: str) -> int:
    try:
        return int(str(v).strip().replace(",", ""))
    except ValueError:
        return 0


def _safe_float(v: str) -> float:
    try:
        return float(str(v).strip().replace(",", "").replace("%", ""))
    except ValueError:
        return 0.0


def aggregate(csv_path: str) -> dict:
    totals = defaultdict(lambda: {"impr": 0, "email": 0, "sms": 0, "rev": 0.0})
    skipped = 0

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            slug = _extract_slug(row.get("Session Landing Url", ""))
            if slug not in KNOWN_SLUGS:
                skipped += 1
                continue
            totals[slug]["impr"]  += _safe_int(row.get("Impressions", 0))
            totals[slug]["email"] += _safe_int(row.get("Email opt ins", 0))
            totals[slug]["sms"]   += _safe_int(row.get("SMS opt ins", 0))
            totals[slug]["rev"]   += _safe_float(row.get("Influenced Revenue", 0))

    print(f"  Skipped {skipped:,} rows (non-TOF pages)")
    return totals


def write_to_sheet(totals: dict):
    svc = get_sheets_service()
    values = []
    for slug in PAGE_ORDER:
        v = totals[slug]
        rate = (v["email"] + v["sms"]) / v["impr"] if v["impr"] else 0.0
        values.append([v["impr"], v["email"], v["sms"], round(rate, 4), round(v["rev"], 2)])

    svc.spreadsheets().values().update(
        spreadsheetId=DESTINATION_SHEET_ID,
        range="'Master_Justuno'!F4:J10",
        valueInputOption="USER_ENTERED",
        body={"values": values},
    ).execute()


def sync(csv_path: str | None = None):
    if csv_path is None:
        if len(sys.argv) < 2:
            raise SystemExit("Usage: python3 -m sync.justuno_csv <path/to/export.csv>")
        csv_path = sys.argv[1]

    print(f"Importing Justuno CSV: {csv_path}")
    totals = aggregate(csv_path)

    print("\n  Per-URL totals:")
    grand = {"impr": 0, "email": 0, "sms": 0, "rev": 0.0}
    for slug in PAGE_ORDER:
        v = totals[slug]
        rate = (v["email"] + v["sms"]) / v["impr"] if v["impr"] else 0.0
        print(f"    {slug:<44}  impr={v['impr']:>6,}  email={v['email']:>4}  sms={v['sms']:>3}  rate={rate:.1%}  rev=${v['rev']:>8,.2f}")
        for k in grand:
            grand[k] += v[k]
    tot_rate = (grand["email"] + grand["sms"]) / grand["impr"] if grand["impr"] else 0.0
    print(f"    {'TOTAL':<44}  impr={grand['impr']:>6,}  email={grand['email']:>4}  sms={grand['sms']:>3}  rate={tot_rate:.1%}  rev=${grand['rev']:>8,.2f}")

    write_to_sheet(totals)
    print("\n  Master_Justuno updated (rows 4-10, cols F-J).")


if __name__ == "__main__":
    sync()
