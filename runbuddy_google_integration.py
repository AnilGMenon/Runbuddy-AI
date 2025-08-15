import os
import datetime
import argparse
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from weather_api import get_weather_forecast 
from llm_agent import get_trail_recommendation

# ==============================
# Config
# ==============================
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]

# Set these to your sheet
SPREADSHEET_ID = "1eqmM0XgmAXBJlfgetFm_y6lWoGW9tHHKH_0Z91WauCk"
SHEET_RANGE = "Sheet1!A1:L18"  # must include your columns

LOCAL_TZ = ZoneInfo("America/Toronto")
ALLOWED_CITIES = {"Scarborough", "Markham", "Pickering"}

# Default coords (approx city centers) for representative weather snapshot
CITY_COORDS = {
    "Scarborough": (43.7700, -79.2500),
    "Markham":     (43.8800, -79.2700),
    "Pickering":   (43.8400, -79.0300),
}

# Toggle minimal safety/size prefilter (keeps it agentic; set to False to disable)
PREFILTER_ON = True
MAX_TRAILS_SENT = 8


# ==============================
# Google Auth
# ==============================
def authenticate_google_api():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return creds


# ==============================
# Calendar
# ==============================
def get_upcoming_run_events():
    creds = authenticate_google_api()
    service = build("calendar", "v3", credentials=creds)
    from datetime import UTC
    now = datetime.datetime.now(UTC).isoformat().replace("+00:00", "Z")

    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now,
            maxResults=10,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    events = events_result.get("items", [])

    run_events = []
    for event in events:
        summary = (event.get("summary") or "").lower()
        if "run" in summary or "jog" in summary:
            run_events.append(event)
    return run_events


def select_next_run_event(run_events: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    def event_start_dt(e):
        start = e.get("start", {})
        if "dateTime" in start:
            return datetime.datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00"))
        if "date" in start:
            d = datetime.date.fromisoformat(start["date"])
            return datetime.datetime(d.year, d.month, d.day, 7, 0, tzinfo=LOCAL_TZ)
        return datetime.datetime.max.replace(tzinfo=datetime.UTC)

    return sorted(run_events, key=event_start_dt)[0] if run_events else None


def normalize_calendar_event(event: Dict[str, Any]) -> Dict[str, str]:
    """
    Normalize a Google Calendar event into a simple dict with local time ISO string.

    Returns:
        {
            "start": "<LOCAL ISO datetime>",
            "summary": "<event summary or empty string>"
        }
    """
    start = event.get("start", {}) or {}
    if "dateTime" in start:
        dt = datetime.datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00")).astimezone(LOCAL_TZ)
    elif "date" in start:
        d = datetime.date.fromisoformat(start["date"])
        # Default morning time for all-day "run" entries; adjust if evening is preferred
        dt = datetime.datetime(d.year, d.month, d.day, 7, 0, tzinfo=LOCAL_TZ)
    else:
        raise ValueError("Event missing start time")

    return {
        "start": dt.isoformat(),
        "summary": (event.get("summary") or "").strip(),
    }

# ==============================
# Sheets (Trails)
# ==============================
def rows_to_dicts(header: List[str], rows: List[List[str]]) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        rec = {header[i]: (r[i] if i < len(r) else "") for i in range(len(header))}
        out.append(rec)
    return out


def load_trails_from_sheet() -> List[Dict[str, Any]]:
    creds = authenticate_google_api()
    service = build("sheets", "v4", credentials=creds)
    resp = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=SPREADSHEET_ID, range=SHEET_RANGE)
        .execute()
    )
    values = resp.get("values", [])
    if not values:
        return []

    header, *rows = values
    raw = rows_to_dicts(header, rows)

    # Only keep the 3 cities for now
    raw = [r for r in raw if (r.get("Location") or "") in ALLOWED_CITIES]

    # Normalize to keys used in prompt examples
    norm = []
    for r in raw:
        def to_float(x):
            try:
                return float(str(x).replace("km", "").strip())
            except Exception:
                return None

        norm.append({
            "name": r.get("Trail Name"),
            "location": r.get("Location"),
            "length_km": to_float(r.get("Length (km)")),
            "difficulty": r.get("Difficulty"),
            "terrain_type": r.get("Terrain Type"),
            "weather_sensitivity": r.get("Weather Sensitivity"),
            "shade_coverage": r.get("Shade Coverage"),
            "mud_rain_risk": r.get("Mud/Rain Risk"),
            "elevation_gain": r.get("Elevation Gain"),
            "hazards": r.get("Notes & Hazards"),
        })
    # Drop broken rows
    return [t for t in norm if t["name"] and t["location"]]


