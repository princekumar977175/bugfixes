"""Pydantic request and response schemas for all REST and WebSocket API endpoints."""

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    """Health check response schema."""
    status: str = Field("ok", description="Service health status")
    app: str = Field(..., description="Application name")
    environment: str = Field(..., description="Deployment environment")
    timestamp: str = Field(..., description="ISO 8601 current timestamp")


class TrainListItem(BaseModel):
    """Running train status overview."""
    run_id: str = Field(..., description="Unique run identifier (e.g. 12002_2026-01-15)")
    train_number: str = Field(..., description="Indian Railways train number (e.g. 12002)")
    train_name: str = Field(..., description="Train commercial name")
    train_type: str = Field(..., description="Train category (Vande Bharat, Rajdhani, Superfast, etc.)")
    priority_class: int = Field(..., description="Priority tier (1=Highest to 4=Lowest)")
    source: str = Field(..., description="Origin station code")
    destination: str = Field(..., description="Terminus station code")
    run_date: date = Field(..., description="Scheduled date of the run")
    current_station: str | None = Field(None, description="Station code of current or most recent stop")
    next_station: str | None = Field(None, description="Station code of upcoming stop")
    current_delay_min: float = Field(0.0, description="Current operational delay in minutes")
    status: str = Field("running", description="Operational status: scheduled, running, completed")
    knock_on_risk: str = Field("low", description="Downstream knock-on risk tier: low, medium, high")


class TrainListResponse(BaseModel):
    """Response containing list of trains on corridor."""
    total: int = Field(..., description="Total trains returned")
    trains: list[TrainListItem] = Field(..., description="List of train items")


class StationItem(BaseModel):
    """Corridor station geographic and infrastructure definition."""
    code: str = Field(..., description="Station code")
    name: str = Field(..., description="Station name")
    lat: float = Field(..., description="Latitude coordinate")
    lon: float = Field(..., description="Longitude coordinate")
    zone: str = Field(..., description="Railway zone code")
    is_junction: bool = Field(False, description="Whether station is a junction")


class StationListResponse(BaseModel):
    """List of corridor stations."""
    total: int = Field(..., description="Total stations returned")
    stations: list[StationItem] = Field(..., description="List of stations")


class StationETAForecast(BaseModel):
    """Downstream station ETA forecast with lower, median, and upper bounds."""
    station_code: str = Field(..., description="IR station code")
    station_name: str = Field(..., description="Full station name")
    seq: int = Field(..., description="Route sequence index")
    stations_ahead: int = Field(..., description="Number of station hops ahead of current position")
    sched_arr: str = Field(..., description="Scheduled timetable arrival (ISO datetime)")
    actual_arr: str | None = Field(None, description="Actual arrival if already passed (ISO datetime)")
    baseline_a_eta: str = Field(..., description="Baseline A (scheduled + current delay) ETA")
    eta_lower: str = Field(..., description="Predicted 10th percentile ETA (lower bound)")
    eta_median: str = Field(..., description="Predicted 50th percentile ETA (median forecast)")
    eta_upper: str = Field(..., description="Predicted 90th percentile ETA (upper bound)")
    interval_width_min: float = Field(..., description="10th-90th prediction interval width in minutes")
    predicted_median_delay_min: float = Field(..., description="Predicted delay at this station in minutes")
    reasons: str = Field(..., description="Plain-language explanation of ETA and delay drivers")


class TrainETAResponse(BaseModel):
    """Downstream ETA forecast for all remaining stations of a train run."""
    run_id: str = Field(..., description="Run identifier")
    train_number: str = Field(..., description="Train number")
    train_name: str = Field(..., description="Train name")
    as_of_timestamp: str = Field(..., description="Timestamp of forecast calculation")
    current_station: str = Field(..., description="Current position station code")
    current_delay_min: float = Field(..., description="Current delay at observation point")
    downstream_stations: list[StationETAForecast] = Field(..., description="Forecasts for all remaining stations")


