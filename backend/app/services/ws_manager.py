from fastapi import WebSocket
from typing import Dict, List, Any, Optional
import json

class _Connection:
    __slots__ = ("websocket", "role")

    def __init__(self, websocket: WebSocket, role: str):
        self.websocket = websocket
        self.role = role

class ConnectionManager:
    """Tracks websocket connections per-venue (a "room" per tenant) rather than
    one global list -- a guest/player/owner connected to one venue must never
    see another venue's broadcasts. Each connection also carries a role
    ("guest" | "player" | "owner") so the router can gate which message types
    a given connection is allowed to send."""

    def __init__(self):
        self.active_connections: Dict[int, List[_Connection]] = {}

    async def connect(self, websocket: WebSocket, venue_id: int, role: str):
        await websocket.accept()
        self.active_connections.setdefault(venue_id, []).append(_Connection(websocket, role))
        print(f"[WebSocket] {role} connected to venue {venue_id}. "
              f"Total active in venue: {len(self.active_connections[venue_id])}")

    def disconnect(self, websocket: WebSocket, venue_id: int):
        conns = self.active_connections.get(venue_id)
        if not conns:
            return
        remaining = [c for c in conns if c.websocket is not websocket]
        if remaining:
            self.active_connections[venue_id] = remaining
        else:
            del self.active_connections[venue_id]
        print(f"[WebSocket] Client disconnected from venue {venue_id}. "
              f"Total active in venue: {len(remaining)}")

    def get_role(self, websocket: WebSocket, venue_id: int) -> Optional[str]:
        for c in self.active_connections.get(venue_id, []):
            if c.websocket is websocket:
                return c.role
        return None

    async def broadcast(self, venue_id: int, message_type: str, payload: Dict[str, Any]):
        """Broadcast a structured JSON event to every connection of one venue."""
        conns = self.active_connections.get(venue_id, [])
        if not conns:
            return
        data = {"type": message_type, "payload": payload}
        json_data = json.dumps(data)

        disconnected = []
        for conn in conns:
            try:
                await conn.websocket.send_text(json_data)
            except Exception as e:
                print(f"[WebSocket] Send error, flagging for removal: {e}")
                disconnected.append(conn.websocket)

        for ws in disconnected:
            self.disconnect(ws, venue_id)

ws_manager = ConnectionManager()