# ==============================
# Weather (your function)
# ==============================
def derive_condition(temp_c: float, precip_mm: float) -> str:
    # Simple label for the prompt
    if precip_mm <= 0.0:
        return "clear"
    # crude “snow” guess: <= 0°C with precip
    if temp_c <= 0 and precip_mm > 0:
        return "snow"
    if precip_mm < 2:
        return "light rain"
    return "rain"

def city_weather_for_run(dt_local: datetime.datetime) -> dict[str, dict]:
    """
    Get weather for each city at the run time using your get_weather_forecast(lat, lon, datetime_obj).
    Returns: { city: {temperature, precipitation, condition} }
    """
    out = {}
    for city, (lat, lon) in CITY_COORDS.items():
        try:
            w = get_weather_forecast(lat, lon, dt_local)
            if w:
                cond = derive_condition(w["temperature"], w["precipitation"])
                out[city] = {
                    "temperature": w["temperature"],
                    "precipitation": w["precipitation"],
                    "condition": cond,
                }
        except Exception as e:
            import traceback
            print(
                f"[WX] {city} fetch failed for {lat},{lon} at {dt_local.isoformat()} "
                f"type={type(e).__name__} repr={e!r}"
            )
            traceback.print_exc(limit=1)
    return out

def pick_representative_weather(city_weather: Dict[str, Dict[str, float | str]]) -> Dict[str, float | str]:
    """
    Choose one snapshot (lowest precip, then cooler temp) to pass to the LLM,
    keeping your current prompt schema unchanged.
    """
    if not city_weather:
        return {"temperature": 18, "precipitation": 0, "condition": "clear"}
    items = list(city_weather.items())
    items.sort(key=lambda kv: (kv[1].get("precipitation", 0), kv[1].get("temperature", 0)))
    best_city, best_weather = items[0]
    print(f"Using {best_city} weather snapshot for LLM: {best_weather}")
    return best_weather

def pick_best_city_and_weather(city_weather: dict[str, dict]) -> tuple[str, dict] | tuple[None, dict]:
    """
    Choose the city with best weather (precip asc, then temp asc).
    Returns (best_city, best_weather) or (None, fallback_weather).
    """
    if not city_weather:
        return None, {"temperature": 18, "precipitation": 0, "condition": "clear"}

    items = list(city_weather.items())
    items.sort(key=lambda kv: (kv[1].get("precipitation", 0), kv[1].get("temperature", 0)))
    best_city, best_weather = items[0]
    return best_city, best_weather

def filter_trails_to_city(trails: list[dict], city: str) -> list[dict]:
    """Keep only trails in the chosen city."""
    return [t for t in trails if (t.get("location") or t.get("Location")) == city]

# ==============================
# Minimal (optional) prefilter
# ==============================
def prefilter_trails_within_city(
    trails_in_city: list[dict],
    city_weather: dict,      # weather for the chosen city
    max_trails: int = MAX_TRAILS_SENT
) -> list[dict]:
    """
    Rank trails in the chosen city with tiny heuristics:
    - If precip > 0: penalize high mud risk.
    - If hot (>= 28C): penalize low shade.
    """
    precip = float(city_weather.get("precipitation", 0) or 0)
    temp = float(city_weather.get("temperature", 0) or 0)

    def mud_penalty(m):
        m = (m or "").lower()
        if "high" in m: return 2
        if "medium" in m: return 1
        return 0

    def shade_penalty(s):
        s = (s or "").lower()
        if "low" in s or "none" in s: return 2
        if "mixed" in s or "moderate" in s: return 1
        return 0

    scored = []
    for t in trails_in_city:
        score = 0
        if precip > 0:
            score += mud_penalty(t.get("mud_rain_risk") or t.get("Mud/Rain Risk"))
        if temp >= 28:
            score += shade_penalty(t.get("shade_coverage") or t.get("Shade Coverage"))
        scored.append((score, t))

    scored.sort(key=lambda x: x[0])
    return [t for _, t in scored][:max_trails]



