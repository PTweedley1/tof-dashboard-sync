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


def _get_sheet_id(service, spreadsheet_id, tab_name):
    """Return the numeric sheetId for a tab by name."""
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for s in meta["sheets"]:
        if s["properties"]["title"] == tab_name:
            return s["properties"]["sheetId"]
    return None


def _reset_tab_formatting(service, spreadsheet_id, sheet_id):
    """Remove all merges and reset all cell formatting to defaults."""
    full_range = {
        "sheetId": sheet_id,
        "startRowIndex": 0, "endRowIndex": 1000,
        "startColumnIndex": 0, "endColumnIndex": 26,
    }
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [
            {"unmergeCells": {"range": full_range}},
            {"updateCells": {"range": full_range, "fields": "userEnteredFormat"}},
        ]}
    ).execute()


def update_data_section(sheet_id, tab_name, data_rows, date_label=None):
    """
    Unmerge the tab, clear all values, then write a header row + data rows.
    This avoids leftover merged cells silently eating written values.
    """
    if not data_rows:
        return

    service = get_sheets_service()

    # Unmerge and clear all formatting so no leftover styles bleed through
    numeric_sheet_id = _get_sheet_id(service, sheet_id, tab_name)
    if numeric_sheet_id is not None:
        _reset_tab_formatting(service, sheet_id, numeric_sheet_id)

    # Clear all values
    service.spreadsheets().values().clear(
        spreadsheetId=sheet_id,
        range=f"{tab_name}!A:Z",
    ).execute()

    # Write header + data rows from A1
    HEADER = ["Date Range", "URL", "Sessions", "Active Users", "New Users",
              "Engagement Rate", "Avg Eng. Time (s)", "Bounce Rate",
              "Conversions", "Revenue ($)"]
    all_rows = [HEADER] + data_rows

    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"{tab_name}!A1",
        valueInputOption="USER_ENTERED",
        body={"values": all_rows},
    ).execute()
