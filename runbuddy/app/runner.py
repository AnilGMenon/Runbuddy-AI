"""RunBuddy orchestrator.

Pipeline:
  parse → resolve time (user time > calendar > now+1h) → load trails → weather → pick city → LLM.
This file coordinates services and ensures consistent timezone handling.
"""

from typing import Any, Dict
import datetime
from zoneinfo import ZoneInfo

from ..config import LOCAL_TZ, DEFAULT_EVENING, CITY_COORDS
from ..nlp import parser as parser_mod
from ..nlp import parser as parser_mod
from ..integrations.sheets import load_trails_from_sheet
from ..integrations.calendar import calendar_time_for_date, next_run_event_time
from ..services.weather import get_weather_forecast
from ..services.trail_filter import prefilter_trails, pick_best_city_and_weather
from ..services.recommender import get_trail_recommendation

# Ensure we can call parser regardless of the exported name
def _parse(q: str, allowed_cities: list[str]) -> Dict[str, Any]:
    if hasattr(parser_mod, 'parse_user_query'):
        return parser_mod.parse_user_query(q, allowed_cities)
    elif hasattr(parser_mod, 'parse_question'):
        return parser_mod.parse_question(q, allowed_cities)
    else:
        raise RuntimeError('No parse_* function found in nlp.parser')

def _parse_iso_to_local(iso_str: str) -> datetime.datetime:
    if not iso_str:
        return None
    dt = datetime.datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
    return dt.astimezone(LOCAL_TZ)

def _evening_default(dt: datetime.datetime) -> datetime.datetime:
    h, m = map(int, DEFAULT_EVENING.split(':'))
    return dt.replace(hour=h, minute=m, second=0, microsecond=0)

# Resolve the datetime to run using layered fallbacks.
# 1) Use parsed user time (iso) if provided
# 2) Try today's calendar run; else next scheduled run
# 3) Fallback to now+1h
def resolve_when(question: str, parsed: Dict[str, Any]):
    """resolve_when.
    :param question: str: 
    :param parsed: Dict[str: 
    :param Any]: 
    :return: 
"""
    when_dt = None
    # Step 1a: parsed time from NLP
    if parsed.get('datetime'):
        try:
            parsed_dt = datetime.datetime.fromisoformat(parsed['datetime'])
            parsed_dt = parsed_dt.replace(tzinfo=parsed_dt.tzinfo or LOCAL_TZ).astimezone(LOCAL_TZ)
            when_dt = parsed_dt
            print(f"[TIME] Using user-provided time: {when_dt.isoformat()}" )
        except Exception as e:
            print(f"[TIME] Failed to parse user time, will try calendar. Error: {e}")
            when_dt = None

    # Step 1b: calendar fallback
    if when_dt is None:
        try:
            today_dt = calendar_time_for_date(datetime.datetime.now(tz=LOCAL_TZ).date())
            if today_dt:
                when_dt = today_dt
                print(f"[CAL] Using today's calendar time: {when_dt.isoformat()}" )
            else:
                nxt = next_run_event_time()
                if nxt:
                    when_dt = nxt
                    print(f"[CAL] Using next calendar event time: {when_dt.isoformat()}" )
        except Exception as e:
            print(f"[CAL] Calendar lookup failed; will use default. Error: {e}")
            when_dt = None

    # Step 1c: last resort → now+1h
    if when_dt is None:
        when_dt = datetime.datetime.now(tz=LOCAL_TZ) + datetime.timedelta(hours=1)
        print(f"[TIME] Defaulting to now+1h: {when_dt.isoformat()}" )
    return when_dt

def answer_free_form(question: str) -> Dict[str, Any]:
    # Cities we know
    allowed_cities = list({*CITY_COORDS.keys()})
    parsed = _parse(question, allowed_cities)

    when_dt = resolve_when(question, parsed)

    trails = load_trails_from_sheet()

    # If the user specified a city, prefilter
    if parsed.get('city'):
        trails = prefilter_trails(trails, parsed['city'])

    # Weather snapshot per city
    city_weather = {}
    for city, (lat, lon) in CITY_COORDS.items():
        try:
            fc = get_weather_forecast(lat, lon, when_dt)
            if fc:
                city_weather[city] = fc
        except Exception as e:
            print(f"[WX] {city} fetch failed: {e}")

    chosen_city, weather_snapshot = pick_best_city_and_weather(city_weather)

    # Ask the LLM to choose among candidate trails using current weather snapshot.
    result = get_trail_recommendation(
        calendar_event={"start": when_dt.isoformat(), "summary": ""},
        weather_forecast=weather_snapshot or {},
        trail_conditions=trails,
    )
    if not result.get("location"):
        result["location"] = parsed.get('city') or chosen_city

    return {
        "intent": parsed.get('intent'),
        "question": question,
        "when": {"date": when_dt.date().isoformat(), "time": when_dt.strftime('%H:%M')},
        "city": parsed.get('city') or chosen_city,
        "result": result,
    }
