"""Domain model dataclasses used across RunBuddy."""

from dataclasses import dataclass
from typing import Optional, Dict, Any, List

@dataclass
class RunRequest:
    question: str
    city: Optional[str]
    when_iso: Optional[str]

@dataclass
class Forecast:
    temperature: float
    precipitation: float
    windspeed: float
    condition: Optional[str] = None

@dataclass
class Recommendation:
    trail_name: Optional[str]
    location: Optional[str]
    reason: str
    cautions: Optional[str] = None
