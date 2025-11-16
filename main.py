import uvicorn
import json
import asyncio
import threading
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# GOOGLE CALENDAR IMPORTS
import os
import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

app = FastAPI()

# Start AI monitor in background thread
def start_ai_monitor():
    """Start the AI monitor in a separate thread"""
    import subprocess
    import sys
    subprocess.Popen([sys.executable, "active_ai_monitor.py"])

@app.on_event("startup")
async def startup_event():
    """Start the AI monitor when the server starts"""
    print("Starting Active AI Monitor...")
    thread = threading.Thread(target=start_ai_monitor, daemon=True)
    thread.start()
HISTORY_FILE = "chat_history.txt"
USER_PROFILES_FILE = "user_food_profiles.json"
PERSONA_CALENDARS_FILE = "persona_calendars.json"
SERVICE_ACCOUNT_FILE = "service_account.json"
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

analyzer = SentimentIntensityAnalyzer()

FOOD_KEYWORDS = {
    "pizza", "pasta", "burger", "sushi", "salad", "steak",
    "chicken", "fish", "tacos", "burrito", "ramen",
    "curry", "soda", "coffee", "tea", "cake", "ice cream"
}

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

# ---------------- GOOGLE CALENDAR FIXED VERSION ----------------
def get_calendar_service():
    try:
        creds = Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=CALENDAR_SCOPES
        )
        return build("calendar", "v3", credentials=creds)
    except Exception as e:
        print("Service account load error:", e)
        return None


def load_persona_calendars() -> dict:
    try:
        with open(PERSONA_CALENDARS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


async def query_availability(people_list: list[str]) -> dict:
    service = get_calendar_service()
    persona_map = load_persona_calendars()

    if not service or not persona_map:
        return {"error": "Could not load calendar service or persona map"}

    calendar_ids_to_query = []
    id_to_name = {}

    for name, cal_id in persona_map.items():
        if name.lower() in people_list:
            if isinstance(cal_id, dict):
                cal_id = list(cal_id.values())[0]
            calendar_ids_to_query.append({"id": cal_id})
            id_to_name[cal_id] = name

    if not calendar_ids_to_query:
        return {"error": "No valid people specified"}

    time_min = datetime.datetime.utcnow().isoformat() + "Z"
    time_max = (datetime.datetime.utcnow() + datetime.timedelta(hours=2)).isoformat() + "Z"

    body = {
        "timeMin": time_min,
        "timeMax": time_max,
        "timeZone": "UTC",
        "items": calendar_ids_to_query
    }

    try:
        result = service.freebusy().query(body=body).execute()
        calendars = result.get("calendars", {})

        availability = {}
        for cal_id, data in calendars.items():
            busy = data.get("busy", [])
            name = id_to_name.get(cal_id, "Unknown")
            if not busy:
                availability[name] = "Available"
            else:
                start = busy[0]["start"].split("T")[1][:5]
                availability[name] = f"Busy (Event at {start} UTC)"
        return availability
    except HttpError as e:
        return {"error": str(e)}


async def process_plan_request(manager: ConnectionManager):
    persona_map = load_persona_calendars()
    all_names = [name.lower() for name in persona_map.keys()]

    if not all_names:
        await manager.broadcast_to_all(json.dumps({
            "sender": "Coordinator",
            "message": "Cannot plan — no personas loaded"
        }))
        return

    availability = await query_availability(all_names)

    msg = "Checking availability for the next 2 hours..."
    for name, status in availability.items():
        msg += f"- {name}: {status}"

    await manager.broadcast_to_all(json.dumps({
        "sender": "Coordinator",
        "message": msg
    }))

# ---------------- FOOD PROFILE LOGIC ----------------
def update_food_profile(user: str, food: str, category: str):
    try:
        with open(USER_PROFILES_FILE, "r") as f:
            db = json.load(f)
    except:
        db = {}

    cats = ["loved", "liked", "neutral", "dislike", "hated"]

    if user not in db:
        db[user] = {c: [] for c in cats}

    if food not in db[user][category]:
        db[user][category].append(food)

    for c in cats:
        if c != category and food in db[user][c]:
            db[user][c].remove(food)

    with open(USER_PROFILES_FILE, "w") as f:
        json.dump(db, f, indent=2)


def process_food_profile_update(user: str, message: str):
    lower = message.lower()
    found = None
    for word in lower.split():
        w = word.strip('.,!?"')
        if w in FOOD_KEYWORDS:
            found = w
            break

    if found:
        score = analyzer.polarity_scores(message)["compound"]
        if score > 0.6:
            cat = "loved"
        elif score >= 0.05:
            cat = "liked"
        elif score <= -0.6:
            cat = "hated"
        elif score <= -0.05:
            cat = "dislike"
        else:
            cat = "neutral"

        update_food_profile(user, found, cat)
        return True

    return False

# ---------------- WEBSOCKET HANDLER ----------------
@app.get("/")
async def get():
    return FileResponse("index.html")


@app.websocket("/ws/{client_name}")
async def websocket_endpoint(websocket: WebSocket, client_name: str):
    await manager.connect(websocket)

    # Load history
    try:
        with open(HISTORY_FILE, "r") as f:
            for line in f.readlines():
                await manager.send_personal_message(line.strip(), websocket)
    except:
        pass

    try:
        while True:
            data = await websocket.receive_text()
            found_food = process_food_profile_update(client_name, data)

            if not found_food and "plan" in data.lower():
                await process_plan_request(manager)

            entry = json.dumps({"sender": client_name, "message": data})
            with open(HISTORY_FILE, "a") as f:
                f.write(entry + "")

            await manager.broadcast_to_all(entry)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
