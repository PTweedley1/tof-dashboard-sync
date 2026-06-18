"""
Pull all TOF campaign orders from Shopify API and write to Master_Orders tab.

Replaces the manual CSV export workflow (April_26 CSV, Beauty_Listicles CSV,
Recharge CSV, TOF emails CSV) entirely.

Usage:
    python3 -m sync.shopify_orders
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


def fetch_tof_orders():
    url = (
        f"https://{SHOPIFY_SHOP}/admin/api/2024-01/orders.json"
        f"?status=any&limit=250&created_at_min={CAMPAIGN_START}&fields={FIELDS}"
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


def sync():
    print("Fetching TOF orders from Shopify API...")
    orders = fetch_tof_orders()

    rows = [build_row(o) for o in orders]
    rows.sort(key=lambda r: (r[1], r[0]))  # sort by date, order name

    from collections import Counter
    concepts  = Counter(r[2] for r in rows)
    channels  = Counter(r[7] for r in rows)
    ctypes    = Counter(r[5] for r in rows)
    total_net = sum(r[11] for r in rows)
    print(f"  Concepts:  {dict(concepts)}")
    print(f"  Channel:   {dict(channels)}")
    print(f"  Cust type: {dict(ctypes)}")
    print(f"  Net Sales: ${total_net:,.2f}")

    header = [
        "Order Name", "Order Date", "Page Concept", "Customer Email", "Order Tag",
        "Customer Type", "Codes Applied", "Channel", "Units", "Gross ($)", "Discount ($)", "Net Sales ($)",
    ]

    svc = get_sheets_service()
    svc.spreadsheets().values().clear(
        spreadsheetId=DESTINATION_SHEET_ID,
        range="'Master_Orders'!A:L",
    ).execute()

    svc.spreadsheets().values().update(
        spreadsheetId=DESTINATION_SHEET_ID,
        range="'Master_Orders'!A1",
        valueInputOption="USER_ENTERED",
        body={"values": [header] + rows},
    ).execute()

    print(f"  Master_Orders updated — {len(rows)} rows written.")


if __name__ == "__main__":
    sync()
