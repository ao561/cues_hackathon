# /// script
# dependencies = [
#   "mcp",
#   "httpx",
# ]
# ///

from typing import Any
import httpx
import json
from pathlib import Path
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("location")

# Constants
OVERPASS_API_BASE = "https://overpass-api.de/api/interpreter"
NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
USER_AGENT = "cues-hackathon/1.0"
CHAT_HISTORY_FILE = Path(__file__).parent / "chat_history.txt"


async def make_overpass_request(query: str) -> dict[str, Any] | None:
    """Make a request to Overpass API."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                OVERPASS_API_BASE,
                params={"data": query}
            )
            response.raise_for_status()
            return response.json()
    except Exception as e:
        print(f"Error making Overpass request: {e}")
        return None


async def make_nominatim_request(url: str) -> dict[str, Any] | None:
    """Make a request to Nominatim API."""
    try:
        headers = {"User-Agent": USER_AGENT}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        print(f"Error making Nominatim request: {e}")
        return None


def format_restaurant(element: dict[str, Any]) -> str:
    """Format a restaurant element into a readable string."""
    tags = element.get("tags", {})
    name = tags.get("name", "Unknown Name")
    cuisine = tags.get("cuisine", "Not specified")
    
    # OpenStreetMap doesn't have ratings, but may have other useful info
    address = tags.get("addr:full") or tags.get("addr:street", "Address not available")
    phone = tags.get("phone", "Phone not available")
    website = tags.get("website", "Website not available")
    opening_hours = tags.get("opening_hours", "Hours not available")
    
    # Get coordinates
    if "lat" in element and "lon" in element:
        lat, lon = element["lat"], element["lon"]
    elif "center" in element:
        lat, lon = element["center"]["lat"], element["center"]["lon"]
    else:
        lat, lon = "N/A", "N/A"
    
    return f"""
{name}
Cuisine: {cuisine}
Address: {address}
Phone: {phone}
Opening Hours: {opening_hours}
Website: {website}
Coordinates: {lat}, {lon}
"""


@mcp.tool()
async def find_restaurants(
    latitude: float,
    longitude: float,
    radius: int = 1500,
    cuisine_type: str = None
) -> str:
    """Find restaurants near a location.

    Args:
        latitude: Latitude of the location
        longitude: Longitude of the location
        radius: Search radius in meters (default: 1500m, ~1 mile)
        cuisine_type: Optional cuisine filter (e.g., "italian", "chinese", "indian")
    """
    # Build Overpass query
    cuisine_filter = f'["cuisine"="{cuisine_type}"]' if cuisine_type else ""
    
    query = f"""
    [out:json][timeout:25];
    (
      node["amenity"="restaurant"]{cuisine_filter}(around:{radius},{latitude},{longitude});
      way["amenity"="restaurant"]{cuisine_filter}(around:{radius},{latitude},{longitude});
    );
    out body center;
    """
    
    data = await make_overpass_request(query)
    
    if not data or "elements" not in data:
        return "Unable to fetch restaurant data for this location."
    
    if not data["elements"]:
        cuisine_msg = f" with {cuisine_type} cuisine" if cuisine_type else ""
        return f"No restaurants found within {radius}m{cuisine_msg}."
    
    # Format restaurants
    restaurants = [format_restaurant(element) for element in data["elements"][:20]]  # Limit to 20
    
    header = f"Found {len(data['elements'])} restaurants within {radius}m:"
    if cuisine_type:
        header = f"Found {len(data['elements'])} {cuisine_type} restaurants within {radius}m:"
    
    return header + "\n---\n".join(restaurants)


@mcp.tool()
async def geocode_address(address: str) -> str:
    """Convert an address to latitude/longitude coordinates.

    Args:
        address: Address to geocode (e.g., "10 Downing Street, London")
    """
    url = f"{NOMINATIM_BASE}/search"
    params = {
        "q": address,
        "format": "json",
        "limit": 5
    }
    
    full_url = f"{url}?q={address}&format=json&limit=5"
    data = await make_nominatim_request(full_url)
    
    if not data:
        return "Unable to geocode this address."
    
    if not data:
        return f"No results found for address: {address}"
    
    # Format results
    results = []
    for i, location in enumerate(data, 1):
        result = f"""
Result {i}:
Address: {location.get('display_name', 'Unknown')}
Coordinates: {location.get('lat', 'N/A')}, {location.get('lon', 'N/A')}
Type: {location.get('type', 'Unknown')}
"""
        results.append(result)
    
    return "Geocoding results:\n---\n".join(results)


@mcp.tool()
async def find_restaurants_by_address(
    address: str,
    radius: int = 1500,
    cuisine_type: str = None
) -> str:
    """Find restaurants near an address (combines geocoding + restaurant search).

    Args:
        address: Address to search near (e.g., "Oxford Street, London")
        radius: Search radius in meters (default: 1500m)
        cuisine_type: Optional cuisine filter (e.g., "italian", "chinese")
    """
    # First geocode the address
    url = f"{NOMINATIM_BASE}/search"
    full_url = f"{url}?q={address}&format=json&limit=1"
    data = await make_nominatim_request(full_url)
    
    if not data or not data:
        return f"Unable to find location for address: {address}"
    
    # Get coordinates from first result
    location = data[0]
    latitude = float(location["lat"])
    longitude = float(location["lon"])
    
    # Now search for restaurants
    result = await find_restaurants(latitude, longitude, radius, cuisine_type)
    
    header = f"Searching near: {location.get('display_name', address)}\n\n"
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
