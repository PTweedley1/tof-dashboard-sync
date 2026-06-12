import json
import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from sync.config import SCOPES


def _get_credentials():
    # GitHub Actions: credentials stored as a secret env var
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw:
        info = json.loads(raw)
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    # Local: credentials stored in file
    return service_account.Credentials.from_service_account_file(
        "service_account.json", scopes=SCOPES
    )


def get_sheets_service():
    return build("sheets", "v4", credentials=_get_credentials())


def list_sheet_tabs(sheet_id):
    service = get_sheets_service()
    meta = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    return [s["properties"]["title"] for s in meta["sheets"]]


def read_tab(sheet_id, tab_name, cell_range="A:Z"):
    service = get_sheets_service()
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=sheet_id, range=f"{tab_name}!{cell_range}")
        .execute()
    )
    return result.get("values", [])


def get_existing_dates(sheet_id, tab_name):
    rows = read_tab(sheet_id, tab_name, "A:A")
    dates = set()
    for row in rows[1:]:  # skip header
        if row:
            dates.add(row[0].strip())
    return dates


def append_rows(sheet_id, tab_name, rows):
    if not rows:
        return
    service = get_sheets_service()
    service.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range=f"{tab_name}!A:A",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": rows},
    ).execute()


def clear_and_write_rows(sheet_id, tab_name, rows):
    """Clear the tab and write rows from A1 (used for fully-refreshed tabs)."""
    if not rows:
        return
    service = get_sheets_service()
    service.spreadsheets().values().clear(
        spreadsheetId=sheet_id,
        range=f"{tab_name}!A:Z",
    ).execute()
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"{tab_name}!A1",
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()


def update_data_section(sheet_id, tab_name, data_rows, date_label=None):
    """
    Update only the data rows in a tab that has a header/title section above.

    Scans column A to find the row with 'Date' (the column header row).
    Clears everything below it and writes fresh data rows.
    Optionally updates a 'Last Updated' cell in the header section.
    """
    service = get_sheets_service()
    col_a = read_tab(sheet_id, tab_name, "A:A")

    header_row_idx = None   # 0-based index of the 'Date' column header row
    last_updated_row_idx = None  # 0-based index of the 'Last Updated' row

    for i, row in enumerate(col_a):
        val = row[0].strip().lower() if row else ""
        if val == "date" or val == "date range":
            header_row_idx = i
        if "last updated" in val:
            last_updated_row_idx = i

    if header_row_idx is None:
        # No existing structure — fall back to full overwrite starting at A1
        clear_and_write_rows(sheet_id, tab_name, data_rows)
        return

    data_start_row = header_row_idx + 2  # 1-indexed row where data begins

    # Update "Last Updated" adjacent cell (column B of that row)
    if date_label and last_updated_row_idx is not None:
        lu_cell = f"{tab_name}!B{last_updated_row_idx + 1}"
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range=lu_cell,
            valueInputOption="USER_ENTERED",
            body={"values": [[date_label]]},
        ).execute()

    # Clear old data rows and write fresh ones
    service.spreadsheets().values().clear(
        spreadsheetId=sheet_id,
        range=f"{tab_name}!A{data_start_row}:J500",
    ).execute()
    if data_rows:
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range=f"{tab_name}!A{data_start_row}",
            valueInputOption="USER_ENTERED",
            body={"values": data_rows},
        ).execute()
