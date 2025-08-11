import os
import datetime
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
    now = datetime.datetime.utcnow().isoformat() + "Z"

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
    start = event.get("start", {})
    if "dateTime" in start:
        dt = datetime.datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00")).astimezone(LOCAL_TZ)
    elif "date" in start:
        d = datetime.date.fromisoformat(start["date"])
        dt = datetime.datetime(d.year, d.month, d.day, 7, 0, tzinfo=LOCAL_TZ)
    else:
        raise ValueError("Event missing start time")

    return {"date": dt.date().isoformat(), "time": dt.strftime("%H:%M")}, dt


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

def city_weather_for_run(dt_local: datetime.datetime) -> Dict[str, Dict[str, float | str]]:
    """
    Get weather for each city at the run time using your get_weather_forecast(lat, lon, datetime_obj).
    Returns: { city: {temperature, precipitation, condition} }
    """
    out: Dict[str, Dict[str, float | str]] = {}
    for city, (lat, lon) in CITY_COORDS.items():
        w = get_weather_forecast(lat, lon, dt_local)
        if not w:
            continue
        cond = derive_condition(w["temperature"], w["precipitation"])
        out[city] = {
            "temperature": w["temperature"],
            "precipitation": w["precipitation"],
            "condition": cond,
        }
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
    slot, dt_local = normalize_calendar_event(next_event)
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

if __name__ == "__main__":
    main()
