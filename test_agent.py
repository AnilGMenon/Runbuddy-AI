from llm_agent import get_trail_recommendation

calendar_event = {"date": "2025-08-15", "time": "07:00"}
weather_forecast = {"temperature": 18, "precipitation": 0, "condition": "clear"}

trail_conditions = [
    {
        "Trail Name": "Milne Dam Trails",
        "Location": "Markham",
        "Length (km)": 3.2,
        "Difficulty": "Easy",
        "Terrain Type": "Gravel / Natural",
        "Weather Sensitivity": "Low",
        "Shade Coverage": "High",
        "Mud/Rain Risk": "Low",
        "Elevation Gain": "10 m",
        "Notes & Hazards": "Some narrow bridges"
    },
    {
        "Trail Name": "Highland Creek Trail",
        "Location": "Scarborough",
        "Length (km)": 9.0,
        "Difficulty": "Easy",
        "Terrain Type": "Paved / Gravel",
        "Weather Sensitivity": "Medium",
        "Shade Coverage": "Mixed",
        "Mud/Rain Risk": "Medium",
        "Elevation Gain": "Low",
        "Notes & Hazards": "Flooding sometimes; mixed surface"
    }
]

result = get_trail_recommendation(calendar_event, weather_forecast, trail_conditions)
print(result)
