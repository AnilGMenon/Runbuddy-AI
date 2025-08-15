
from typing import List, Optional, Tuple

# UI-limited cities
ALLOWED = ["Scarborough", "Markham", "Pickering"]

def get_allowed_cities() -> List[str]:
    return ALLOWED[:]

def coerce_city_to_allowed(user_city: Optional[str]) -> Tuple[Optional[str], bool]:
    """
    Returns (city_or_none, was_explicit).
    If user_city matches one of the allowed names (case-insensitive), return canonical + True.
    If user_city is None or doesn't match, return (None, False).
    """
    if not user_city:
        return (None, False)
    for c in ALLOWED:
        if c.lower() == user_city.lower():
            return (c, True)
    return (None, False)
