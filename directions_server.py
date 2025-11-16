# /// script
# dependencies = [
#   "mcp",
#   "httpx",
#   "python-dotenv",
# ]
# ///

import os
from typing import Any
import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Load environment variables
load_dotenv()
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")

if not GOOGLE_MAPS_API_KEY:
    raise ValueError("GOOGLE_MAPS_API_KEY not found in .env file")

# Initialize FastMCP server
mcp = FastMCP("directions")

# Hardcoded user addresses
USER_ADDRESSES = {
    "Alice": "Sidney Sussex College, Cambridge, UK",
    "Bob": "Trinity College, Cambridge, UK",
    "Charlie": "King's College, Cambridge, UK",
}

GOOGLE_DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
OPENWEATHER_BASE_URL = "https://api.openweathermap.org/data/2.5"


async def get_weather_data(lat: float, lon: float) -> dict[str, Any] | None:
    """Get current weather data."""
    if not OPENWEATHER_API_KEY:
        return None
        
    try:
        url = f"{OPENWEATHER_BASE_URL}/weather"
        params = {
            "lat": lat,
            "lon": lon,
            "appid": OPENWEATHER_API_KEY,
            "units": "metric"
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        print(f"Error getting weather: {e}")
        return None


def is_weather_suitable_for_mode(weather_data: dict[str, Any], mode: str) -> tuple[bool, str]:
    """Check if weather is suitable for travel mode."""
    if not weather_data:
        return True, "Weather data unavailable"
    
    main = weather_data.get("main", {})
    weather = weather_data.get("weather", [{}])[0]
    wind = weather_data.get("wind", {})
    rain = weather_data.get("rain", {})
    
    condition = weather.get("main", "").lower()
    wind_speed = wind.get("speed", 0)
    rain_1h = rain.get("1h", 0)
    
    if mode == "bicycling":
        reasons = []
        if "rain" in condition or rain_1h > 0:
            reasons.append("raining")
        if "snow" in condition:
            reasons.append("snowing")
        if "thunderstorm" in condition:
            reasons.append("thunderstorms")
        if wind_speed > 10:
            reasons.append(f"very windy ({wind_speed:.1f} m/s)")
        
        if reasons:
            return False, f"Not suitable for cycling: {', '.join(reasons)}"
        return True, "Good cycling weather"
    
    elif mode == "walking":
        if "thunderstorm" in condition or "storm" in condition:
            return False, "Thunderstorms - not safe for walking"
        if rain_1h > 5:
            return False, f"Heavy rain ({rain_1h:.1f}mm)"
        return True, "Suitable for walking"
    
    return True, f"Weather doesn't significantly affect {mode}"


async def get_directions(origin: str, destination: str, mode: str = "driving") -> dict[str, Any] | None:
    """Get directions from Google Maps API."""
    try:
        params = {
            "origin": origin,
            "destination": destination,
            "mode": mode,
            "departure_time": "now",
            "key": GOOGLE_MAPS_API_KEY
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(GOOGLE_DIRECTIONS_URL, params=params)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        print(f"Error getting directions: {e}")
        return None


def format_directions(directions_data: dict[str, Any], person_name: str, weather_warning: str = None) -> str:
    """Format directions into readable text."""
    if directions_data.get("status") != "OK":
        return f"Unable to get directions for {person_name}: {directions_data.get('status')}"
    
    route = directions_data["routes"][0]
    leg = route["legs"][0]
    
    result = f"\n{'='*60}\n"
    result += f"{person_name}'s Route\n"
    result += f"{'='*60}\n"
    
    if weather_warning:
        result += f"⚠️  {weather_warning}\n\n"
    
    result += f"📍 From: {leg['start_address']}\n"
    result += f"📍 To: {leg['end_address']}\n"
    result += f"📏 Distance: {leg['distance']['text']}\n"
    result += f"⏱️  Duration: {leg['duration']['text']}\n"
    
    if "duration_in_traffic" in leg:
        result += f"🚗 Duration in current traffic: {leg['duration_in_traffic']['text']}\n"
    
    result += f"\n📋 Step-by-step directions:\n"
    for i, step in enumerate(leg["steps"], 1):
        instruction = step["html_instructions"].replace("<b>", "**").replace("</b>", "**")
        instruction = instruction.replace("<div style=\"font-size:0.9em\">", "\n   ").replace("</div>", "")
        result += f"\n{i}. {instruction}\n   ({step['distance']['text']})\n"
    
    return result


@mcp.tool()
async def get_group_directions(
    restaurant_name_or_address: str,
    travel_mode: str = "walking"
) -> str:
    """Get directions for all group members to a destination.
    
    Args:
        restaurant_name_or_address: Restaurant address or name
        travel_mode: driving, walking, bicycling, or transit (default: walking)
    """
    results = []
    results.append(f"\n🗺️  GROUP DIRECTIONS TO: {restaurant_name_or_address}")
    results.append(f"🚶 Travel mode: {travel_mode.upper()}\n")
    
    for person, address in USER_ADDRESSES.items():
        directions = await get_directions(address, restaurant_name_or_address, travel_mode)
        
        if directions:
            formatted = format_directions(directions, person, None)
            results.append(formatted)
        else:
            results.append(f"\n❌ Unable to get directions for {person}")
    
    return "\n".join(results)


@mcp.tool()
async def get_group_directions_with_weather(
    restaurant_name_or_address: str,
    travel_mode: str = "driving"
) -> str:
    """Get directions for all group members with weather-aware recommendations.
    
    Args:
        restaurant_name_or_address: Restaurant address
        travel_mode: driving, walking, bicycling, or transit
    """
    results = []
    results.append(f"\n🗺️  GROUP DIRECTIONS TO: {restaurant_name_or_address}")
    results.append(f"🚶 Travel mode: {travel_mode.upper()}\n")
    
    # Get weather for destination
    try:
        geo_url = "http://api.openweathermap.org/geo/1.0/direct"
        params = {
            "q": restaurant_name_or_address,
            "limit": 1,
            "appid": OPENWEATHER_API_KEY
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            geo_response = await client.get(geo_url, params=params)
            geo_data = geo_response.json()
            
            weather_data = None
            if geo_data:
                lat = geo_data[0]["lat"]
                lon = geo_data[0]["lon"]
                weather_data = await get_weather_data(lat, lon)
                
                if weather_data:
                    suitable, reason = is_weather_suitable_for_mode(weather_data, travel_mode)
                    if not suitable:
                        results.append(f"⚠️  WEATHER WARNING: {reason}")
                        results.append(f"💡 Consider using a different travel mode\n")
    except:
        pass
    
    for person, address in USER_ADDRESSES.items():
        directions = await get_directions(address, restaurant_name_or_address, travel_mode)
        
        weather_warning = None
        if weather_data and travel_mode in ["bicycling", "walking"]:
            suitable, reason = is_weather_suitable_for_mode(weather_data, travel_mode)
            if not suitable:
                weather_warning = reason
        
        if directions:
            formatted = format_directions(directions, person, weather_warning)
            results.append(formatted)
        else:
            results.append(f"\n❌ Unable to get directions for {person}")
    
    return "\n".join(results)


@mcp.tool()
async def get_travel_time_summary(restaurant_name_or_address: str) -> str:
    """Get travel time summary for all group members."""
    results = []
    results.append(f"⏱️  TRAVEL TIME SUMMARY TO: {restaurant_name_or_address}\n")
    
    for person, address in USER_ADDRESSES.items():
        directions = await get_directions(address, restaurant_name_or_address, "driving")
        
        if directions and directions.get("status") == "OK":
            leg = directions["routes"][0]["legs"][0]
            duration = leg["duration"]["text"]
            distance = leg["distance"]["text"]
            
            if "duration_in_traffic" in leg:
                traffic_duration = leg["duration_in_traffic"]["text"]
                results.append(f"{person}: {distance} - {traffic_duration} (with traffic) / {duration} (normal)")
            else:
                results.append(f"{person}: {distance} - {duration}")
        else:
            results.append(f"{person}: Unable to calculate")
    
    return "\n".join(results)


@mcp.tool()
async def list_group_members() -> str:
    """List all group members and their addresses."""
    result = "👥 GROUP MEMBERS:\n\n"
    for person, address in USER_ADDRESSES.items():
        result += f"{person}: {address}\n"
    return result


if __name__ == "__main__":
    mcp.run()
