import uvicorn
import json
import asyncio
import threading
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from pydantic import BaseModel

app = FastAPI()

# Message model for the endpoint
class Message(BaseModel):
    sender: str
    message: str

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


@app.post("/send_message")
async def send_message(msg: Message):
    """HTTP endpoint for AI monitor to send messages"""
    entry = json.dumps({"sender": msg.sender, "message": msg.message})
    await manager.broadcast_to_all(entry)
    return {"status": "success"}


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
            process_food_profile_update(client_name, data)

            entry = json.dumps({"sender": client_name, "message": data})
            with open(HISTORY_FILE, "a") as f:
                f.write(entry + "\n")

            await manager.broadcast_to_all(entry)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