# ==============================
# Main flow
# ==============================
def main():
    # 1) Calendar
    run_events = get_upcoming_run_events()
    if not run_events:
        print("No upcoming run/jog events found.")
        return
    next_event = select_next_run_event(run_events)
    slot = normalize_calendar_event(next_event)
    dt_local = _parse_iso_to_local(slot['start'])
    print("Next run slot:", slot)

    # 2) Weather: get per-city
    city_wx = city_weather_for_run(dt_local)

    # 2a) Pick the single best city AND its weather; use the same for the LLM
    best_city, weather_for_llm = pick_best_city_and_weather(city_wx)
    print(f"Best city by weather: {best_city} • Snapshot: {weather_for_llm}")

    # 3) Load all trails, then FILTER to the best city only
    all_trails = load_trails_from_sheet()
    if not all_trails:
        print("No trails loaded from sheet.")
        return

    if best_city:
        trails_in_city = filter_trails_to_city(all_trails, best_city)
    else:
        trails_in_city = all_trails  # fallback if no weather

    if not trails_in_city:
        # Fallback: if the best-city has no trails in your sheet, pick the next best city with trails
        if city_wx:
            # try next best city that actually has trails
            for city, _w in sorted(city_wx.items(), key=lambda kv: (kv[1]["precipitation"], kv[1]["temperature"])):
                alt = filter_trails_to_city(all_trails, city)
                if alt:
                    best_city = city
                    trails_in_city = alt
                    weather_for_llm = city_wx[city]
                    print(f"No trails in initial best city; using {city} instead.")
                    break

    if not trails_in_city:
        print("No trails available in any city; cannot proceed.")
        return

    # 4) (Optional) attach per-trail forecast for that city (consistent with weather_for_llm)
    for t in trails_in_city:
        t["forecast"] = {
            "temperature": weather_for_llm["temperature"],
            "precipitation": weather_for_llm["precipitation"],
            "condition": weather_for_llm["condition"],
        }

    # 5) Prefilter WITHIN that city, then call the agent
    candidates = prefilter_trails_within_city(trails_in_city, weather_for_llm, max_trails=MAX_TRAILS_SENT)

    result = get_trail_recommendation(
        calendar_event=slot,
        weather_forecast=weather_for_llm,   # matches the best city we filtered to
        trail_conditions=candidates
    )


    print("\n=== RunBuddy Recommendation ===")
    print(f"Trail:    {result.get('trail_name')}")
    print(f"Location: {result.get('location')}")
    print(f"Reason:   {result.get('reason')}")
    if result.get("cautions"):
        print(f"Cautions: {result.get('cautions')}")

#if __name__ == "__main__":
 #   main()

# --- Timezone ---
LOCAL_TZ = ZoneInfo("America/Toronto")

# --- Configurable default "evening" time if no calendar entry exists on a requested date ---
_DEFAULT_EVENING = os.getenv("RUNBUDDY_DEFAULT_EVENING", "19:00")  # HH:MM like "19:00"

# --- Helpers for time resolution logic ---
import re
_TIME_HINT_RX = re.compile(
    r"\b(\d{1,2})(?::\d{2})?\s*(am|pm)\b|\b\d{1,2}:\d{2}\b|\b\d{1,2}\s*(?:h|hr|hrs)\b|"
    r"\bnoon\b|\bmidnight\b|\bmorning\b|\bafternoon\b|\bevening\b|\bnight\b|\btonight\b",
    re.I,
)

def _has_explicit_time_phrase(text: str) -> bool:
    return bool(_TIME_HINT_RX.search(text or ""))

def _parse_iso_to_local(dt_str: str) -> datetime.datetime:
    """Handles both '...Z' and '...+00:00' ISO strings and returns LOCAL_TZ-aware datetime."""
    return datetime.datetime.fromisoformat(dt_str.replace("Z", "+00:00")).astimezone(LOCAL_TZ)

