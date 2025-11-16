import uvicorn
import json
import asyncio
import threading
import sys
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

# Add parent directory to path for sentiment_server import
sys.path.append(str(Path(__file__).parent))

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

# Note: Food sentiment analysis is now handled by the AI using sentiment_server.py MCP

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

# Note: Food profile updates are now handled intelligently by the AI
# using sentiment_server.py MCP with Claude-based sentiment analysis

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
            
            # Automatic food sentiment analysis on every message
            try:
                from sentiment_server import analyze_message_sentiment
                await analyze_message_sentiment(client_name, data)
            except Exception as e:
                print(f"[Sentiment Analysis Error] {e}")

            entry = json.dumps({"sender": client_name, "message": data})
            with open(HISTORY_FILE, "a") as f:
                f.write(entry + "\n")

            await manager.broadcast_to_all(entry)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
