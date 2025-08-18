import requests
from datetime import datetime


def get_weather_forecast(lat: float, lon: float, datetime_obj: datetime) -> dict | None:
    """Fetch hourly weather forecast for a given location and datetime.

    Uses the Open-Meteo API to pull hourly data and returns the weather
    snapshot (temperature, precipitation, windspeed) at the requested time.

    :param lat: Latitude of the location.
    :param lon: Longitude of the location.
    :param datetime_obj: Target datetime (timezone-aware).
    :return: Dict with keys {"temperature", "precipitation", "windspeed"} or None if not found.
    """
    date_str = datetime_obj.strftime("%Y-%m-%d")

    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}&hourly=temperature_2m,precipitation,windspeed_10m"
        f"&start_date={date_str}&end_date={date_str}"
        f"&timezone=America/Toronto"
    )

    response = requests.get(url, timeout=5)
    data = response.json()

    times = data["hourly"]["time"]
    temps = data["hourly"]["temperature_2m"]
    rain = data["hourly"]["precipitation"]
    wind = data["hourly"]["windspeed_10m"]

    try:
        # Match requested hour exactly in the API's hourly list
        idx = times.index(datetime_obj.strftime("%Y-%m-%dT%H:00"))
    except ValueError:
        return None

    return {
        "temperature": temps[idx],
        "precipitation": rain[idx],
        "windspeed": wind[idx],
    }
