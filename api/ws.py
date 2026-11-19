"""WebSocket manager — broadcasts real-time notifications to connected clients.

Events:
  action_completed: skill action finished (success or error)
  data_changed: entity data was modified (create, update, delete, submit)
"""

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from auth.jwt_utils import verify_access_token

router = APIRouter(tags=["websocket"])


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts events."""

    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.register(ws)

    def register(self, ws: WebSocket):
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, event: str, data: dict):
        """Send an event to all connected clients."""
        message = json.dumps({
            "event": event,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        stale = []
        for ws in self.active:
            try:
                await ws.send_text(message)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)


manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """Authenticate with the first WebSocket message; never put JWTs in URLs."""
    await ws.accept()

    try:
        auth_message = await asyncio.wait_for(ws.receive_text(), timeout=10)
    except WebSocketDisconnect:
        return
    except asyncio.TimeoutError:
        await ws.close(code=4001, reason="Unauthorized")
        return

    try:
        auth_data = json.loads(auth_message)
    except (TypeError, ValueError):
        auth_data = None

    token = (
        auth_data.get("token")
        if isinstance(auth_data, dict) and auth_data.get("type") == "auth"
        else None
    )
    if not isinstance(token, str) or not verify_access_token(token):
        await ws.close(code=4001, reason="Unauthorized")
        return

    manager.register(ws)
    await ws.send_text(json.dumps({"event": "authenticated"}))

    try:
        while True:
            # Keep connection alive; client can send pings
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text(json.dumps({"event": "pong"}))
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)


async def notify_action(skill: str, action: str, success: bool, entity: str | None = None):
    """Broadcast an action completion event."""
    await manager.broadcast("action_completed", {
        "skill": skill,
        "action": action,
        "success": success,
        "entity": entity,
    })


async def notify_data_change(entity: str, change_type: str, record_id: str | None = None):
    """Broadcast a data change event."""
    await manager.broadcast("data_changed", {
        "entity": entity,
        "change_type": change_type,
        "record_id": record_id,
    })