def _calendar_run_time_for_date(target_date: datetime.date) -> datetime.datetime | None:
    """
    Return the first LOCAL_TZ datetime for a 'run/jog/running' event on target_date, or None.
    Works whether get_upcoming_run_events() or get_upcoming_run_events() is implemented.
    """
    try:
        # Obtain creds if your helper needs them
        try:
            creds = authenticate_google_api()
        except Exception:
            creds = None

        events = None
        try:
            if creds is not None:
                events = get_upcoming_run_events()
        except TypeError:
            # Your helper may be a no-arg function
            events = None

        if events is None:
            events = get_upcoming_run_events()

        events = events or []
        candidates: list[datetime.datetime] = []

        for ev in events:
            slot = normalize_calendar_event(ev)  # expected -> {"start": "...", "end": "...", "summary": "..."}
            if not slot or not slot.get("start"):
                continue
            start_dt = _parse_iso_to_local(slot["start"])
            if start_dt.date() != target_date:
                continue
            summary = (slot.get("summary") or ev.get("summary") or "").lower()
            if any(k in summary for k in ("run", "running", "jog")):
                candidates.append(start_dt)

        if not candidates:
            return None

        now_local = datetime.datetime.now(tz=LOCAL_TZ)
        future = [c for c in candidates if c >= now_local]
        return min(future) if future else min(candidates)
    except Exception:
        return None
    
from nlp_utils import parse_user_query
from ui_cities import get_allowed_cities, coerce_city_to_allowed

