# /// script
# dependencies = [
#   "mcp",
#   "google-auth",
#   "google-auth-oauthlib",
#   "google-auth-httplib2",
#   "google-api-python-client",
# ]
# ///

"""
Calendar MCP Server - Provides tools for checking user availability via Google Calendar
"""

import json
import datetime
from pathlib import Path
from typing import Any
from mcp.server.fastmcp import FastMCP
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Initialize FastMCP server
mcp = FastMCP("calendar")

# File paths
PERSONA_CALENDARS_FILE = Path(__file__).parent / "persona_calendars.json"
SERVICE_ACCOUNT_FILE = Path(__file__).parent / "service_account.json"
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def get_calendar_service():
    """Get authenticated Google Calendar service"""
    try:
        creds = Credentials.from_service_account_file(
            str(SERVICE_ACCOUNT_FILE),
            scopes=CALENDAR_SCOPES
        )
        return build("calendar", "v3", credentials=creds)
    except Exception as e:
        return None


def load_persona_calendars() -> dict:
    """Load persona to calendar ID mapping from JSON file"""
    try:
        with open(PERSONA_CALENDARS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


@mcp.tool()
async def check_availability(
    people: list[str],
    hours_ahead: int = 2
) -> str:
    """Check calendar availability for a list of people.

    Args:
        people: List of person names to check (e.g., ["Simon", "Mahdi", "Amaan"])
        hours_ahead: Number of hours to check ahead (default: 2)
    
    Returns:
        Availability status for each person
    """
    service = get_calendar_service()
    persona_map = load_persona_calendars()

    if not service:
        return "Error: Could not authenticate with Google Calendar API"
    
    if not persona_map:
        return "Error: No persona calendars configured"

    # Normalize people names to lowercase for matching
    people_lower = [p.lower() for p in people]
    
    calendar_ids_to_query = []
    id_to_name = {}

    for name, cal_id in persona_map.items():
        if name.lower() in people_lower:
            # Handle nested dict format
            if isinstance(cal_id, dict):
                cal_id = list(cal_id.values())[0]
            calendar_ids_to_query.append({"id": cal_id})
            id_to_name[cal_id] = name

    if not calendar_ids_to_query:
        available_people = ", ".join(persona_map.keys())
        return f"No matching people found. Available people: {available_people}"

    # Query time range
    time_min = datetime.datetime.utcnow().isoformat() + "Z"
    time_max = (datetime.datetime.utcnow() + datetime.timedelta(hours=hours_ahead)).isoformat() + "Z"

    body = {
        "timeMin": time_min,
        "timeMax": time_max,
        "timeZone": "UTC",
        "items": calendar_ids_to_query
    }

    try:
        result = service.freebusy().query(body=body).execute()
        calendars = result.get("calendars", {})

        # Format results
        results = []
        results.append(f"Availability for the next {hours_ahead} hours:\n")
        
        for cal_id, data in calendars.items():
            busy = data.get("busy", [])
            name = id_to_name.get(cal_id, "Unknown")
            
            if not busy:
                results.append(f"✅ {name}: Available")
            else:
                # Get first busy time
                start_time = busy[0]["start"]
                # Parse and format time
                dt = datetime.datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                time_str = dt.strftime("%H:%M UTC")
                results.append(f"❌ {name}: Busy (Event at {time_str})")
        
        return "\n".join(results)
        
    except HttpError as e:
        return f"Error querying calendar: {str(e)}"


@mcp.tool()
async def get_available_people() -> str:
    """Get a list of all people with configured calendars.
    
    Returns:
        List of people names who have calendars configured
    """
    persona_map = load_persona_calendars()
    
    if not persona_map:
        return "No people configured in the calendar system"
    
    people = list(persona_map.keys())
    return f"People with calendars: {', '.join(people)}"


@mcp.tool()
async def get_current_locations(
    people: list[str],
    hours_ahead: int = 2
) -> str:
    """Get the current or upcoming location for each person based on their calendar events.

    Args:
        people: List of person names to check (e.g., ["Simon", "Mahdi", "Amaan"])
        hours_ahead: Number of hours to check ahead (default: 2)
    
    Returns:
        Location information for each person's current/upcoming events
    """
    service = get_calendar_service()
    persona_map = load_persona_calendars()

    if not service:
        return "Error: Could not authenticate with Google Calendar API"
    
    if not persona_map:
        return "Error: No persona calendars configured"

    # Normalize people names
    people_lower = [p.lower() for p in people]
    
    results = []
    results.append(f"Locations for the next {hours_ahead} hours:\n")

    # Query time range
    time_min = datetime.datetime.utcnow().isoformat() + "Z"
    time_max = (datetime.datetime.utcnow() + datetime.timedelta(hours=hours_ahead)).isoformat() + "Z"

    for name, cal_id in persona_map.items():
        if name.lower() not in people_lower:
            continue
            
        # Handle nested dict format
        if isinstance(cal_id, dict):
            cal_id = list(cal_id.values())[0]

        try:
            # Get events with full details including location
            events_result = service.events().list(
                calendarId=cal_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime"
            ).execute()
            
            events = events_result.get("items", [])
            
            if not events:
                results.append(f"📍 {name}: No scheduled events (location unknown)")
            else:
                # Show all events in the time window
                for event in events:
                    summary = event.get("summary", "Untitled Event")
                    location = event.get("location", "No location specified")
                    start = event["start"].get("dateTime", event["start"].get("date"))
                    
                    # Parse and format time
                    if "T" in start:
                        dt = datetime.datetime.fromisoformat(start.replace('Z', '+00:00'))
                        time_str = dt.strftime("%H:%M UTC")
                    else:
                        time_str = "All day"
                    
                    results.append(f"📍 {name} @ {time_str}: {location}")
                    results.append(f"   Event: {summary}")
                    
        except HttpError as e:
            results.append(f"❌ {name}: Error accessing calendar - {str(e)}")
    
    return "\n".join(results)


@mcp.tool()
async def find_common_free_time(
    people: list[str],
    hours_ahead: int = 8
) -> str:
    """Find common free time slots when all specified people are available.

    Args:
        people: List of person names to check
        hours_ahead: Number of hours to search (default: 8)
    
    Returns:
        Common available time slots for all people
    """
    service = get_calendar_service()
    persona_map = load_persona_calendars()

    if not service:
        return "Error: Could not authenticate with Google Calendar API"
    
    if not persona_map:
        return "Error: No persona calendars configured"

    # Normalize people names
    people_lower = [p.lower() for p in people]
    
    calendar_ids_to_query = []
    id_to_name = {}

    for name, cal_id in persona_map.items():
        if name.lower() in people_lower:
            if isinstance(cal_id, dict):
                cal_id = list(cal_id.values())[0]
            calendar_ids_to_query.append({"id": cal_id})
            id_to_name[cal_id] = name

    if not calendar_ids_to_query:
        return "No matching people found"

    # Query time range
    time_min = datetime.datetime.utcnow().isoformat() + "Z"
    time_max = (datetime.datetime.utcnow() + datetime.timedelta(hours=hours_ahead)).isoformat() + "Z"

    body = {
        "timeMin": time_min,
        "timeMax": time_max,
        "timeZone": "UTC",
        "items": calendar_ids_to_query
    }

    try:
        result = service.freebusy().query(body=body).execute()
        calendars = result.get("calendars", {})

        # Collect all busy times
        all_busy_times = []
        for cal_id, data in calendars.items():
            busy = data.get("busy", [])
            all_busy_times.extend(busy)

        # If no one is busy, everyone is free
        if not all_busy_times:
            return f"✅ All people ({', '.join(id_to_name.values())}) are completely free for the next {hours_ahead} hours!"

        # Sort busy times
        all_busy_times.sort(key=lambda x: x["start"])
        
        # Find gaps (free times)
        now = datetime.datetime.utcnow()
        end_time = now + datetime.timedelta(hours=hours_ahead)
        
        free_slots = []
        current = now
        
        for busy in all_busy_times:
            busy_start = datetime.datetime.fromisoformat(busy["start"].replace('Z', '+00:00'))
            busy_end = datetime.datetime.fromisoformat(busy["end"].replace('Z', '+00:00'))
            
            # If there's a gap before this busy time
            if current < busy_start:
                duration = (busy_start - current).total_seconds() / 60
                if duration >= 30:  # Only show slots 30+ minutes
                    free_slots.append({
                        "start": current.strftime("%H:%M"),
                        "end": busy_start.strftime("%H:%M"),
                        "duration": int(duration)
                    })
            
            current = max(current, busy_end)
        
        # Check if there's free time after last busy period
        if current < end_time:
            duration = (end_time - current).total_seconds() / 60
            if duration >= 30:
                free_slots.append({
                    "start": current.strftime("%H:%M"),
                    "end": end_time.strftime("%H:%M"),
                    "duration": int(duration)
                })
        
        if not free_slots:
            return f"❌ No common free time found for {', '.join(id_to_name.values())} in the next {hours_ahead} hours"
        
        result = [f"Common free times for {', '.join(id_to_name.values())}:\n"]
        for slot in free_slots:
            result.append(f"⏰ {slot['start']} - {slot['end']} UTC ({slot['duration']} minutes)")
        
        return "\n".join(result)
        
    except HttpError as e:
        return f"Error querying calendar: {str(e)}"


if __name__ == "__main__":
    mcp.run()
