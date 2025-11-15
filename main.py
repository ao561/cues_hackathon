# main.py
import uvicorn
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

app = FastAPI()
HISTORY_FILE = "chat_history.txt"
analyzer = SentimentIntensityAnalyzer()

# --- User profile database file ---
USER_PROFILES_FILE = "user_food_profiles.json"

# --- List of food items to track ---
FOOD_KEYWORDS = {
    "pizza", "pasta", "burger", "sushi", "salad", "steak",
    "chicken", "fish", "tacos", "burrito", "ramen",
    "curry", "soda", "coffee", "tea", "cake", "ice cream"
}

def update_food_profile(user: str, food: str, category: str):
    """
    Updates the user profile JSON, moving the food item
    to the new category.
    """
    try:
        # Load the entire user profile database
        with open(USER_PROFILES_FILE, "r") as f:
            db = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Database is a dictionary of users
        db = {}

    # Define all possible categories
    all_categories = ["loved", "liked", "neutral", "dislike", "hated"]
    
    # Get or create the profile for this user
    if user not in db:
        db[user] = {cat: [] for cat in all_categories}
    
    # 1. Add the food to the new category (if not already there)
    if food not in db[user][category]:
        db[user][category].append(food)
        
    # 2. Remove the food from all *other* categories
    # (This handles a change of opinion)
    for cat in all_categories:
        if cat != category and food in db[user][cat]:
            db[user][cat].remove(food)
            
    # Write the updated database back to the file
    with open(USER_PROFILES_FILE, "w") as f:
        json.dump(db, f, indent=2)


def process_food_profile_update(user: str, message: str):
    """
    Checks for food, gets sentiment, and maps it
    to one of five categories for the user's profile.
    """
    lower_msg = message.lower()
    found_food = None
    
    for word in lower_msg.split():
        clean_word = word.strip('.,!?"') 
        if clean_word in FOOD_KEYWORDS:
            found_food = clean_word
            break 

    if found_food:
        # 1. Get VADER score
        scores = analyzer.polarity_scores(message)
        compound_score = scores['compound']
        
        # 2. Map score to one of the 5 categories
        category = ""
        if compound_score > 0.6:
            category = "loved"
        elif compound_score >= 0.05:
            category = "liked"
        elif compound_score <= -0.6:
            category = "hated"
        elif compound_score <= -0.05:
            category = "dislike"
        else:
            category = "neutral"
            
        # 3. Save the result to the user's profile
        update_food_profile(user, found_food, category)


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast_to_all(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()


@app.get("/")
async def get():
    return FileResponse("index.html")


@app.websocket("/ws/{client_name}")
async def websocket_endpoint(websocket: WebSocket, client_name: str):
    await manager.connect(websocket)
    
    # Send history to the connecting user
    try:
        with open(HISTORY_FILE, "r") as f:
            history = f.readlines()
            for line in history:
                # Send the raw JSON string from the history file
                await manager.send_personal_message(line.strip(), websocket)
    except FileNotFoundError:
        pass 
    
    try:
        while True:
            data = await websocket.receive_text()
            
            # Process the message for food preferences
            process_food_profile_update(client_name, data)
            
            # Create a JSON object for the message
            message_data = {
                "sender": client_name,
                "message": data
            }
            # Convert the Python dict to a JSON string
            message_json = json.dumps(message_data)
            
            # Save the JSON string to history
            with open(HISTORY_FILE, "a") as f:
                f.write(message_json + "\n")
            
            # Broadcast the JSON string
            await manager.broadcast_to_all(message_json)
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# Add to main.py
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import json

# Google Calendar Configuration
SCOPES = ['https://www.googleapis.com/auth/calendar']
CLIENT_SECRETS_FILE = "credentials.json"  # Downloaded from Google Cloud

user_credentials = {}
pending_auth_states = {}  # Maps state -> username
user_profiles = {}  # Maps username -> {email, calendar_connected, etc}

@app.post("/user/register")
async def register_user(user_data: dict):
    """Register user with email"""
    username = user_data.get("username")
    email = user_data.get("email")
    
    if username and email:
        user_profiles[username] = {
            "email": email,
            "calendar_connected": False,
            "joined_at": datetime.now().isoformat()
        }
        return {"status": "success", "message": f"User {username} registered"}
    return {"status": "error", "message": "Username and email required"}

@app.get("/auth/google-login/{username}")
async def google_login(username: str):
    """Start Google OAuth for a specific user"""
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri="http://localhost:8000/auth/callback"
    )
    
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )
    
    # Store which user is authenticating
    pending_auth_states[state] = username
    
    return {"auth_url": authorization_url, "state": state, "username": username}

