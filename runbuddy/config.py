"""Central configuration for RunBuddy (env, constants, cities)."""

import os
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo(os.getenv("LOCAL_TZ", "America/Toronto"))
DUCKLING_URL = os.getenv("DUCKLING_URL", "http://localhost:8000/parse")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

DEFAULT_EVENING = os.getenv("DEFAULT_EVENING", "19:00")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "1eqmM0XgmAXBJlfgetFm_y6lWoGW9tHHKH_0Z91WauCk")
SHEET_RANGE = os.getenv("SHEET_RANGE", "Sheet1!A1:L999")

# Cities (can also be loaded from a sheet later)
ALLOWED_CITIES = set(os.getenv("ALLOWED_CITIES", "Scarborough,Markham,Pickering").split(","))
CITY_COORDS = {
    "Scarborough": (43.7700, -79.2500),
    "Markham":     (43.8800, -79.2700),
    "Pickering":   (43.8400, -79.0300),
}
