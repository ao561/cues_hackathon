# main.py
import uvicorn
import json
import asyncio
import os
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from anthropic import Anthropic
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI()
HISTORY_FILE = "chat_history.txt"
analyzer = SentimentIntensityAnalyzer()

# Auto-responder configuration
PREPARED_RESPONSE_FILE = Path("prepared_response.txt")
LAST_TRIGGER_FILE = Path(".last_trigger_line")
TRIGGER_WORD = "@ai"
CHECK_INTERVAL = 1  # Check every 1 second

# Anthropic client
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = "claude-3-haiku-20240307"  # Using Haiku - faster and cheaper
claude_client = Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

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


def get_last_trigger_line():
    """Get the line number we last processed"""
    if LAST_TRIGGER_FILE.exists():
        try:
            return int(LAST_TRIGGER_FILE.read_text().strip())
        except:
            return 0
    return 0


def set_last_trigger_line(line_num):
    """Save the line number we just processed"""
    LAST_TRIGGER_FILE.write_text(str(line_num))


def get_user_profiles():
    """Load user food profiles for context"""
    try:
        with open(USER_PROFILES_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}


async def generate_ai_response(context_lines):
    """Generate AI response using Claude"""
    if not claude_client:
        return "Error: AI not configured (missing API key)"
    
    # Build conversation context
    conversation = []
    for line in context_lines:
        try:
            msg = json.loads(line.strip())
            sender = msg.get("sender", "Unknown")
            message = msg.get("message", "")
            conversation.append(f"{sender}: {message}")
        except:
            continue
    
    # Load user profiles for context
    profiles = get_user_profiles()
    profile_context = ""
    if profiles:
        profile_context = "\n\nUser Food Preferences:\n"
        for user, prefs in profiles.items():
            loved = prefs.get('loved', [])
            disliked = prefs.get('dislike', []) + prefs.get('hated', [])
            if loved or disliked:
                profile_context += f"- {user}: "
                if loved:
                    profile_context += f"Loves {', '.join(loved)}. "
                if disliked:
                    profile_context += f"Dislikes {', '.join(disliked)}."
                profile_context += "\n"
    
    # System prompt
    system_prompt = f"""You are a helpful AI assistant in a group chat helping plan social activities.

Your role:
- Help plan dinners, movies, hangouts
- Be conversational and friendly
- Consider user preferences when making suggestions
- Be concise but helpful (keep responses under 3 sentences unless asked for details)

Recent conversation:
{chr(10).join(conversation)}
{profile_context}

Respond naturally to the most recent @ai mention."""
    
    try:
        # Call Claude
        response = claude_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": "Based on the conversation above, provide a helpful response."
            }],
            system=system_prompt
        )
        
        # Extract text
        response_text = ""
        for block in response.content:
            if hasattr(block, 'text'):
                response_text += block.text
        
        return response_text.strip()
        
    except Exception as e:
        print(f"❌ Error calling Claude: {e}")
        return f"Sorry, I encountered an error: {str(e)}"


async def check_for_ai_trigger():
    """Check if @ai appears in new messages and generate response"""
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
    except FileNotFoundError:
        return None, None
    
    last_trigger = get_last_trigger_line()
    new_lines = all_lines[last_trigger:]
    
    if not new_lines:
        return None, None
    
    # Check for @ai trigger
    for i, line in enumerate(new_lines):
        try:
            msg = json.loads(line.strip())
            message = msg.get("message", "")
            
            if TRIGGER_WORD.lower() in message.lower():
                # Found trigger!
                current_line = last_trigger + i + 1
                
                # Get last 20 messages for context
                context_start = max(0, current_line - 20)
                context_lines = all_lines[context_start:current_line + 1]
                
                return current_line, context_lines
        except json.JSONDecodeError:
            continue
    
    # Update last checked line even if no trigger
    set_last_trigger_line(len(all_lines))
    return None, None


async def auto_responder_loop():
    """Background task that monitors for @ai and generates responses"""
    print("🤖 Auto Responder Started")
    print(f"   Monitoring: {HISTORY_FILE}")
    print(f"   Trigger: {TRIGGER_WORD}")
    
    if not claude_client:
        print("⚠️  WARNING: ANTHROPIC_API_KEY not set - AI responses will be disabled")
    
    while True:
        try:
            # Check for trigger
            trigger_line, context = await check_for_ai_trigger()
            
            if trigger_line and context:
                print(f"\n🎯 @ai trigger detected at line {trigger_line}")
                print("   Generating AI response...")
                
                # Generate response
                response = await generate_ai_response(context)
                
                # Save to file
                with open(PREPARED_RESPONSE_FILE, 'w', encoding='utf-8') as f:
                    f.write(response)
                
                print(f"   ✅ Response ready: {response[:80]}...")
                
                # Broadcast to all connected clients
                message_data = {
                    "sender": "AI Assistant",
                    "message": response
                }
                message_json = json.dumps(message_data)
                
                # Save to history
                with open(HISTORY_FILE, "a") as f:
                    f.write(message_json + "\n")
                
                # Broadcast
                await manager.broadcast_to_all(message_json)
                
                # Update last processed line
                set_last_trigger_line(trigger_line)
                
                # Clean up response file
                if PREPARED_RESPONSE_FILE.exists():
                    PREPARED_RESPONSE_FILE.unlink()
            
            # Wait before next check
            await asyncio.sleep(CHECK_INTERVAL)
            
        except Exception as e:
            print(f"❌ Auto-responder error: {e}")
            await asyncio.sleep(CHECK_INTERVAL)


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


@app.on_event("startup")
async def startup_event():
    """Start the auto-responder background task when the app starts"""
    asyncio.create_task(auto_responder_loop())


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