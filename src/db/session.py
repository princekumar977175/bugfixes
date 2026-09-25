"""Database engine, session management, and schema initialization."""

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from src.config import settings
from src.db.models import Base


def get_engine(db_url: str | None = None) -> Engine:
    """Create SQLAlchemy engine with appropriate dialect arguments."""
    url = db_url or settings.DATABASE_URL
    connect_args = {}

    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        # Ensure parent directory exists for file-based sqlite databases
        if "///" in url and not url.startswith("sqlite:///:memory:"):
            db_path = url.split("///")[-1]
            parent = Path(db_path).parent
            parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(url, connect_args=connect_args)

    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db(target_engine: Engine | None = None) -> None:
    """Create all tables in the database if they do not exist."""
    eng = target_engine or engine
    Base.metadata.create_all(bind=eng)


def get_db() -> Generator[Session, None, None]:
    """Dependency for obtaining a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