def answer_free_form(question: str) -> dict:
    """
    End-to-end handler for a free-form natural-language question.

    TIME RESOLUTION:
      - If the user gives a time → use it.
      - If the user gives a date only → use run/jog calendar entry on that date; else evening default (19:00).
      - If no date/time → use next run/jog calendar event; else now + 1h.

    CITY RESOLUTION:
      - If the user gives a location (allowed) → use it.
      - Otherwise → choose best-weather city.

    Sheets/Weather/LLM logic are preserved.
    """
    if parse_user_query is None:
        raise RuntimeError("nlp_utils.py not available. Add it to the project.")
    if get_allowed_cities is None:
        raise RuntimeError("ui_cities.py not available. Add it to the project.")

    allowed = get_allowed_cities()

    # Parse user query (Duckling-first in your nlp_utils) with allowed city constraint
    parsed = parse_user_query(
        question,
        allowed_cities=allowed,
        now=datetime.datetime.now(tz=LOCAL_TZ),
    )

    # === 1) Determine datetime per the rules ===
    when_dt: datetime.datetime | None = None
    explicit_time = _has_explicit_time_phrase(question)

    # 1a) Use parsed datetime if present
    if parsed.get("datetime"):
        try:
            parsed_dt = datetime.datetime.fromisoformat(parsed["datetime"])
            parsed_dt = parsed_dt.replace(tzinfo=parsed_dt.tzinfo or LOCAL_TZ).astimezone(LOCAL_TZ)

            # If user didn’t give an explicit time (e.g., “tomorrow”) and parse returns 00:00,
            # consult calendar for that date; else assume evening on that date.
            if (not explicit_time) and parsed_dt.time() == datetime.time(0, 0):
                target_date = parsed_dt.date()
                cal_dt = _calendar_run_time_for_date(target_date)
                if cal_dt:
                    when_dt = cal_dt
                    print(f"[CAL] Using calendar time for {target_date}: {when_dt.isoformat()}")
                else:
                    h, m = map(int, _DEFAULT_EVENING.split(":"))
                    when_dt = parsed_dt.replace(hour=h, minute=m, second=0, microsecond=0)
                    print(f"[TIME] No calendar entry on {target_date}; using evening default {when_dt.strftime('%H:%M')}")
            else:
                when_dt = parsed_dt
                print(f"[TIME] Using user-provided time: {when_dt.isoformat()}")
        except Exception as e:
            print(f"[TIME] Failed to parse user time, will try calendar. Error: {e}")
            when_dt = None

    # 1b) If no datetime from text, use next run/jog calendar event
    if when_dt is None:
        try:
            # First try today's date specifically
            today_dt = _calendar_run_time_for_date(datetime.datetime.now(tz=LOCAL_TZ).date())
            if today_dt:
                when_dt = today_dt
                print(f"[CAL] Using today's calendar time: {when_dt.isoformat()}")
            else:
                # Otherwise consult the general upcoming list using your helpers
                try:
                    creds = authenticate_google_api()
                except Exception:
                    creds = None

                events = None
                try:
                    if creds is not None:
                        events = get_upcoming_run_events()
                except TypeError:
                    events = None
                if events is None:
                    events = get_upcoming_run_events()
                events = events or []

                # Your selector should already know how to find the next run/jog
                next_evt = select_next_run_event(events) if events else None
                if next_evt:
                    slot = normalize_calendar_event(next_evt)
                    s = (slot or {}).get("start")
                    if s:
                        when_dt = _parse_iso_to_local(s)
                        print(f"[CAL] Using next calendar event time: {when_dt.isoformat()}")
        except Exception as e:
            print(f"[CAL] Calendar lookup failed; will use default. Error: {e}")
            when_dt = None

    # 1c) Last resort → now + 1h
    if when_dt is None:
        when_dt = datetime.datetime.now(tz=LOCAL_TZ) + datetime.timedelta(hours=1)
        print(f"[TIME] Defaulting to now+1h: {when_dt.isoformat()}")

    # === 2) City resolution per the rules ===
    # If user provided a city (and parse_user_query constrained it to allowed), use it;
    # otherwise choose best-weather city.
    city_allowed = parsed.get("city")  # already constrained inside parse_user_query
    try:
        city_wx = city_weather_for_run(when_dt) or {}
    except Exception as e:
        print(f"[WX] Weather fetch failed; proceeding without snapshot. Error: {e}")
        city_wx = {}

    if city_allowed:
        chosen_city = city_allowed  # Always honor user's city if present
        weather_for_llm = city_wx.get(chosen_city)
        if weather_for_llm is None:
            # Borrow a general best-weather snapshot for the prompt if user's city snapshot missing
            try:
                _, best_wx = pick_best_city_and_weather(city_wx)
            except Exception:
                best_wx = None
            weather_for_llm = best_wx
        print(f"[CITY] Using user city: {chosen_city}")
    else:
        # User gave no city → pick best-weather city
        try:
            best_city, best_wx = pick_best_city_and_weather(city_wx)
        except Exception as e:
            print(f"[WX] Best-city selection failed. Error: {e}")
            best_city, best_wx = (None, None)
        chosen_city = best_city if best_city else (allowed[0] if allowed else "Unknown")
        weather_for_llm = best_wx or city_wx.get(chosen_city)
        print(f"[CITY] No user city → chosen best-weather: {chosen_city}")

    # Ensure weather dict exists so the LLM prompt has fields
    if not weather_for_llm:
        weather_for_llm = {"temperature": None, "precipitation": None, "condition": None}

    # === 3) Trails: load + filter; fallback if no rows for chosen city ===
    trails = load_trails_from_sheet()
    subset = filter_trails_to_city(trails, chosen_city)
    if not subset:
        for alt in allowed:
            alt_subset = filter_trails_to_city(trails, alt)
            if alt_subset:
                subset = alt_subset
                print(f"[TRAIL] No trails in {chosen_city}; falling back to {alt}")
                chosen_city = alt
                break
    if not subset:
        subset = trails  # last resort

    candidates = prefilter_trails_within_city(subset, weather_for_llm, max_trails=8)

    # Final structured slot for the agent
    slot = {"date": when_dt.date().isoformat(), "time": when_dt.strftime("%H:%M")}
    print(f"[SLOT] Final slot: {slot} • City: {chosen_city}")

    # === 4) LLM agent call (no offline flag) ===
    result = get_trail_recommendation(
        calendar_event=slot,
        weather_forecast=weather_for_llm,
        trail_conditions=candidates,
    )
    if not result.get("location"):
        result["location"] = chosen_city

    return {
        "intent": parsed.get("intent"),
        "question": question,
        "when": slot,
        "city": chosen_city,
        "result": result,
    }


# --- Single entry point (no duplicates) ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RunBuddy AI – free-form CLI")
    parser.add_argument("--ask", type=str, help="Free-form question, e.g., 'Where should I run tomorrow at 6pm?'")
    args = parser.parse_args()

    if args.ask:
        ans = answer_free_form(args.ask)
        # A compact, readable printout
        print("\n=== RunBuddy Recommendation ===")
        print(f"When:     {ans['when']['date']} {ans['when']['time']}")
        print(f"City:     {ans['city']}")
        r = ans["result"]
        print(f"Trail:    {r.get('trail_name')}")
        print(f"Reason:   {r.get('reason')}")
        if r.get("cautions"):
            print(f"Cautions: {r.get('cautions')}")