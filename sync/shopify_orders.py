"""
Pull TOF campaign orders from Shopify API and write to Master_Orders tab.

By default runs in INCREMENTAL mode: reads the last date already in the sheet
and only fetches new orders from that date forward, then appends them.

Usage:
    python3 -m sync.shopify_orders           # incremental (default)
    python3 -m sync.shopify_orders --full    # full rebuild from campaign start
"""

import os
import time
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from sync.config import DESTINATION_SHEET_ID, SHOPIFY_SHOP, SHOPIFY_TOKEN
from sync.sheets import get_sheets_service

CAMPAIGN_START = "2026-04-24"

TOF_CONCEPT_MAP = {
    "TOF_APRIL2026--ProblemAndAbsorption": "PA",
    "TOF_APRIL2026--ProofAndOutcome":      "PO",
    "TOF_APRIL2026--AuthorityAndDelivery": "AD",
    "TOF_JUN26_BEAUTY_LISTICLES_LP":       "LIS",
    "TOF_APRIL2026--Listicle":             "LIS",
}

HEADERS = {
    "X-Shopify-Access-Token": SHOPIFY_TOKEN,
}

FIELDS = ",".join([
    "id", "name", "email", "created_at", "tags",
    "note_attributes", "customer", "line_items", "discount_applications",
])


def get_last_sheet_date(svc):
    """Return the latest Order Date already in the sheet, or CAMPAIGN_START if empty."""
    result = svc.spreadsheets().values().get(
        spreadsheetId=DESTINATION_SHEET_ID,
        range="'Master_Orders'!B:B",
    ).execute()
    dates = [r[0] for r in result.get("values", [])[1:] if r and r[0] >= CAMPAIGN_START]
    return max(dates) if dates else CAMPAIGN_START


def get_existing_order_names(svc):
    """Return set of order names already in the sheet."""
    result = svc.spreadsheets().values().get(
        spreadsheetId=DESTINATION_SHEET_ID,
        range="'Master_Orders'!A:A",
    ).execute()
    return {r[0] for r in result.get("values", [])[1:] if r}


def fetch_tof_orders(since_date):
    url = (
        f"https://{SHOPIFY_SHOP}/admin/api/2024-01/orders.json"
        f"?status=any&limit=250&created_at_min={since_date}&fields={FIELDS}"
    )

    matched = []
    total_checked = 0

    while url:
        resp = requests.get(url, headers=HEADERS)

        if resp.status_code == 429:
            print("  Rate limited — waiting 2s...")
            time.sleep(2)
            continue

        batch = resp.json().get("orders", [])
        total_checked += len(batch)

        for o in batch:
            for attr in o.get("note_attributes", []):
                if attr["name"] == "order-tag" and attr["value"] in TOF_CONCEPT_MAP:
                    o["_tof_tag"] = attr["value"]
                    matched.append(o)
                    break

        if total_checked % 5000 == 0:
            print(f"  Checked {total_checked:,} orders, {len(matched)} TOF matches so far...")

        link = resp.headers.get("Link", "")
        url = None
        if 'rel="next"' in link:
            for part in link.split(","):
                if 'rel="next"' in part:
                    url = part.strip().split(";")[0].strip().strip("<>")

        time.sleep(0.5)

    print(f"  Done — checked {total_checked:,} orders, found {len(matched)} TOF orders")
    return matched


def build_row(order):
    tof_tag    = order["_tof_tag"]
    concept    = TOF_CONCEPT_MAP[tof_tag]
    order_date = order["created_at"][:10]
    email      = (order.get("email") or "").lower().strip()

    # Channel: Subscription tag present = subscription order
    order_tags = order.get("tags", "")
    channel = "Subscription" if "Subscription" in order_tags else "One-Time"

    # Customer type: new if customer account created on/after campaign start
    customer   = order.get("customer") or {}
    cust_created = customer.get("created_at", "")
    if cust_created:
        cust_type = "New" if cust_created[:10] >= CAMPAIGN_START else "Returning"
    else:
        cust_type = "New"  # guest checkout = no prior account

    # Financials
    gross = discount = units = 0.0
    for li in order.get("line_items", []):
        qty  = float(li.get("quantity", 1) or 1)
        price = float(li.get("price", 0) or 0)
        disc  = float(li.get("total_discount", 0) or 0)
        gross    += price * qty
        discount += disc
        units    += qty
    net = gross - discount

    # Codes applied
    codes = []
    for da in order.get("discount_applications", []):
        title = da.get("title") or da.get("code") or ""
        if title and title not in codes:
            codes.append(title)
    codes_str = " + ".join(codes)

    return [
        order["name"],
        order_date,
        concept,
        email,
        tof_tag,
        cust_type,
        codes_str,
        channel,
        int(units),
        round(gross, 2),
        round(discount, 2),
        round(net, 2),
    ]


def sync(full=False):
    import sys
    from collections import Counter

    svc = get_sheets_service()

    if full:
        since_date = CAMPAIGN_START
        print(f"Full rebuild from {CAMPAIGN_START}...")
    else:
        since_date = get_last_sheet_date(svc)
        print(f"Incremental update — fetching orders from {since_date} onwards...")

    orders = fetch_tof_orders(since_date)
    new_rows = [build_row(o) for o in orders]
    new_rows.sort(key=lambda r: (r[1], r[0]))

    if full:
        header = [
            "Order Name", "Order Date", "Page Concept", "Customer Email", "Order Tag",
            "Customer Type", "Codes Applied", "Channel", "Units", "Gross ($)", "Discount ($)", "Net Sales ($)",
        ]
        svc.spreadsheets().values().clear(
            spreadsheetId=DESTINATION_SHEET_ID,
            range="'Master_Orders'!A:L",
        ).execute()
        svc.spreadsheets().values().update(
            spreadsheetId=DESTINATION_SHEET_ID,
            range="'Master_Orders'!A1",
            valueInputOption="USER_ENTERED",
            body={"values": [header] + new_rows},
        ).execute()
        added = len(new_rows)
    else:
        # Filter out orders already in the sheet
        existing = get_existing_order_names(svc)
        to_add = [r for r in new_rows if r[0] not in existing]
        added = len(to_add)

        if to_add:
            svc.spreadsheets().values().append(
                spreadsheetId=DESTINATION_SHEET_ID,
                range="'Master_Orders'!A:L",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": to_add},
            ).execute()

    concepts = Counter(r[2] for r in new_rows)
    print(f"  Concepts found: {dict(concepts)}")
    print(f"  New rows added: {added}")
    print(f"  Master_Orders updated.")


if __name__ == "__main__":
    import sys
    sync(full="--full" in sys.argv)
