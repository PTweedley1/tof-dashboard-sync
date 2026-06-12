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
