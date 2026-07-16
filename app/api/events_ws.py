from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.auth import get_current_user, get_ws_user
from app.events.manager import event_manager

router = APIRouter(tags=["events"])


@router.websocket("/ws/events")
async def events_websocket(ws: WebSocket):
    user = await get_ws_user(ws)
    await event_manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        event_manager.disconnect(ws)


@router.get("/api/v1/events/history", dependencies=[Depends(get_current_user)])
async def event_history(limit: int = 50):
    return event_manager.get_history(limit)
