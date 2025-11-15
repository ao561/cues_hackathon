# main.py
import uvicorn
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# --- GOOGLE CALENDAR ADDITIONS ---
import os.path
import datetime
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
# -----------------------------------


app = FastAPI()
HISTORY_FILE = "chat_history.txt"
analyzer = SentimentIntensityAnalyzer()

# --- User profile database file ---
USER_PROFILES_FILE = "user_food_profiles.json"
# --- GOOGLE CALENDAR ADDITIONS ---
PERSONA_CALENDARS_FILE = "persona_calendars.json"
SERVICE_ACCOUNT_FILE = "service_account.json"
CALENDAR_SCOPES = ['https.www.googleapis.com/auth/calendar.readonly']
# -----------------------------------


# --- List of food items to track ---
FOOD_KEYWORDS = {
    "pizza", "pasta", "burger", "sushi", "salad", "steak",
    "chicken", "fish", "tacos", "burrito", "ramen",
    "curry", "soda", "coffee", "tea", "cake", "ice cream"
}

# --- CLASS DEFINITION MOVED HERE ---
# Moved up to fix the NameError, as other functions reference this class
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

# --- INSTANTIATE THE MANAGER ---
# This must be placed *after* the class is defined
manager = ConnectionManager()


# --- GOOGLE CALENDAR ADDITIONS ---

def get_calendar_service():
    """
    Authenticates using the Service Account and returns a
    Google Calendar API service object.
    """
    creds = None
    if os.path.exists(SERVICE_ACCOUNT_FILE):
        creds = Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=CALENDAR_SCOPES)
    else:
        print(f"Error: '{SERVICE_ACCOUNT_FILE}' not found.")
        print("Please download your service account key from Google Cloud Console.")
        return None

    try:
        service = build('calendar', 'v3', credentials=creds)
        return service
    except HttpError as error:
        print(f'An error occurred building the service: {error}')
        return None

def load_persona_calendars() -> dict:
    """
    Loads the mapping of persona names to calendar IDs
    from 'persona_calendars.json'.
    """
    try:
        with open(PERSONA_CALENDARS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"Error: Could not load '{PERSONA_CALENDARS_FILE}'")
        return {}


async def query_availability(people_list: list[str]) -> dict:
    """
    Given a list of persona names, checks their availability
    for the next 2 hours and returns a status dictionary.
    """

    

    service = get_calendar_service()
    persona_map = load_persona_calendars()
    
    if not service or not persona_map:
        return {"error": "Could not set up calendar service or load personas."}

    calendar_ids_to_query = []
    name_to_id_map = {}
    id_to_name_map = {}
    
    # --- START OF FIX ---
    # We loop through the persona map, assuming the value is a nested dict
    for name_key, cal_id_object in persona_map.items():
        if name_key.lower() in people_list:
            
            # Extract the ID string from the inner dictionary.
            # Based on your prompt, the key is "Name".
            # If your key is different, change "Name" here.
            try:
                cal_id_string = cal_id_object["Name"]
            except KeyError:
                print(f"Error: 'Name' key not found for {name_key} in persona_calendars.json")
                continue
            except TypeError:
                 # This handles the case where the format is correct ("Alice": "id...")
                 cal_id_string = cal_id_object

            
            calendar_ids_to_query.append({"id": cal_id_string})
            name_to_id_map[name_key.lower()] = cal_id_string
            # Use the extracted STRING as the key, not the dictionary
            id_to_name_map[cal_id_string] = name_key
    # --- END OF FIX ---

    if not calendar_ids_to_query:
        return {"error": "No valid people specified."}

    time_min = datetime.datetime.utcnow().isoformat() + 'Z'  # 'Z' indicates UTC
    time_max = (datetime.datetime.utcnow() + datetime.timedelta(hours=2)).isoformat() + 'Z'
    
    freebusy_body = {
        "timeMin": time_min,
        "timeMax": time_max,
        "timeZone": "UTC",
        "items": calendar_ids_to_query
    }

    try:
        results = service.freebusy().query(body=freebusy_body).execute()
        
        availability = {}
        calendars_data = results.get('calendars', {})
        
        for cal_id, data in calendars_data.items():
            persona_name = id_to_name_map.get(cal_id, "Unknown")
            busy_times = data.get('busy', [])
            
            if not busy_times:
                availability[persona_name] = "Available"
            else:
                first_conflict = busy_times[0]
                start_str = first_conflict['start'].split('T')[1][:5] # e.g., "18:30"
                availability[persona_name] = f"Busy (Event at {start_str} UTC)"

        for name in people_list:
            if name.title() not in availability:
                 availability[name.title()] = "Error (Calendar not found)"
                 
        return availability

    except HttpError as error:
        print(f'An error occurred during freebusy query: {error}')
        return {"error": f"API Error: {error}"}


async def process_plan_request(manager: ConnectionManager): # This type hint now works
    """
    Handles the AI planning logic.
    For the hackathon, this queries *all* known personas.
    """
    persona_map = load_persona_calendars()
    all_persona_names = [name.lower() for name in persona_map.keys()]
    
    if not all_persona_names:
        await manager.broadcast_to_all(json.dumps({
            "sender": "Coordinator",
            "message": "I can't plan... I don't know anyone's calendar!"
        }))
        return

    availability_results = await query_availability(all_persona_names)

    plan_message = "OK, I'm checking everyone's availability for the next 2 hours...\n"
    for name, status in availability_results.items():
        plan_message += f"\n- {name}: {status}"
        
    plan_message += "\n\n(Next step: Send this context to Claude to pick a restaurant!)"

    await manager.broadcast_to_all(json.dumps({
        "sender": "Coordinator",
        "message": plan_message
    }))

# -----------------------------------


def update_food_profile(user: str, food: str, category: str):
    """
    Updates the user profile JSON, moving the food item
    to the new category.
    """
    try:
        with open(USER_PROFILES_FILE, "r") as f:
            db = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        db = {}

    all_categories = ["loved", "liked", "neutral", "dislike", "hated"]
    
    if user not in db:
        db[user] = {cat: [] for cat in all_categories}
    
    if food not in db[user][category]:
        db[user][category].append(food)
        
    for cat in all_categories:
        if cat != category and food in db[user][cat]:
            db[user][cat].remove(food)
            
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
        scores = analyzer.polarity_scores(message)
        compound_score = scores['compound']
        
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
            
        update_food_profile(user, found_food, category)
        return True # Found food
    return False # No food found


@app.get("/")
async def get():
    return FileResponse("index.html")


@app.websocket("/ws/{client_name}")
async def websocket_endpoint(websocket: WebSocket, client_name: str):
    await manager.connect(websocket)
    
    try:
        with open(HISTORY_FILE, "r") as f:
            history = f.readlines()
            for line in history:
                await manager.send_personal_message(line.strip(), websocket)
    except FileNotFoundError:
        pass 
    
    try:
        while True:
            data = await websocket.receive_text()
            
            # 1. Try to process as a food update
            found_food = process_food_profile_update(client_name, data)
            
            # 2. If not a food update, check for a "plan" command
            if not found_food and "plan" in data.lower():
                await process_plan_request(manager)

            # 3. Always save and broadcast the original message
            message_data = {
                "sender": client_name,
                "message": data
            }
            message_json = json.dumps(message_data)
            
            with open(HISTORY_FILE, "a") as f:
                f.write(message_json + "\n")
            
            await manager.broadcast_to_all(message_json)
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)