# llm_agent.py — Groq version
import json
import re
from typing import Any, Dict, List, Optional
import os

from groq import Groq
from prompts import TRAIL_ASSISTANT_SYSTEM_PROMPT_LITE as TRAIL_ASSISTANT_SYSTEM_PROMPT  # <- your prompt.py file

# Create Groq client (reads GROQ_API_KEY from env)
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

_REQUIRED_KEYS = ["trail_name", "location", "reason", "cautions"]

def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Extract the first JSON object from text (handles prose / code fences)."""
    # Try direct parse
    try:
        return json.loads(text)
    except Exception:
        pass
    # Fallback: find {...} block
    m = re.search(r"\{(?:[^{}]|(?R))*\}", text, flags=re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None

def _validate_model_output(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Model output is not a JSON object.")
    out: Dict[str, Any] = {}

    tn = payload.get("trail_name", None)
    out["trail_name"] = tn if (tn is None or isinstance(tn, str)) else str(tn)

    loc = payload.get("location", None)
    out["location"] = loc if (loc is None or isinstance(loc, str)) else str(loc)

    rsn = payload.get("reason", "")
    if not isinstance(rsn, str):
        rsn = str(rsn)
    if not rsn:
        raise ValueError("Model output missing 'reason'.")
    out["reason"] = rsn

    caut = payload.get("cautions", None)
    out["cautions"] = caut if (caut is None or isinstance(caut, str)) else str(caut)

    # Ensure required keys exist
    for k in _REQUIRED_KEYS:
        if k not in out:
            raise ValueError(f"Model output missing required key: {k}")

    return out

def _normalize_trails(trails: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Normalize trail records to the names used in your prompt examples.
    Accepts either your Google Sheet keys or the normalized keys.
    Preserves per-trail 'forecast' if present:
    forecast: {temperature, precipitation, condition}
    """
    normed = []
    for t in trails:
        normed.append({
            "name": t.get("name") or t.get("Trail Name"),
            "location": t.get("location") or t.get("Location"),
            "length_km": t.get("length_km") or t.get("Length (km)"),
            "difficulty": t.get("difficulty") or t.get("Difficulty"),
            "terrain_type": t.get("terrain_type") or t.get("Terrain Type"),
            "weather_sensitivity": t.get("weather_sensitivity") or t.get("Weather Sensitivity"),
            "shade_coverage": t.get("shade_coverage") or t.get("Shade Coverage"),
            "mud_rain_risk": t.get("mud_rain_risk") or t.get("Mud/Rain Risk"),
            "elevation_gain": t.get("elevation_gain") or t.get("Elevation Gain"),
            "hazards": t.get("hazards") or t.get("Notes & Hazards"),
            "forecast": t.get("forecast"),
        })
    return normed

def get_trail_recommendation(
    calendar_event: Dict[str, Any],
    weather_forecast: Dict[str, Any],
    trail_conditions: List[Dict[str, Any]],
    *,
    model: str = "llama3-70b-8192",   # or "llama3-8b-8192" for cheaper
    temperature: float = 0.2
) -> Dict[str, Any]:
    """
    Calls Groq chat with your system prompt and context.
    Returns a validated dict: { trail_name, location, reason, cautions }.
    """
    trail_conditions = _normalize_trails(trail_conditions)
    context = {
        "calendar_event": calendar_event,         # {"date": "YYYY-MM-DD", "time": "HH:MM"}
        "weather_forecast": weather_forecast,     # {"temperature": <num>, "precipitation": <num>, "condition": <str>}
        "trail_conditions": trail_conditions
    }

    print(f"ANIL CONTEXT :    {context}")

    messages = [
        {"role": "system", "content": TRAIL_ASSISTANT_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(context, ensure_ascii=False)}
    ]

    # Groq API: chat.completions
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
    )

    raw = resp.choices[0].message.content
    parsed = _extract_json(raw)
    if not parsed:
        raise ValueError("Could not extract JSON from model output.")
    return _validate_model_output(parsed)
