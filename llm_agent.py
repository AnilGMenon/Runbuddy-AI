from openai import OpenAI
import json
from prompts import TRAIL_ASSISTANT_SYSTEM_PROMPT

client = OpenAI()

def get_trail_recommendation(calendar_event: dict, weather_data: dict, trails_data: list):
    """
    Call the LLM with system prompt + context data to get trail recommendation.

    Args:
        calendar_event: dict with run date/time info
        weather_data: dict with weather forecast info
        trails_data: list of dicts, each with trail info

    Returns:
        str: LLM response string (usually JSON formatted recommendation)
    """
    context = {
        "calendar_event": calendar_event,
        "weather_forecast": weather_data,
        "trail_conditions": trails_data
    }

    messages = [
        {"role": "system", "content": TRAIL_ASSISTANT_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(context)}
    ]

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.3
    )

    raw_output = response.choices[0].message["content"]

    try:
        result = json.loads(raw_output)
    except json.JSONDecodeError:
        # fallback if parsing fails
        result = {
            "trail_name": None,
            "location": None,
            "reason": "Sorry, I couldn't parse the response correctly.",
            "cautions": "Please try again."
        }

    return result
