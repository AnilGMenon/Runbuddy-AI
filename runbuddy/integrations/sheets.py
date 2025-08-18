"""Google Sheets integration for loading trail rows as dicts."""

from typing import Any, Dict, List
from googleapiclient.discovery import build
from .google_auth import authenticate_google_api
from ..config import GOOGLE_SHEET_ID, SHEET_RANGE

def load_trails_from_sheet() -> List[Dict[str, Any]]:
    creds = authenticate_google_api()
    service = build('sheets', 'v4', credentials=creds)
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=GOOGLE_SHEET_ID, range=SHEET_RANGE).execute()
    rows = result.get('values', [])

    if not rows:
        return []

    headers = rows[0]
    trails: List[Dict[str, Any]] = []
    for r in rows[1:]:
        item = {headers[i]: (r[i] if i < len(r) else None) for i in range(len(headers))}
        trails.append(item)
    return trails
