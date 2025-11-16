# /// script
# dependencies = [
#   "mcp",
#   "httpx",
#   "python-dotenv",
# ]
# ///

from typing import Any
import httpx
import json
import os
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize FastMCP server
mcp = FastMCP("location")

# Constants
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
GOOGLE_PLACES_BASE = "https://maps.googleapis.com/maps/api/place"
GOOGLE_GEOCODING_BASE = "https://maps.googleapis.com/maps/api/geocode/json"
CHAT_HISTORY_FILE = Path(__file__).parent / "chat_history.txt"


async def make_google_places_request(url: str, params: dict) -> dict[str, Any] | None:
    """Make a request to Google Places API."""
    try:
        params["key"] = GOOGLE_MAPS_API_KEY
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        print(f"Error making Google Places request: {e}")
        return None


def format_restaurant(place: dict[str, Any]) -> str:
    """Format a Google Places result into a readable string."""
    name = place.get("name", "Unknown Name")
    address = place.get("vicinity") or place.get("formatted_address", "Address not available")
    rating = place.get("rating", "No rating")
    user_ratings = place.get("user_ratings_total", 0)
    price_level = "💰" * place.get("price_level", 0) if place.get("price_level") else "Price not available"
    
    # Get cuisine types
    types = place.get("types", [])
    cuisine = ", ".join([t.replace("_", " ").title() for t in types if t != "restaurant" and t != "food" and t != "point_of_interest" and t != "establishment"])
    if not cuisine:
        cuisine = "Not specified"
    
    # Opening status
    opening_now = "Open now" if place.get("opening_hours", {}).get("open_now") else "Closed"
    
    # Get coordinates
    location = place.get("geometry", {}).get("location", {})
    lat = location.get("lat", "N/A")
    lon = location.get("lng", "N/A")
    
    return f"""
{name}
Cuisine: {cuisine}
Address: {address}
Rating: {rating}/5 ({user_ratings} reviews)
Price: {price_level}
Status: {opening_now}
Coordinates: {lat}, {lon}
"""


@mcp.tool()
async def find_restaurants(
    latitude: float,
    longitude: float,
    radius: int = 1500,
    cuisine_type: str = None
) -> str:
    """Find restaurants near a location using Google Places API.

    Args:
        latitude: Latitude of the location
        longitude: Longitude of the location
        radius: Search radius in meters (default: 1500m, ~1 mile)
        cuisine_type: Optional cuisine filter (e.g., "italian", "chinese", "indian")
    """
    if not GOOGLE_MAPS_API_KEY:
        return "Google Maps API key not configured. Please set GOOGLE_MAPS_API_KEY in .env file."
    
    # Build request parameters
    url = f"{GOOGLE_PLACES_BASE}/nearbysearch/json"
    params = {
        "location": f"{latitude},{longitude}",
        "radius": radius,
        "type": "restaurant"
    }
    
    # Add cuisine keyword if specified
    if cuisine_type:
        params["keyword"] = cuisine_type
    
    data = await make_google_places_request(url, params)
    
    if not data:
        return "Unable to fetch restaurant data from Google Places."
    
    if data.get("status") != "OK":
        return f"Error from Google Places API: {data.get('status')} - {data.get('error_message', 'Unknown error')}"
    
    results = data.get("results", [])
    
    if not results:
        cuisine_msg = f" with {cuisine_type} cuisine" if cuisine_type else ""
        return f"No restaurants found within {radius}m{cuisine_msg}."
    
    # Format restaurants (limit to top 20)
    restaurants = [format_restaurant(place) for place in results[:20]]
    
    header = f"Found {len(results)} restaurants within {radius}m:"
    if cuisine_type:
        header = f"Found {len(results)} {cuisine_type} restaurants within {radius}m:"
    
    return header + "\n---\n".join(restaurants)


