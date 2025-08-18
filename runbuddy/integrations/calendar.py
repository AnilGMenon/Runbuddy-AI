"""Google Calendar integration for RunBuddy.

Selects upcoming 'run/jog' events, normalizes their starts,
and provides per-date lookup with LOCAL_TZ awareness.
"""

import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo
from googleapiclient.discovery import build
from ..config import LOCAL_TZ
from .google_auth import authenticate_google_api

def get_upcoming_run_events(max_results: int = 10) -> List[Dict[str, Any]]:
    creds = authenticate_google_api()
    service = build("calendar", "v3", credentials=creds)
    now = datetime.datetime.now(tz=LOCAL_TZ).isoformat()
    events_result = service.events().list(
        calendarId='primary', timeMin=now, maxResults=max_results, singleEvents=True, orderBy='startTime'
    ).execute()
    events = events_result.get('items', [])
    run_events = []
    for event in events:
        summary = (event.get("summary") or "").lower()
        if "run" in summary or "jog" in summary:
            run_events.append(event)
    return run_events

# Heuristic: pick the earliest upcoming event among summaries containing 'run'/'jog'.
def select_next_run_event(run_events: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Select the next run event from a list of candidate events.

    :param run_events: List of Google Calendar events (dicts).
    :return: The earliest upcoming event with a valid start time, or None.
    """

    def event_start_dt(e: Dict[str, Any]) -> datetime.datetime:
        """Extract the start datetime from an event.

        :param e: Google Calendar event.
        :return: Start time as a datetime (LOCAL_TZ aware).
        """
        start = e.get("start", {})
        if "dateTime" in start:
            return datetime.datetime.fromisoformat(
                start["dateTime"].replace("Z", "+00:00")
            )
        if "date" in start:
            d = datetime.date.fromisoformat(start["date"])
            return datetime.datetime(d.year, d.month, d.day, 7, 0, tzinfo=LOCAL_TZ)
        return datetime.datetime.max.replace(tzinfo=datetime.UTC)

    return sorted(run_events, key=event_start_dt)[0] if run_events else None

def normalize_calendar_event(event: Dict[str, Any]) -> Dict[str, str]:
    start = event.get("start", {})
    start_iso = start.get("dateTime") or start.get("date") + "T00:00:00Z"
    return {"start": start_iso, "summary": event.get("summary", "")}

def calendar_time_for_date(target_date: datetime.date) -> Optional[datetime.datetime]:
    events = get_upcoming_run_events(max_results=25)
    for e in events:
        start = e.get("start", {})
        if "dateTime" in start:
            dt = datetime.datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00"))
            dt_local = dt.astimezone(LOCAL_TZ)
            if dt_local.date() == target_date:
                return dt_local
        elif "date" in start and start["date"] == target_date.isoformat():
            return datetime.datetime(target_date.year, target_date.month, target_date.day, 7, 0, tzinfo=LOCAL_TZ)
    return None

def next_run_event_time() -> Optional[datetime.datetime]:
    evts = get_upcoming_run_events(max_results=25)
    nxt = select_next_run_event(evts)
    if not nxt:
        return None
    start = normalize_calendar_event(nxt).get("start")
    if start:
        dt = datetime.datetime.fromisoformat(start.replace("Z", "+00:00"))
        return dt.astimezone(LOCAL_TZ)
    return None