class DriverAttribution(BaseModel):
    """Shapley driver attribution for a feature."""
    feature: str = Field(..., description="Feature column identifier")
    label: str = Field(..., description="Human-readable driver label")
    shap_value: float = Field(..., description="Shapley delay contribution in minutes")
    importance: float = Field(..., description="Absolute Shapley importance in minutes")
    feature_val: Any = Field(..., description="Observed feature value")
    category: str = Field(..., description="Operational category: tsr, congestion, weather, headway, etc.")


class ETAChangeLogItem(BaseModel):
    """Historical revision log entry for an ETA."""
    id: int = Field(..., description="Change log record ID")
    station_code: str = Field(..., description="Target station code")
    timestamp: str = Field(..., description="Time of revision")
    old_eta: str | None = Field(None, description="Previous ETA")
    new_eta: str = Field(..., description="Updated ETA")
    delta_min: float = Field(..., description="Minutes revised")
    reasons: str = Field(..., description="Plain-language explanation")


class TrainExplainResponse(BaseModel):
    """Explainability details for the latest ETA revision of a train run."""
    run_id: str = Field(..., description="Run identifier")
    train_number: str = Field(..., description="Train number")
    train_name: str = Field(..., description="Train name")
    as_of_timestamp: str = Field(..., description="Timestamp of explanation")
    latest_explanation: str = Field(..., description="Latest plain-language reason string")
    delta_min: float = Field(..., description="Latest delay revision delta in minutes")
    top_drivers: list[DriverAttribution] = Field(..., description="Top 3 extracted SHAP drivers")
    change_history: list[ETAChangeLogItem] = Field(default_factory=list, description="Recent ETA change history")


class DisruptionItem(BaseModel):
    """Section disruption event record."""
    id: str = Field(..., description="Unique disruption identifier")
    section_id: str = Field(..., description="Affected corridor section block ID")
    type: str = Field(..., description="Disruption type: TSR, congestion, weather, signal_halt")
    start_time: str = Field(..., description="Active start time (ISO datetime)")
    end_time: str = Field(..., description="Active end time (ISO datetime)")
    severity: float = Field(..., description="Severity scaling factor (0.0 to 1.0)")


class SectionDisruptionsResponse(BaseModel):
    """Disruptions on a section or corridor."""
    section_id: str = Field(..., description="Section queried (or 'all')")
    total: int = Field(..., description="Total disruptions count")
    disruptions: list[DisruptionItem] = Field(..., description="List of disruption events")


class ReplayStartRequest(BaseModel):
    """Request payload to initiate or resume simulated replay."""
    date: str | None = Field(None, description="Simulation date (YYYY-MM-DD), defaults to latest test date")
    run_id: str | None = Field(None, description="Optional focus run ID")
    speed: float = Field(1.0, ge=0.1, le=120.0, description="Simulation speed multiplier (1x to 120x)")


class ReplaySpeedRequest(BaseModel):
    """Request payload to adjust replay speed."""
    speed: float = Field(..., ge=0.1, le=120.0, description="New speed multiplier")


class ReplayStatusResponse(BaseModel):
    """Current state of the simulation replay engine."""
    status: str = Field(..., description="Engine status: running, paused, stopped")
    current_sim_time: str = Field(..., description="Current simulated corridor clock (ISO datetime)")
    speed: float = Field(..., description="Current speed multiplier")
    active_run_id: str | None = Field(None, description="Focused train run ID if applicable")


class WebSocketETAUpdate(BaseModel):
    """WebSocket payload streamed to live clients."""
    model_config = ConfigDict(extra="allow")

    type: str = Field("eta_update", description="Message type")
    run_id: str = Field(..., description="Train run ID")
    sim_time: str = Field(..., description="Simulated timestamp")
    current_station: str = Field(..., description="Current station code")
    current_delay_min: float = Field(..., description="Current delay in minutes")
    predictions: list[StationETAForecast] = Field(..., description="Downstream station ETA predictions")
