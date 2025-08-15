'''
#!/usr/bin/env python3
import argparse
import re
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dateutil import parser as dtparser  # pip install python-dateutil

# ===== import your existing helpers =====
from runbuddy_google_integration import (
    ALLOWED_CITIES,
    LOCAL_TZ,
    city_weather_for_run,
    pick_representative_weather,     # keep for compatibility if needed elsewhere
    pick_best_city_and_weather,
    load_trails_from_sheet,
    filter_trails_to_city,
    prefilter_trails_within_city,
    get_upcoming_run_events,
    select_next_run_event,
    normalize_calendar_event,
    MAX_TRAILS_SENT,
)

from llm_agent import get_trail_recommendation


# -----------------------
# NLU: parse user query
# -----------------------
INTENT_TODAY_AT_TIME = "today_at_time"
INTENT_CITY_TOMORROW_AT_TIME = "city_tomorrow_at_time"
INTENT_USE_CALENDAR = "use_calendar"

CITY_SET = {c.lower() for c in ALLOWED_CITIES}
TZ = ZoneInfo("America/Toronto")

TIME_REGEX = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.I)

def _extract_time_str(q: str):
    m = TIME_REGEX.search(q)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2)) if m.group(2) else 0
    ampm = (m.group(3) or "").lower()
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}"

def _extract_city(q: str):
    q_low = q.lower()
    for c in CITY_SET:
        if c in q_low:
            # return canonical capitalization from ALLOWED_CITIES
            for canonical in ALLOWED_CITIES:
                if canonical.lower() == c:
                    return canonical
    return None

def parse_query(question: str):
    q = question.strip()

    # 3) Use calendar?
    if re.search(r"\b(what .*location .*today|what .*go .*today|check .*calendar|from my calendar)\b", q, re.I):
        return {"intent": INTENT_USE_CALENDAR}

    # 2) I'm going to {city} tomorrow ... @ {time}
    if "tomorrow" in q.lower():
        city = _extract_city(q)
        tstr = _extract_time_str(q)
        if not tstr:
            # fallback: try to parse any time phrase; default 07:00 if none found
            tstr = "07:00"
        dt = (datetime.now(TZ) + timedelta(days=1)).replace(
            hour=int(tstr[:2]), minute=int(tstr[3:5]), second=0, microsecond=0
        )
        return {"intent": INTENT_CITY_TOMORROW_AT_TIME, "city": city, "dt": dt}

    # 1) Where should I run today at {time}?
    if "today" in q.lower() or "where should i run" in q.lower():
        tstr = _extract_time_str(q)
        if not tstr:
            # if no explicit time, try NLP parse; otherwise default 07:00
            try:
                # try to find a time phrase anywhere
                dt_parsed = dtparser.parse(q, fuzzy=True, default=datetime.now(TZ))
                tstr = dt_parsed.strftime("%H:%M")
            except Exception:
                tstr = "07:00"
        now = datetime.now(TZ)
        dt = now.replace(hour=int(tstr[:2]), minute=int(tstr[3:5]), second=0, microsecond=0)
        # if that time already passed today, assume user means next upcoming instance (today later or tomorrow morning)
        if dt < now:
            dt = dt + timedelta(days=1)
        return {"intent": INTENT_TODAY_AT_TIME, "dt": dt}

    # Fallback: try to parse any datetime in the sentence
    try:
        dt_parsed = dtparser.parse(q, fuzzy=True)
        if not dt_parsed.tzinfo:
            dt_parsed = dt_parsed.replace(tzinfo=TZ)
        return {"intent": INTENT_TODAY_AT_TIME, "dt": dt_parsed}
    except Exception:
        # Default: use calendar
        return {"intent": INTENT_USE_CALENDAR}


# -----------------------
# Core execution
# -----------------------
def run_with_dt_and_optional_city(dt_local: datetime, city: str | None, debug: bool = False):
    # 1) weather for all cities at dt
    city_wx = city_weather_for_run(dt_local)

    # If user specified a city, force that city; else pick best by weather
    if city:
        if city not in ALLOWED_CITIES:
            print(f"[warn] '{city}' is not in allowed cities {ALLOWED_CITIES}. Falling back to best weather city.")
            best_city, wx_for_llm = pick_best_city_and_weather(city_wx)
        else:
            wx_for_llm = city_wx.get(city)
            if not wx_for_llm:
                # no weather for that city (API hiccup) – fall back to best
                best_city, wx_for_llm = pick_best_city_and_weather(city_wx)
                city = best_city
    else:
        best_city, wx_for_llm = pick_best_city_and_weather(city_wx)
        city = best_city

    if not wx_for_llm:
        print("[error] Could not obtain weather. Try again.")
        sys.exit(1)

    # 2) load trails
    all_trails = load_trails_from_sheet()
    if not all_trails:
        print("[error] No trails found in your Google Sheet.")
        sys.exit(1)

    # 3) filter to city (weather-first), attach per-trail forecast (same city snapshot)
    trails_in_city = filter_trails_to_city(all_trails, city)
    if not trails_in_city:
        print(f"[error] No trails found for city '{city}'.")
        sys.exit(1)

    for t in trails_in_city:
        t["forecast"] = {
            "temperature": wx_for_llm["temperature"],
            "precipitation": wx_for_llm["precipitation"],
            "condition": wx_for_llm["condition"],
        }

    # 4) tiny within-city prefilter, then call agent
    candidates = prefilter_trails_within_city(trails_in_city, wx_for_llm, max_trails=MAX_TRAILS_SENT)

    if debug:
        import json
        print("\n[debug] Sending candidates to LLM:")
        print(json.dumps({
            "calendar_event": {"date": dt_local.date().isoformat(), "time": dt_local.strftime("%H:%M")},
            "weather_forecast": wx_for_llm,
            "trail_conditions": candidates
        }, indent=2))

    result = get_trail_recommendation(
        calendar_event={"date": dt_local.date().isoformat(), "time": dt_local.strftime("%H:%M")},
        weather_forecast=wx_for_llm,
        trail_conditions=candidates
    )

    print("\n=== RunBuddy Recommendation ===")
    print(f"Trail:    {result.get('trail_name')}")
    print(f"Location: {result.get('location')}")
    print(f"Reason:   {result.get('reason')}")
    if result.get("cautions"):
        print(f"Cautions: {result.get('cautions')}")


def run_from_calendar(debug: bool = False):
    events = get_upcoming_run_events()
    if not events:
        print("[info] No upcoming run/jog events found in your Calendar.")
        sys.exit(0)
    ev = select_next_run_event(events)
    slot, dt_local = normalize_calendar_event(ev)
    if debug:
        print(f"[debug] Next calendar slot: {slot} ({dt_local})")
    run_with_dt_and_optional_city(dt_local, city=None, debug=debug)


def main():
    ap = argparse.ArgumentParser(description="RunBuddy CLI — ask where to run.")
    ap.add_argument("question", nargs="+", help="Your question, e.g. 'Where should I run today at 6:30pm?'")
    ap.add_argument("--debug", action="store_true", help="Print the exact payload sent to the LLM")
    args = ap.parse_args()

    question = " ".join(args.question)
    parsed = parse_query(question)

    if parsed["intent"] == INTENT_USE_CALENDAR:
        run_from_calendar(debug=args.debug)
        return

    if parsed["intent"] in (INTENT_TODAY_AT_TIME, INTENT_CITY_TOMORROW_AT_TIME):
        dt_local = parsed["dt"]
        city = parsed.get("city")
        run_with_dt_and_optional_city(dt_local, city, debug=args.debug)
        return

    # Fallback
    print("[error] Couldn't understand your question. Try: \n"
          "  - Where should I run today at 6:30pm?\n"
          "  - I'm going to Markham tomorrow, where should I run at 7am?\n"
          "  - What running location do I go to today? (uses your calendar)")
    sys.exit(1)


if __name__ == "__main__":
    main()
'''