@mcp.tool()
async def geocode_address(address: str) -> str:
    """Convert an address to latitude/longitude coordinates using Google Geocoding API.

    Args:
        address: Address to geocode (e.g., "10 Downing Street, London")
    """
    if not GOOGLE_MAPS_API_KEY:
        return "Google Maps API key not configured. Please set GOOGLE_MAPS_API_KEY in .env file."
    
    params = {
        "address": address,
        "key": GOOGLE_MAPS_API_KEY
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(GOOGLE_GEOCODING_BASE, params=params)
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        return f"Error geocoding address: {str(e)}"
    
    if data.get("status") != "OK":
        return f"Unable to geocode address: {data.get('status')}"
    
    results = data.get("results", [])
    if not results:
        return f"No results found for address: {address}"
    
    # Format results
    formatted_results = []
    for i, location in enumerate(results[:5], 1):
        geometry = location.get("geometry", {})
        loc = geometry.get("location", {})
        result = f"""
Result {i}:
Address: {location.get('formatted_address', 'Unknown')}
Coordinates: {loc.get('lat', 'N/A')}, {loc.get('lng', 'N/A')}
Type: {', '.join(location.get('types', ['Unknown']))}
"""
        formatted_results.append(result)
    
    return "Geocoding results:\n---\n".join(formatted_results)


@mcp.tool()
async def find_restaurants_by_address(
    address: str,
    radius: int = 1500,
    cuisine_type: str = None
) -> str:
    """Find restaurants near an address using Google Places API (combines geocoding + restaurant search).

    Args:
        address: Address to search near (e.g., "Oxford Street, London")
        radius: Search radius in meters (default: 1500m)
        cuisine_type: Optional cuisine filter (e.g., "italian", "chinese")
    """
    if not GOOGLE_MAPS_API_KEY:
        return "Google Maps API key not configured. Please set GOOGLE_MAPS_API_KEY in .env file."
    
    # First geocode the address
    params = {
        "address": address,
        "key": GOOGLE_MAPS_API_KEY
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(GOOGLE_GEOCODING_BASE, params=params)
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        return f"Error geocoding address: {str(e)}"
    
    if data.get("status") != "OK" or not data.get("results"):
        return f"Unable to find location for address: {address}"
    
    # Get coordinates from first result
    location = data["results"][0]
    geometry = location.get("geometry", {})
    loc = geometry.get("location", {})
    latitude = loc.get("lat")
    longitude = loc.get("lng")
    
    if not latitude or not longitude:
        return f"Unable to get coordinates for address: {address}"
    
    # Now search for restaurants
    result = await find_restaurants(latitude, longitude, radius, cuisine_type)
    
    header = f"Searching near: {location.get('formatted_address', address)}\n\n"
    return header + result


@mcp.tool()
async def get_chat_messages(limit: int = 50) -> str:
    """Read recent messages from the web chat.

    Args:
        limit: Maximum number of messages to return (default: 50)
    """
    try:
        if not CHAT_HISTORY_FILE.exists():
            return "No chat history found."
        
        with open(CHAT_HISTORY_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Get last N messages
        recent_lines = lines[-limit:] if len(lines) > limit else lines
        
        messages = []
        for line in recent_lines:
            try:
                msg = json.loads(line.strip())
                sender = msg.get('sender', 'Unknown')
                message = msg.get('message', '')
                messages.append(f"{sender}: {message}")
            except json.JSONDecodeError:
                continue
        
        if not messages:
            return "No messages found in chat history."
        
        return f"Recent chat messages ({len(messages)} total):\n\n" + "\n".join(messages)
    except Exception as e:
        return f"Error reading chat history: {str(e)}"


@mcp.tool()
async def analyze_food_preferences() -> str:
    """Analyze food preferences mentioned in the chat to suggest restaurants.
    
    Returns a summary of food types mentioned and user preferences.
    """
    try:
        if not CHAT_HISTORY_FILE.exists():
            return "No chat history found."
        
        with open(CHAT_HISTORY_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Keywords for food types
        food_keywords = {
            'sushi': 'japanese',
            'ramen': 'japanese',
            'pizza': 'italian',
            'pasta': 'italian',
            'steak': 'steakhouse',
            'burger': 'american',
            'chinese': 'chinese',
            'indian': 'indian',
            'thai': 'thai',
            'mexican': 'mexican',
            'korean': 'korean',
            'french': 'french',
            'seafood': 'seafood',
            'vegan': 'vegan',
            'vegetarian': 'vegetarian',
        }
        
        mentions = {}
        user_preferences = {}
        
        for line in lines:
            try:
                msg = json.loads(line.strip())
                sender = msg.get('sender', 'Unknown')
                message = msg.get('message', '').lower()
                
                # Track food mentions
                for food, cuisine in food_keywords.items():
                    if food in message:
                        mentions[food] = mentions.get(food, 0) + 1
                        
                        # Track user preferences
                        if sender not in user_preferences:
                            user_preferences[sender] = []
                        
                        # Detect sentiment
                        if any(word in message for word in ['love', 'like', 'want', 'craving', 'kill for']):
                            user_preferences[sender].append(f"likes {food}")
                        elif any(word in message for word in ['hate', 'worst', "don't like", 'dislike']):
                            user_preferences[sender].append(f"dislikes {food}")
                        else:
                            user_preferences[sender].append(f"mentioned {food}")
                            
            except json.JSONDecodeError:
                continue
        
        # Format results
        result = "Food Preference Analysis:\n\n"
        
        if mentions:
            result += "Most mentioned foods:\n"
            sorted_mentions = sorted(mentions.items(), key=lambda x: x[1], reverse=True)
            for food, count in sorted_mentions:
                result += f"  - {food}: {count} mention(s)\n"
            result += "\n"
        
        if user_preferences:
            result += "User preferences:\n"
            for user, prefs in user_preferences.items():
                result += f"  {user}:\n"
                for pref in prefs:
                    result += f"    - {pref}\n"
        else:
            result += "No clear food preferences detected in chat."
        
        return result
        
    except Exception as e:
        return f"Error analyzing preferences: {str(e)}"


if __name__ == "__main__":
    mcp.run()
