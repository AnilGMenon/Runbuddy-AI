
from typing import List, Optional, Tuple

# UI-limited cities
ALLOWED = ["Scarborough", "Markham", "Pickering"]

def get_allowed_cities() -> List[str]:
    return ALLOWED[:]