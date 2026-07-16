import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class EventManager:
    """WebSocket-based event broadcasting for real-time machine state updates."""

    def __init__(self):
        self._connections: list[WebSocket] = []
        self._history: list[dict] = []
        self._max_history = 500

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.append(ws)
        logger.info(f"WebSocket connected. Total: {len(self._connections)}")

    def disconnect(self, ws: WebSocket):
        self._connections.remove(ws)
        logger.info(f"WebSocket disconnected. Total: {len(self._connections)}")

    async def broadcast(self, event: dict):
        event["timestamp"] = datetime.now(timezone.utc).isoformat()
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]

        message = json.dumps(event)
        dead = []
        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.remove(ws)

    def get_history(self, limit: int = 50) -> list[dict]:
        return self._history[-limit:]


event_manager = EventManager()
