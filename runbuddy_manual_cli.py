
# runbuddy_manual_cli.py
# Manual Ask Mode for RunBuddy — uses your existing Google Sheets & Groq agent
import sys
import datetime
from typing import Optional, Dict, Any, List
from zoneinfo import ZoneInfo

from nlp_utils import parse_user_query
from ui_cities import get_allowed_cities, coerce_city_to_allowed

# Reuse your existing pipeline utilities
from runbuddy_google_integration import (
    LOCAL_TZ,
    load_trails_from_sheet,
    city_weather_for_run,
    pick_best_city_and_weather,
    filter_trails_to_city,
    prefilter_trails_within_city,
)
from llm_agent import get_trail_recommendation

ALLOWED = get_allowed_cities()

def _ensure_localized(dt: datetime.datetime, tz: ZoneInfo) -> datetime.datetime:
    # If naive, assume local tz
    return dt.replace(tzinfo=tz) if dt.tzinfo is None else dt.astimezone(tz)

def _choose_dt_from_query(parsed: Dict[str, Any]) -> datetime.datetime:
    # Prefer user-specified datetime; else, default to now+1h
    if parsed.get("datetime"):
        dt = datetime.datetime.fromisoformat(parsed["datetime"])
        return _ensure_localized(dt, LOCAL_TZ)
    return _ensure_localized(datetime.datetime.now() + datetime.timedelta(hours=1), LOCAL_TZ)

def _pick_city_and_weather(dt_local: datetime.datetime, user_city: Optional[str]) -> tuple[str, Dict[str, Any]]:
    # Always gather weather for all cities (so we can fall back if needed)
    city_wx = city_weather_for_run(dt_local)

    if user_city:
        # Use user city if allowed; if this city's weather snapshot is missing, fall back to global best
        if user_city in city_wx:
            return user_city, city_wx[user_city]
        best_city, best_wx = pick_best_city_and_weather(city_wx)
        return (best_city or ALLOWED[0]), best_wx

    # No explicit city -> choose the best by weather
    best_city, best_wx = pick_best_city_and_weather(city_wx)
    return (best_city or ALLOWED[0]), best_wx

def _select_trails_for_city(all_trails: List[Dict[str, Any]], city: str, fallback_weather: Dict[str, Any]) -> tuple[List[Dict[str, Any]], str, Dict[str, Any]]:
    # Try chosen city first
    subset = filter_trails_to_city(all_trails, city)
    if subset:
        return subset, city, fallback_weather

    # Fall back to any city that actually has trails
    # We don't want to block if sheet lacks rows for the chosen city.
    for alt in ALLOWED:
        alt_subset = filter_trails_to_city(all_trails, alt)
        if alt_subset:
            return alt_subset, alt, fallback_weather

    # As a last resort, use all trails
    return all_trails, city, fallback_weather

def answer_query(q: str) -> Dict[str, Any]:
    parsed = parse_user_query(q, now=datetime.datetime.now(tz=LOCAL_TZ))

    # Constrain city hint to UI-allowed list, but do NOT verify against the sheet
    city_hint = parsed.get("city_hint")
    city_allowed, was_explicit = coerce_city_to_allowed(city_hint)

    # Choose datetime
    dt_local = _choose_dt_from_query(parsed)

    # Pick city & weather (respect user city if provided, else best-by-weather)
    chosen_city, weather_for_llm = _pick_city_and_weather(dt_local, city_allowed)

    # Load trails
    all_trails = load_trails_from_sheet()
    if not all_trails:
        raise RuntimeError("No trails loaded from Google Sheet. Check your sheet ID/range/credentials.")

    # Filter to chosen city; if none available for that city, fall back gracefully
    trails_in_city, final_city, weather_for_llm = _select_trails_for_city(all_trails, chosen_city, weather_for_llm)

    # Attach the same weather snapshot to each candidate (consistent with your existing agent prompt)
    for t in trails_in_city:
        t["forecast"] = {
            "temperature": weather_for_llm.get("temperature"),
            "precipitation": weather_for_llm.get("precipitation"),
            "condition": weather_for_llm.get("condition"),
        }

    # Light prefilter (keeps prompt small and relevant)
    candidates = prefilter_trails_within_city(trails_in_city, weather_for_llm, max_trails=8)

    # Call your Groq agent
    slot = {
        "date": dt_local.date().isoformat(),
        "time": dt_local.strftime("%H:%M"),
    }
    result = get_trail_recommendation(
        calendar_event=slot,
        weather_forecast=weather_for_llm,
        trail_conditions=candidates,
    )

    # Ensure location is consistent if model leaves it empty
    if not result.get("location"):
        result["location"] = final_city

    return {
        "intent": parsed.get("intent"),
        "city": final_city,
        "when": slot,
        "result": result,
    }

def main():
    print("RunBuddy — Manual Ask Mode")
    print(f"Valid cities: {', '.join(ALLOWED)}")
    print("Ask things like:")
    print("  • Where should I run today at 6:30pm?")
    print("  • I'm going to Markham tomorrow morning, where should I run?")
    print("  • What running location do I go to today?")

    while True:
        q = input("\nAsk me (or 'quit'): ").strip()
        if q.lower() in {"q", "quit", "exit"}:
            print("Bye! 🏃‍♂️")
            break
        try:
            ans = answer_query(q)
            res = ans["result"]
            print("\n=== RunBuddy Recommendation ===")
            print(f"Trail:    {res.get('trail_name')}")
            print(f"Location: {res.get('location')}")
            print(f"When:     {ans['when']['date']} {ans['when']['time']}")
            print(f"Reason:   {res.get('reason')}")
            if res.get('cautions'):
                print(f"Cautions: {res.get('cautions')}")
        except Exception as e:
            print(f"[Error] {e}")

if __name__ == "__main__":
    main()
