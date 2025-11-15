# main.py
import uvicorn
import json  # --- NEW IMPORT ---
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse 

app = FastAPI()
HISTORY_FILE = "chat_history.txt"

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


# --- THIS ENDPOINT IS UPDATED TO USE JSON ---
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
            
            # --- NEW: Create a JSON object ---
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