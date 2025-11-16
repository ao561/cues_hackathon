# /// script
# dependencies = [
#   "mcp",
#   "httpx",
#   "python-dotenv",
# ]
# ///

import os
from typing import Any
from pathlib import Path

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------
# Load .env from same directory as this file
# ---------------------------------------------------------
HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
if not OPENWEATHER_API_KEY:
    raise RuntimeError(
        f"OPENWEATHER_API_KEY not found.\n"
        f"Make sure {HERE / '.env'} contains:\n"
        f"OPENWEATHER_API_KEY=your_key_here"
    )

mcp = FastMCP("weather")

# One Call 3.0 base URL
OPENWEATHER_BASE_URL = "https://api.openweathermap.org/data/3.0"


async def get_onecall_data(lat: float, lon: float) -> dict[str, Any] | None:
    """
    Get current weather (and optionally forecast) using One Call 3.0.
    """
    try:
        url = f"{OPENWEATHER_BASE_URL}/onecall"
        params = {
            "lat": lat,
            "lon": lon,
            "appid": OPENWEATHER_API_KEY,
            "units": "metric",
            # we mostly care about 'current' – exclude stuff we don't need
            "exclude": "minutely,alerts",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params=params)
            # For debugging auth problems:
            if resp.status_code >= 400:
                print("OneCall error:", resp.status_code, resp.text)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        print(f"Error getting One Call data: {e}")
        return None


def is_weather_suitable_for_cycling(onecall_data: dict[str, Any]) -> tuple[bool, str]:
    """
    Determine if weather is suitable for cycling using One Call 3.0 response.
    Returns (is_suitable, reason).
    """
    if not onecall_data or "current" not in onecall_data:
        return False, "Unable to fetch current weather data"

    current = onecall_data["current"]
    weather = (current.get("weather") or [{}])[0]

    temp = current.get("temp", 0.0)            # °C (because units=metric)
    condition = (weather.get("main") or "").lower()
    wind_speed = current.get("wind_speed", 0.0)  # m/s
    rain_1h = (current.get("rain") or {}).get("1h", 0.0)
    snow_1h = (current.get("snow") or {}).get("1h", 0.0)

    reasons: list[str] = []

    if "rain" in condition or "drizzle" in condition or rain_1h > 0:
        reasons.append(
            f"raining ({rain_1h:.1f} mm in last hour)" if rain_1h > 0 else "rain expected"
        )

    if "snow" in condition or snow_1h > 0:
        reasons.append(
            f"snowing ({snow_1h:.1f} mm in last hour)" if snow_1h > 0 else "snow expected"
        )

    if "thunderstorm" in condition or "storm" in condition:
        reasons.append("thunderstorms")

    if wind_speed > 10:
        reasons.append(f"very windy ({wind_speed:.1f} m/s)")

    if temp < 0:
        reasons.append(f"freezing temperature ({temp:.1f}°C)")
    elif temp > 35:
        reasons.append(f"extremely hot ({temp:.1f}°C)")

    if reasons:
        return False, ", ".join(reasons)

    desc = (weather.get("description") or "").lower()
    return True, f"Good cycling weather ({temp:.1f}°C, {desc})"


@mcp.tool()
async def get_current_weather(location: str) -> str:
    """
    Get current weather for a location using One Call 3.0.

    Args:
        location: City name or address (e.g., "Cambridge, UK")
    """
    try:
        # Geocode via OpenWeather
        geo_url = "https://api.openweathermap.org/geo/1.0/direct"
        params = {
            "q": location,
            "limit": 1,
            "appid": OPENWEATHER_API_KEY,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            geo_resp = await client.get(geo_url, params=params)
            if geo_resp.status_code >= 400:
                print("Geo error:", geo_resp.status_code, geo_resp.text)
            geo_resp.raise_for_status()
            geo_data = geo_resp.json()

        if not geo_data:
            return f"Unable to find location: {location}"

        lat = geo_data[0]["lat"]
        lon = geo_data[0]["lon"]

        onecall_data = await get_onecall_data(lat, lon)
        if not onecall_data or "current" not in onecall_data:
            return "Unable to fetch weather data"

        current = onecall_data["current"]
        weather = (current.get("weather") or [{}])[0]

        temp = current.get("temp", "N/A")
        feels_like = current.get("feels_like", "N/A")
        humidity = current.get("humidity", "N/A")
        wind_speed = current.get("wind_speed", "N/A")
        description = (weather.get("description") or "N/A").title()

        result = f"🌍 Weather in {location}:\n\n"
        result += f"🌡️  Temperature: {temp}°C (feels like {feels_like}°C)\n"
        result += f"☁️  Conditions: {description}\n"
        result += f"💧 Humidity: {humidity}%\n"
        result += f"💨 Wind: {wind_speed} m/s\n"

        suitable, reason = is_weather_suitable_for_cycling(onecall_data)
        result += f"\n🚴 Cycling conditions: {'✅ Good' if suitable else '❌ Not recommended'}\n"
        result += f"   Reason: {reason}\n"

        return result

    except Exception as e:
        return f"Error getting weather: {e}"


@mcp.tool()
async def check_cycling_conditions(location: str) -> str:
    """
    Quick cycling suitability check for a location.
    """
    try:
        geo_url = "https://api.openweathermap.org/geo/1.0/direct"
        params = {
            "q": location,
            "limit": 1,
            "appid": OPENWEATHER_API_KEY,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            geo_resp = await client.get(geo_url, params=params)
            geo_resp.raise_for_status()
            geo_data = geo_resp.json()

        if not geo_data:
            return f"Unable to find location: {location}"

        lat = geo_data[0]["lat"]
        lon = geo_data[0]["lon"]

        onecall_data = await get_onecall_data(lat, lon)
        suitable, reason = is_weather_suitable_for_cycling(onecall_data)

        if suitable:
            return f"✅ Cycling is suitable in {location}\nReason: {reason}"
        else:
            return (
                f"❌ Cycling is NOT recommended in {location}\n"
                f"Reason: {reason}\n\n💡 Consider walking, driving, or public transport instead."
            )

    except Exception as e:
        return f"Error checking cycling conditions: {e}"


if __name__ == "__main__":
    mcp.run()
