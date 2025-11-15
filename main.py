# main.py
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

app = FastAPI()

html = None
with open("index.html") as f:
    html = f.read()

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

    async def broadcast(self, message: str, sender: WebSocket):
        # Send a message to all connections *except* the sender
        for connection in self.active_connections:
            if connection != sender:
                await connection.send_text(message)

# Create an instance of the manager
manager = ConnectionManager()


# This endpoint serves the HTML page
@app.get("/")
async def get():
    return HTMLResponse(html)


# This endpoint handles the WebSocket connection
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Wait for a message from the client
            data = await websocket.receive_text()
            
            # Broadcast the received message to all other clients
            # We add a prefix to show it's from "Someone"
            await manager.broadcast(f"Someone: {data}", websocket)
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await manager.broadcast("A user has left the chat", websocket)