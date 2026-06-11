from sync.sheets import list_sheet_tabs, read_tab, get_existing_dates, append_rows
from sync.config import TW_SHEET_ID, DESTINATION_SHEET_ID, DEST_TABS

DEST_TAB = DEST_TABS["triple_whale"]


def _clean(val):
    if isinstance(val, str):
        return val.replace("$", "").replace(",", "").replace("%", "").strip()
    return val


def _parse_rows(source_rows):
    """Parse TW sheet rows, handling both column formats the agency uses."""
    records = []
    header = None

    for row in source_rows:
        if not row or not row[0]:
            header = None  # reset on blank rows between tables
            continue

        # Detect header row
        if row[0].strip().lower() == "date":
            header = [c.strip().lower() for c in row]
            continue

        if header is None:
            continue

        try:
            date = row[0].strip()
            if not date or date.lower() == "date":
                continue

            # Two formats: with or without landing_page_campaign column
            if "landing_page_campaign" in header:
                lp_idx = header.index("landing_page_campaign")
                campaign = row[lp_idx] if len(row) > lp_idx else ""
                s = lp_idx + 1  # spend starts after landing_page_campaign
            else:
                campaign = row[1] if len(row) > 1 else ""
                s = 2  # spend starts at index 2

            if len(row) <= s + 5:
                continue

            records.append([
                date,
                campaign,
                _clean(row[s]),        # Spend ($)
                _clean(row[s + 1]),    # CPM ($)
                _clean(row[s + 2]),    # CPC ($)
                _clean(row[s + 3]),    # CTR
                _clean(row[s + 4]),    # CPA ($)
                _clean(row[s + 5]),    # ROAS
                row[s + 6] if len(row) > s + 6 else "0",  # New Customers
            ])
        except (IndexError, ValueError):
            continue

    return records


def sync():
    print("Syncing Triple Whale...")

    # Auto-discover the first tab name in the TW sheet
    tabs = list_sheet_tabs(TW_SHEET_ID)
    source_tab = tabs[0]
    print(f"  Reading from tab: '{source_tab}'")

    source_rows = read_tab(TW_SHEET_ID, source_tab)
    if not source_rows:
        print("  No data found in Triple Whale sheet.")
        return

    all_records = _parse_rows(source_rows)
    if not all_records:
        print("  No parseable rows found.")
        return

    # Only append rows with dates not already in the destination
    existing_dates = get_existing_dates(DESTINATION_SHEET_ID, DEST_TAB)
    new_rows = [r for r in all_records if r[0] not in existing_dates]

    if new_rows:
        append_rows(DESTINATION_SHEET_ID, DEST_TAB, new_rows)
        print(f"  Added {len(new_rows)} new row(s) to '{DEST_TAB}'.")
    else:
        print(f"  '{DEST_TAB}' is already up to date.")
