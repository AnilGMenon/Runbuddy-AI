from __future__ import print_function
import datetime
import os.path
import pickle

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from weather_api import get_weather_forecast  # Import your weather module


# Scopes for Sheets and Calendar read-only
SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly',
          'https://www.googleapis.com/auth/calendar.readonly']

def authenticate_google_api():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    return creds

def read_google_sheet(spreadsheet_id, range_name):
    creds = authenticate_google_api()
    service = build('sheets', 'v4', credentials=creds)
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=spreadsheet_id,
                                range=range_name).execute()
    values = result.get('values', [])
    if not values:
        print('No data found.')
        return []
    else:
        return values

def get_upcoming_run_events():
    creds = authenticate_google_api()
    service = build('calendar', 'v3', credentials=creds)

    now = datetime.datetime.utcnow().isoformat() + 'Z'  # 'Z' indicates UTC time
    events_result = service.events().list(calendarId='primary', timeMin=now,
                                          maxResults=10, singleEvents=True,
                                          orderBy='startTime').execute()
    events = events_result.get('items', [])

    run_events = []
    for event in events:
        summary = event.get('summary', '').lower()
        if 'run' in summary or 'jog' in summary:
            run_events.append(event)
    return run_events

def prepare_trail_data_for_ai(trail_sheet_rows):
    # trail_sheet_rows: list of dicts from Google Sheets
    filtered_trails = []
    for trail in trail_sheet_rows:
        if trail['Location'] in ['Scarborough', 'Markham', 'Pickering']:
            filtered_trails.append({
                "name": trail['Trail Name'],
                "location": trail['Location'],
                "length_km": trail.get('Length (km)'),
                "difficulty": trail.get('Difficulty'),
                "terrain_type": trail.get('Terrain Type'),
                "weather_sensitivity": trail.get('Weather Sensitivity'),
                "shade_coverage": trail.get('Shade Coverage'),
                "mud_rain_risk": trail.get('Mud/Rain Risk'),
                "elevation_gain": trail.get('Elevation Gain'),
                "access_parking": trail.get('Access & Parking'),
                "notes_hazards": trail.get('Notes & Hazards')
            })
    return filtered_trails


if __name__ == '__main__':
    # Your Google Sheet ID and range for trail data
    spreadsheet_id = '1eqmM0XgmAXBJlfgetFm_y6lWoGW9tHHKH_0Z91WauCk'
    range_name = 'Sheet1!A1:L18'

    print("Reading trail data from Google Sheet...")
    trails = read_google_sheet(spreadsheet_id, range_name)
    trails = prepare_trail_data_for_ai(trails)
    print(trails)

    print("\nFetching upcoming run events from Google Calendar...")
    runs = get_upcoming_run_events()
    for run in runs:
        print(run['summary'], run['start']['dateTime'])

    # Example: Use the first upcoming run event time for weather fetch
    if runs:
        run_start_str = runs[0]['start'].get('dateTime') or runs[0]['start'].get('date')
        run_time = datetime.datetime.fromisoformat(run_start_str)
    else:
        # Default to 5 PM today if no events found
        now = datetime.datetime.now()
        run_time = now.replace(hour=17, minute=0, second=0, microsecond=0)

    locations = {
        "Scarborough": (43.7767, -79.2318),
        "Markham": (43.8561, -79.3370),
        "Pickering": (43.8356, -79.0865)
    }

    print(f"\nFetching weather data for planned run time: {run_time}")

    weather_data = {}
    for city, (lat, lon) in locations.items():
        weather = get_weather_forecast(lat, lon, run_time)
        weather_data[city] = weather

    print(weather_data)

    from llm_agent import get_trail_recommendation

    # Assuming you already have these variables ready:
    # calendar_event = {...}
    # weather_data = {...}
    # trails_data = [...]

    recommendation = get_trail_recommendation(calendar_event, weather_data, trails_data)

    print("Trail Recommendation from AI:")
    print(recommendation)