@app.get("/auth/callback")
async def google_callback(code: str, state: str):
    """Handle Google OAuth callback"""
    # Get the username from the state
    username = pending_auth_states.get(state, "default")
    
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri="http://localhost:8000/auth/callback",
        state=state
    )
    
    flow.fetch_token(code=code)
    credentials = flow.credentials
    
    # Store credentials for this specific user
    user_credentials[username] = credentials
    
    # Update user profile
    if username in user_profiles:
        user_profiles[username]["calendar_connected"] = True
        user_profiles[username]["connected_at"] = datetime.now().isoformat()
    
    # Clean up
    if state in pending_auth_states:
        del pending_auth_states[state]
    
    return {"status": "success", "message": f"Calendar connected for {username}!"}

# Get calendar events - SUPER SIMPLE!
async def get_calendar_events(username: str, days_ahead: int = 7):
    """Get user's Google Calendar events"""
    if username not in user_credentials:
        return {"error": "Not authenticated"}
    
    creds = user_credentials[username]
    service = build('calendar', 'v3', credentials=creds)
    
    # Get events
    now = datetime.utcnow().isoformat() + 'Z'
    end = (datetime.utcnow() + timedelta(days=days_ahead)).isoformat() + 'Z'
    
    events_result = service.events().list(
        calendarId='primary',
        timeMin=now,
        timeMax=end,
        singleEvents=True,
        orderBy='startTime'
    ).execute()
    
    events = events_result.get('items', [])
    return events

# Create event 
async def create_calendar_event(username: str, summary: str, start_time: datetime, end_time: datetime):
    """Create Google Calendar event"""
    creds = user_credentials[username]
    service = build('calendar', 'v3', credentials=creds)
    
    event = {
        'summary': summary,
        'start': {'dateTime': start_time.isoformat(), 'timeZone': 'UTC'},
        'end': {'dateTime': end_time.isoformat(), 'timeZone': 'UTC'},
    }
    
    created_event = service.events().insert(calendarId='primary', body=event).execute()
    return created_event

# Find free time 
async def find_free_busy(username: str, days_ahead: int = 7):
    """Check when user is free/busy"""
    creds = user_credentials[username]
    service = build('calendar', 'v3', credentials=creds)
    
    now = datetime.utcnow().isoformat() + 'Z'
    end = (datetime.utcnow() + timedelta(days=days_ahead)).isoformat() + 'Z'
    
    body = {
        "timeMin": now,
        "timeMax": end,
        "items": [{"id": "primary"}]
    }
    
    freebusy = service.freebusy().query(body=body).execute()
    busy_times = freebusy['calendars']['primary']['busy']
    
    return busy_times


# ===== TEST ENDPOINTS =====
# These endpoints help you test calendar functionality

@app.get("/test/events")
async def test_get_events():
    """Test endpoint to get calendar events"""
    if "default" not in user_credentials:
        return {
            "error": "Not authenticated", 
            "message": "Please authenticate first by visiting /auth/google-login"
        }
    
    try:
        events = await get_calendar_events("default", days_ahead=7)
        return {
            "status": "success",
            "event_count": len(events),
            "events": events
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/test/create-event")
async def test_create_event():
    """Test endpoint to create a sample calendar event"""
    if "default" not in user_credentials:
        return {
            "error": "Not authenticated",
            "message": "Please authenticate first by visiting /auth/google-login"
        }
    
    try:
        # Create event 1 hour from now
        start = datetime.now() + timedelta(hours=1)
        end = start + timedelta(hours=1)
        
        event = await create_calendar_event(
            username="default",
            summary="Test Event from Chat App",
            start_time=start,
            end_time=end
        )
        
        return {
            "status": "success",
            "message": "Event created!",
            "event": event
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/test/free-busy")
async def test_free_busy():
    """Test endpoint to check free/busy times"""
    if "default" not in user_credentials:
        return {
            "error": "Not authenticated",
            "message": "Please authenticate first by visiting /auth/google-login"
        }
    
    try:
        busy_times = await find_free_busy("default", days_ahead=7)
        return {
            "status": "success",
            "busy_times": busy_times
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/test/auth-status")
async def test_auth_status():
    """Check if user is authenticated"""
    if "default" in user_credentials:
        return {
            "authenticated": True,
            "message": "User is authenticated and ready to use calendar features"
        }
    else:
        return {
            "authenticated": False,
            "message": "Please authenticate first",
            "auth_url": "/auth/google-login"
        }

@app.get("/auth/status/{username}")
async def check_user_auth_status(username: str):
    """Check if a specific user has connected their calendar"""
    if username in user_credentials:
        return {
            "authenticated": True,
            "username": username,
            "message": "Calendar connected"
        }
    else:
        return {
            "authenticated": False,
            "username": username,
            "message": "Calendar not connected"
        }