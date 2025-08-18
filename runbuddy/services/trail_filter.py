"""Trail prefilter and simple city+weather chooser."""

from typing import List, Dict, Tuple, Optional

def prefilter_trails(trails: List[Dict], city: Optional[str]) -> List[Dict]:
    if not city:
        return trails
    city_key = "location" if "location" in (trails[0] if trails else {}) else "Location"
    return [t for t in trails if (t.get(city_key) == city)]

def pick_best_city_and_weather(city_weather: Dict[str, Dict]) -> Tuple[Optional[str], Dict]:
    """Choose the best city based on weather snapshot.

    Heuristic:
    - Prefer lowest precipitation.
    - If tied, prefer cooler temperature.

    :param city_weather: Dict mapping city -> weather info dict.
    :return: (best_city, best_weather_dict)
    """
    if not city_weather:
        # Default fallback when no weather data is available
        return None, {"temperature": 18, "precipitation": 0, "condition": "clear"}

    items = list(city_weather.items())

    # Sort by precipitation ascending, then temperature ascending (cooler & dry preferred).
    items.sort(
        key=lambda kv: (
            kv[1].get("precipitation", 0),
            kv[1].get("temperature", 0),
        )
    )

    best_city, best_weather = items[0]
    return best_city, best_weather

