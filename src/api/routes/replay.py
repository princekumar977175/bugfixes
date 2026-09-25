"""Simulation replay control routes."""

import logging

from fastapi import APIRouter, HTTPException

from src.api.schemas import ReplaySpeedRequest, ReplayStartRequest, ReplayStatusResponse
from src.simulator.replay import replay_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/replay", tags=["Simulation Replay"])


@router.post("/start", response_model=ReplayStatusResponse)
async def start_replay(request: ReplayStartRequest | None = None) -> ReplayStatusResponse:
    """Start or resume corridor simulation replay."""
    date_str = request.date if request else None
    run_id = request.run_id if request else None
    speed = request.speed if request else 1.0

    status = replay_engine.start(sim_date=date_str, run_id=run_id, speed=speed)
    return ReplayStatusResponse(**status)


@router.post("/pause", response_model=ReplayStatusResponse)
async def pause_replay() -> ReplayStatusResponse:
    """Pause corridor simulation replay."""
    replay_engine.pause()
    return ReplayStatusResponse(**replay_engine.get_status())


@router.post("/speed", response_model=ReplayStatusResponse)
async def set_replay_speed(request: ReplaySpeedRequest) -> ReplayStatusResponse:
    """Update simulation replay speed multiplier."""
    if request.speed <= 0:
        raise HTTPException(status_code=400, detail="Speed multiplier must be positive.")
    replay_engine.set_speed(request.speed)
    return ReplayStatusResponse(**replay_engine.get_status())


@router.get("/status", response_model=ReplayStatusResponse)
async def get_replay_status() -> ReplayStatusResponse:
    """Query current status of the replay simulation engine."""
    return ReplayStatusResponse(**replay_engine.get_status())


@router.post("/step", response_model=ReplayStatusResponse)
async def step_replay(seconds: float = 300.0) -> ReplayStatusResponse:
    """Manually step simulation time forward by N seconds and broadcast updates."""
    await replay_engine.step(seconds=seconds)
    return ReplayStatusResponse(**replay_engine.get_status())
