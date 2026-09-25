"""SQLAlchemy models for train operations, corridor infrastructure, schedules, and disruptions."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy declarative models."""

    pass


class Station(Base):
    """Station entity representing a geographic railway halt or junction."""

    __tablename__ = "stations"

    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    zone: Mapped[str] = mapped_column(String(10), nullable=False)  # e.g., NR, NCR, ECR
    is_junction: Mapped[bool] = mapped_column(default=False)

    # Relationships
    schedules: Mapped[list["Schedule"]] = relationship("Schedule", back_populates="station")


class Section(Base):
    """Section entity representing a directional block track between two stations."""

    __tablename__ = "sections"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)  # e.g. "NDLS-GZB-DN"
    from_station: Mapped[str] = mapped_column(String(10), ForeignKey("stations.code"), nullable=False)
    to_station: Mapped[str] = mapped_column(String(10), ForeignKey("stations.code"), nullable=False)
    distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    line_speed_kmph: Mapped[float] = mapped_column(Float, nullable=False)
    scheduled_runtime_min: Mapped[float] = mapped_column(Float, nullable=False)
    direction: Mapped[str] = mapped_column(String(5), default="DN")  # "UP" or "DN"

    # Relationships
    disruptions: Mapped[list["Disruption"]] = relationship("Disruption", back_populates="section")


class Train(Base):
    """Train entity defining static metadata and priority hierarchy."""

    __tablename__ = "trains"

    number: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)  # Vande Bharat, Rajdhani, Superfast, Mail, Passenger
    priority_class: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 (Highest) to 4 (Lowest)
    source: Mapped[str] = mapped_column(String(10), ForeignKey("stations.code"), nullable=False)
    destination: Mapped[str] = mapped_column(String(10), ForeignKey("stations.code"), nullable=False)

    # Relationships
    schedules: Mapped[list["Schedule"]] = relationship(
        "Schedule", back_populates="train", order_by="Schedule.seq"
    )
    runs: Mapped[list["Run"]] = relationship("Run", back_populates="train")


class Schedule(Base):
    """Static timetable schedule for a train at a specific sequence station."""

    __tablename__ = "schedules"

    train_number: Mapped[str] = mapped_column(String(10), ForeignKey("trains.number"), primary_key=True)
    station_code: Mapped[str] = mapped_column(String(10), ForeignKey("stations.code"), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    sched_arr: Mapped[str | None] = mapped_column(String(8), nullable=True)  # "HH:MM:SS" (None for origin)
    sched_dep: Mapped[str | None] = mapped_column(String(8), nullable=True)  # "HH:MM:SS" (None for destination)

    # Relationships
    train: Mapped["Train"] = relationship("Train", back_populates="schedules")
    station: Mapped["Station"] = relationship("Station", back_populates="schedules")

    __table_args__ = (
        Index("idx_schedules_train_seq", "train_number", "seq"),
    )


class Run(Base):
    """A specific operational date instance of a scheduled train."""

    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(50), primary_key=True)  # e.g., "12002_2025-11-01"
    train_number: Mapped[str] = mapped_column(String(10), ForeignKey("trains.number"), nullable=False)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Relationships
    train: Mapped["Train"] = relationship("Train", back_populates="runs")
    events: Mapped[list["RunEvent"]] = relationship(
        "RunEvent", back_populates="run", order_by="RunEvent.seq"
    )
    live_statuses: Mapped[list["LiveStatus"]] = relationship("LiveStatus", back_populates="run")
    eta_change_logs: Mapped[list["ETAChangeLog"]] = relationship(
        "ETAChangeLog", back_populates="run", order_by="ETAChangeLog.timestamp"
    )

    __table_args__ = (
        Index("idx_runs_train_date", "train_number", "run_date"),
    )


class RunEvent(Base):
    """Actual historical or replayed arrival/departure event at a station for a specific run."""

    __tablename__ = "run_events"

    run_id: Mapped[str] = mapped_column(String(50), ForeignKey("runs.run_id"), primary_key=True)
    station_code: Mapped[str] = mapped_column(String(10), ForeignKey("stations.code"), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_arr: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    actual_dep: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    arr_delay_min: Mapped[float] = mapped_column(Float, default=0.0)
    dwell_min: Mapped[float] = mapped_column(Float, default=0.0)

    # Relationships
    run: Mapped["Run"] = relationship("Run", back_populates="events")

    __table_args__ = (
        Index("idx_runevents_run_seq", "run_id", "seq"),
    )


class Disruption(Base):
    """External track or operational disruption affecting a section."""

    __tablename__ = "disruptions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    section_id: Mapped[str] = mapped_column(String(50), ForeignKey("sections.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)  # TSR, signal_halt, congestion, weather, maintenance_block
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    severity: Mapped[float] = mapped_column(Float, default=1.0)  # Severity factor 0.0 to 1.0 (or speed multiplier)

    # Relationships
    section: Mapped["Section"] = relationship("Section", back_populates="disruptions")

    __table_args__ = (
        Index("idx_disruptions_section_time", "section_id", "start_time", "end_time"),
    )


class LiveStatus(Base):
    """Real-time or simulated snapshot position and delay for an active train run."""

    __tablename__ = "live_status"

    run_id: Mapped[str] = mapped_column(String(50), ForeignKey("runs.run_id"), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, primary_key=True)
    current_station: Mapped[str | None] = mapped_column(String(10), nullable=True)
    next_station: Mapped[str | None] = mapped_column(String(10), nullable=True)
    current_section: Mapped[str | None] = mapped_column(String(50), nullable=True)
    current_delay_min: Mapped[float] = mapped_column(Float, default=0.0)
    speed_kmph: Mapped[float] = mapped_column(Float, default=0.0)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)

    # Relationships
    run: Mapped["Run"] = relationship("Run", back_populates="live_statuses")

    __table_args__ = (
        Index("idx_livestatus_run_ts", "run_id", "ts"),
    )


class ETAChangeLog(Base):
    """Log entry recording an ETA revision for a train run and station."""

    __tablename__ = "eta_change_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(50), ForeignKey("runs.run_id"), nullable=False)
    station_code: Mapped[str] = mapped_column(String(10), ForeignKey("stations.code"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    old_eta: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    new_eta: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    delta_min: Mapped[float] = mapped_column(Float, default=0.0)
    reasons: Mapped[str] = mapped_column(String(500), nullable=False)
    drivers_json: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Relationships
    run: Mapped["Run"] = relationship("Run", back_populates="eta_change_logs")
    station: Mapped["Station"] = relationship("Station")

    __table_args__ = (
        Index("idx_etachanges_run_ts", "run_id", "timestamp"),
        Index("idx_etachanges_run_station", "run_id", "station_code"),
    )

