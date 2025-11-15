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