from collections import defaultdict
from datetime import datetime, timezone

from fastapi import WebSocket


class ConnectionManager:
    """Track this process's WebSocket connections by conversation and user."""

    def __init__(self) -> None:
        self._connections: dict[int, dict[int, set[WebSocket]]] = defaultdict(
            lambda: defaultdict(set)
        )
        self._expirations: dict[WebSocket, datetime] = {}

    async def connect(
        self,
        websocket: WebSocket,
        conversation_id: int,
        user_id: int,
        expires_at: datetime,
        subprotocol: str,
    ) -> None:
        await websocket.accept(subprotocol=subprotocol)
        self._connections[conversation_id][user_id].add(websocket)
        self._expirations[websocket] = expires_at

    def disconnect(
        self, websocket: WebSocket, conversation_id: int, user_id: int
    ) -> None:
        self._expirations.pop(websocket, None)
        users = self._connections.get(conversation_id)
        if users is None:
            return
        connections = users.get(user_id)
        if connections is not None:
            connections.discard(websocket)
            if not connections:
                users.pop(user_id, None)
        if not users:
            self._connections.pop(conversation_id, None)

    def is_expired(self, websocket: WebSocket) -> bool:
        expires_at = self._expirations.get(websocket)
        return expires_at is None or datetime.now(timezone.utc) >= expires_at

    async def close_if_expired(
        self, websocket: WebSocket, conversation_id: int, user_id: int
    ) -> bool:
        if not self.is_expired(websocket):
            return False
        try:
            await websocket.close(code=4408, reason="Authentication expired.")
        except Exception:
            pass
        self.disconnect(websocket, conversation_id, user_id)
        return True

    async def broadcast(self, conversation_id: int, payload: dict) -> None:
        users = self._connections.get(conversation_id, {})
        stale: list[tuple[int, WebSocket]] = []
        for user_id, sockets in list(users.items()):
            for websocket in list(sockets):
                if await self.close_if_expired(websocket, conversation_id, user_id):
                    continue
                try:
                    await websocket.send_json(payload)
                except Exception:
                    # One dead client must not prevent delivery to other clients.
                    stale.append((user_id, websocket))
        for user_id, websocket in stale:
            self.disconnect(websocket, conversation_id, user_id)

    def connection_count(self, conversation_id: int, user_id: int) -> int:
        return len(self._connections.get(conversation_id, {}).get(user_id, set()))


connection_manager = ConnectionManager()
