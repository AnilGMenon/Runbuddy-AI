import requests
from datetime import datetime

def get_weather_forecast(lat, lon, datetime_obj):
    date_str = datetime_obj.strftime('%Y-%m-%d')

    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}&hourly=temperature_2m,precipitation,windspeed_10m"
        f"&start_date={date_str}&end_date={date_str}"
        f"&timezone=America/Toronto"
    )

    response = requests.get(url)
    data = response.json()

    times = data['hourly']['time']
    temps = data['hourly']['temperature_2m']
    rain = data['hourly']['precipitation']
    wind = data['hourly']['windspeed_10m']

    try:
        idx = times.index(datetime_obj.strftime('%Y-%m-%dT%H:00'))
    except ValueError:
        return None

    return {
        'temperature': temps[idx],
        'precipitation': rain[idx],
        'windspeed': wind[idx]
    }
