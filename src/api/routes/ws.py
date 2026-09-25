"""WebSocket endpoint for streaming live train ETA forecasts."""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.api.ws_manager import ws_manager
from src.db.session import SessionLocal
from src.simulator.replay import replay_engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSockets"])


@router.websocket("/ws/trains/{run_id}")
async def websocket_train_eta_stream(websocket: WebSocket, run_id: str) -> None:
    """Stream dynamic ETA forecast updates for a specific train run or all trains ('all')."""
    await ws_manager.connect(websocket, run_id)

    # Send initial snapshot immediately upon connection
    try:
        with SessionLocal() as session:
            current_time = replay_engine.current_sim_time
            if run_id != "all":
                snapshot = replay_engine._generate_run_update(session, run_id, current_time)
                if snapshot:
                    await websocket.send_json(snapshot)
                else:
                    await websocket.send_json({
                        "type": "connected",
                        "run_id": run_id,
                        "sim_time": current_time.isoformat(),
                        "message": f"Subscribed to train run {run_id}",
                    })
            else:
                await websocket.send_json({
                    "type": "connected",
                    "run_id": "all",
                    "sim_time": current_time.isoformat(),
                    "message": "Subscribed to all corridor trains",
                })
    except Exception as e:
        logger.warning(f"Error sending initial WebSocket snapshot: {e}")

    try:
        while True:
            # Keep connection alive; accept pings or client queries
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_json({"type": "pong", "sim_time": replay_engine.current_sim_time.isoformat()})
            elif msg == "step":
                await replay_engine.step(300.0)
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, run_id)
    except Exception as e:
        logger.info(f"WebSocket client disconnected: {e}")
        ws_manager.disconnect(websocket, run_id)
