from fastapi import WebSocket
from typing import List, Dict, Any
import json
import asyncio

class ConnectionManager:
    def __init__(self):
        # Active connections list
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"[WebSocket] Client connected. Total active: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            print(f"[WebSocket] Client disconnected. Total active: {len(self.active_connections)}")

    async def broadcast(self, message_type: str, payload: Dict[str, Any]):
        """Broadcast a structured JSON event to all connected clients."""
        data = {
            "type": message_type,
            "payload": payload
        }
        json_data = json.dumps(data)
        
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(json_data)
            except Exception as e:
                print(f"[WebSocket] Send error, flagging for removal: {e}")
                disconnected.append(connection)
                
        for conn in disconnected:
            self.disconnect(conn)

ws_manager = ConnectionManager()
