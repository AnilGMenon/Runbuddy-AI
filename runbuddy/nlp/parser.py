"""NLP parsing utilities. Duckling-first time extraction + fallbacks."""


# nlp_utils.py (Duckling-first NLP)
from typing import Optional, Dict, List
from datetime import datetime
from zoneinfo import ZoneInfo
import os, json
import dateparser
from dateparser.search import search_dates

try:
    import spacy
    _NLP = spacy.load("en_core_web_sm")
except Exception:
    _NLP = None

from .duckling_client import parse_time as duckling_time

LOCAL_TZ = ZoneInfo("America/Toronto")

try:
    from nlp_model import predict_label as ml_predict_label
except Exception:
    ml_predict_label = None

_DEF_POD = {"morning":"07:30","noon":"12:00","afternoon":"15:00","evening":"18:30","night":"21:30","tonight":"21:30","midnight":"00:00"}
try:
    _POD = {**_DEF_POD, **json.loads(os.getenv("RUNBUDDY_PART_OF_DAY","{}"))}
except Exception:
    _POD = _DEF_POD

def _to_local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(LOCAL_TZ)

def extract_city(text: str) -> Optional[str]:
    if _NLP:
        doc = _NLP(text)
        for ent in doc.ents:
            if ent.label_ in ("GPE", "LOC", "FAC"):
                return ent.text.strip()
    return None

def _part_of_day_default(text: str) -> Optional[str]:
    t = text.lower()
    for k,v in _POD.items():
        if k in t:
            return v
    return None

def extract_datetime(text: str, now: Optional[datetime] = None) -> Optional[datetime]:
    now = _to_local(now or datetime.now(LOCAL_TZ))
    dt = duckling_time(text, base_dt=now)
    if dt:
        return _to_local(dt)

    base = dateparser.parse(
        text,
        settings={
            "RELATIVE_BASE": now,
            "PREFER_DATES_FROM": "future",
            "TIMEZONE": "America/Toronto",
            "RETURN_AS_TIMEZONE_AWARE": True,
        },
    )
    if not base:
        return None
    base = _to_local(base)

    found = search_dates(
        text,
        settings={
            "RELATIVE_BASE": base,
            "PREFER_DATES_FROM": "future",
            "TIMEZONE": "America/Toronto",
            "RETURN_AS_TIMEZONE_AWARE": True,
        },
    )
    if found:
        _, candidate = found[-1]
        candidate = _to_local(candidate)
        if candidate.date() != base.date():
            candidate = candidate.replace(year=base.year, month=base.month, day=base.day)
        dt = candidate
    else:
        dt = base

    if dt == base:
        hhmm = _part_of_day_default(text)
        if hhmm:
            h, m = map(int, hhmm.split(":"))
            dt = dt.replace(hour=h, minute=m, second=0, microsecond=0)
    return _to_local(dt)

def classify_intent(text: str) -> str:
    if ml_predict_label:
        try:
            lbl = ml_predict_label(text)
            if lbl and lbl != "free_form":
                return lbl
        except Exception:
            pass
    t = text.lower()
    if "tomorrow" in t and "run" in t:
        return "where_tomorrow"
    if "today" in t and ("where should i run" in t or "what running location" in t or "which location" in t):
        return "where_today"
    return "free_form"

def parse_user_query(q: str, allowed_cities: Optional[List[str]] = None, now: Optional[datetime] = None) -> Dict:
    intent = classify_intent(q)
    dt = extract_datetime(q, now=now)

    # City constrained to allowed list (if provided)
    city_found = extract_city(q)
    city_final = None
    if allowed_cities:
        t = q.lower()
        for c in allowed_cities:
            if c.lower() in t:
                city_final = c
                break
        if not city_final and city_found and any(c.lower() == city_found.lower() for c in allowed_cities):
            city_final = next(c for c in allowed_cities if c.lower() == city_found.lower())
    else:
        city_final = city_found

    return {
        "intent": intent,
        "city": city_final,
        "datetime": (dt.isoformat() if dt else None),
        "raw": q,
    }
