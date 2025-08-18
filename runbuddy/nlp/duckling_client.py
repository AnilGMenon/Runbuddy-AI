"""Thin HTTP client to a Duckling server for time parsing."""


# duckling_client.py
import os
from typing import Optional
from datetime import datetime
from zoneinfo import ZoneInfo
import requests

LOCAL_TZ = ZoneInfo("America/Toronto")

def parse_time(text: str, base_dt: Optional[datetime] = None, locale: str = "en_CA") -> Optional[datetime]:
    url = os.getenv("DUCKLING_URL")
    if not url:
        return None
    base_dt = (base_dt or datetime.now(LOCAL_TZ)).astimezone(LOCAL_TZ)
    base_ms = int(base_dt.timestamp() * 1000)
    try:
        r = requests.post(
            url,
            data={"text": text, "locale": locale, "tz": "America/Toronto", "reftime": str(base_ms)},
            timeout=3.0,
        )
        r.raise_for_status()
        items = r.json()
    except Exception:
        return None
    for it in items:
        if it.get("dim") != "time":
            continue
        val = it.get("value", {})
        if "value" in val:
            iso = val["value"].replace("Z","+00:00")
            dt = datetime.fromisoformat(iso)
            return dt.astimezone(LOCAL_TZ)
        if "from" in val and val["from"].get("value"):
            iso = val["from"]["value"].replace("Z","+00:00")
            dt = datetime.fromisoformat(iso)
            return dt.astimezone(LOCAL_TZ)
    return None
