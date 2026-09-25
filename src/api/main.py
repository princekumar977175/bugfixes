"""Main FastAPI application entrypoint."""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import replay, sections, trains, ws
from src.api.schemas import HealthResponse, StationItem, StationListResponse
from src.config import settings
from src.db.session import get_engine, init_db
from src.explain.explainer import ETAExplainer
from src.features.pipeline import FeaturePipeline
from src.models.ml_model import TrainDelayForecaster
from src.models.quantiles import QuantileForecaster
from src.simulator.replay import replay_engine

logger = logging.getLogger(__name__)


def init_forecast_engine() -> ETAExplainer | None:
    """Load machine learning models and attach explainer to the replay engine."""
    if replay_engine.explainer is not None:
        return replay_engine.explainer

    model_path = Path("models/v1_lgbm.pkl")
    quantile_path = Path("models/quantile_models.pkl")

    if not model_path.exists() or not quantile_path.exists():
        logger.warning("ML models not found on disk; forecast engine will not be available.")
        return None

    try:
        forecaster = TrainDelayForecaster.load(str(model_path))
        quantile_model = QuantileForecaster.load(str(quantile_path))

        pipeline = FeaturePipeline()
        pipeline.is_fitted = True
        pipeline.historical_mean_delay = {}
        pipeline.historical_std_delay = {}

        explainer = ETAExplainer(
            model=forecaster,
            pipeline=pipeline,
            quantile_model=quantile_model,
        )
        replay_engine.set_explainer(explainer)
        logger.info("Forecast engine and explainability models successfully initialized.")
        return explainer
    except Exception as e:
        logger.error(f"Failed to initialize forecast models: {e}", exc_info=True)
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup and shutdown events."""
    # 1. Startup: Initialize database schema
    engine = get_engine()
    init_db(engine)

    # 2. Load ML models and attach to replay engine
    init_forecast_engine()
    replay_engine.set_event_loop(asyncio.get_running_loop())

    yield

    # 3. Shutdown: Clean up replay worker
    replay_engine.stop()


app = FastAPI(
    title="SIH26028 Dynamic ETA Forecast API",
    description="Dynamic Forecast of Expected Time of Arrival (ETA) for Coaching Trains on Northern-NCR-ECR Corridor",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Routers
app.include_router(trains.router)
app.include_router(sections.router)
app.include_router(replay.router)
app.include_router(ws.router)


@app.get("/", tags=["Root"])
def root():
    """Root metadata endpoint."""
    return {
        "name": settings.APP_NAME,
        "version": "0.1.0",
        "description": "Dynamic Forecast of ETA for Coaching Trains (SIH26028)",
        "docs_url": "/docs",
        "health_url": "/health",
        "honesty_notice": "All data is simulated or replayed for research/demonstration purposes.",
    }


@app.get("/health", response_model=HealthResponse, tags=["Health"])
def health_check():
    """Health check endpoint to verify backend service readiness."""
    return HealthResponse(
        status="ok",
        app=settings.APP_NAME,
        environment=settings.ENVIRONMENT,
        timestamp=datetime.now(UTC).isoformat(),
    )


@app.get("/stations", response_model=StationListResponse, tags=["Corridor"])
def get_stations():
    """Retrieve all corridor stations with geographic coordinates for map rendering."""
    from src.simulator.corridor import SMALL_CORRIDOR_STATIONS

    items = [
        StationItem(
            code=s.code,
            name=s.name,
            lat=s.lat,
            lon=s.lon,
            zone=s.zone,
            is_junction=s.is_junction,
        )
        for s in SMALL_CORRIDOR_STATIONS
    ]
    return StationListResponse(total=len(items), stations=items)
