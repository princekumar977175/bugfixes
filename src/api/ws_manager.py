"""WebSocket connection manager for handling client subscriptions and real-time broadcasts."""

import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections grouped by train run_id and corridor-wide subscribers."""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, websocket: WebSocket, run_id: str = "all") -> None:
        """Accept and register an active WebSocket connection for a given run_id."""
        await websocket.accept()
        self._connections[run_id].add(websocket)
        logger.info(f"WebSocket client connected to topic '{run_id}'. Active in topic: {len(self._connections[run_id])}")

    def disconnect(self, websocket: WebSocket, run_id: str = "all") -> None:
        """Deregister a disconnected WebSocket."""
        if run_id in self._connections:
            self._connections[run_id].discard(websocket)
            if not self._connections[run_id]:
                del self._connections[run_id]
        logger.info(f"WebSocket client disconnected from topic '{run_id}'.")

    async def broadcast_to_run(self, run_id: str, message: dict[str, Any]) -> None:
        """Broadcast a message to clients listening to a specific run_id and to corridor-wide ('all') clients."""
        targets = set(self._connections.get(run_id, set())) | set(self._connections.get("all", set()))
        if not targets:
            return

        dead_connections: list[tuple[str, WebSocket]] = []
        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send WebSocket message to client: {e}")
                for r_id, conns in self._connections.items():
                    if ws in conns:
                        dead_connections.append((r_id, ws))

        for r_id, ws in dead_connections:
            self.disconnect(ws, r_id)

    async def broadcast_all(self, message: dict[str, Any]) -> None:
        """Broadcast a message to all active WebSocket connections across all topics."""
        all_targets: set[WebSocket] = set()
        for conns in self._connections.values():
            all_targets.update(conns)

        dead_connections: list[tuple[str, WebSocket]] = []
        for ws in all_targets:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to broadcast WebSocket message: {e}")
                for r_id, conns in self._connections.items():
                    if ws in conns:
                        dead_connections.append((r_id, ws))

        for r_id, ws in dead_connections:
            self.disconnect(ws, r_id)

    @property
    def total_connections(self) -> int:
        """Total number of unique active connections."""
        unique_ws = set()
        for conns in self._connections.values():
            unique_ws.update(conns)
        return len(unique_ws)


# Global singleton instance
ws_manager = ConnectionManager()
