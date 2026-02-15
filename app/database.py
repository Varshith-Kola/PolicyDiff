"""Database setup with SQLAlchemy.

Supports SQLite (default, single-instance) and PostgreSQL (production).
Session management is designed so that:
  - Each FastAPI request gets its own session via ``get_db``.
  - Background tasks and concurrent pipelines use ``get_scoped_session``
    to obtain independent sessions that don't interfere with each other.
"""

import os
import logging
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session

from app.config import settings

logger = logging.getLogger(__name__)

# Ensure the data directory exists (for SQLite)
if settings.database_url.startswith("sqlite"):
    os.makedirs("data", exist_ok=True)

# Build engine with appropriate connect_args
_connect_args = {}
if settings.database_url.startswith("sqlite"):
    _connect_args["check_same_thread"] = False

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    echo=False,
    pool_pre_ping=True,  # Detect stale connections
)


# Enable WAL mode and foreign keys for SQLite
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    if settings.database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency that yields a request-scoped database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_scoped_session() -> Session:
    """Context manager that provides an independent database session.

    Use this in background tasks, concurrent pipelines, and any code
    that runs outside the FastAPI request lifecycle to avoid sharing
    sessions across coroutines.

    Usage:
        with get_scoped_session() as db:
            policy = db.query(Policy).first()
            ...
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _col_default_sql(col) -> str:
    """Return a SQL DEFAULT clause for a column, or empty string."""
    if col.default is None or not col.default.is_scalar:
        return ""
    val = col.default.arg
    if isinstance(val, bool):
        return f" DEFAULT {1 if val else 0}"
    if isinstance(val, (int, float)):
        return f" DEFAULT {val}"
    if isinstance(val, str):
        return f" DEFAULT '{val}'"
    return ""


def _auto_migrate_sqlite():
    """Add missing columns to existing SQLite tables.

    SQLAlchemy's ``create_all`` only creates new tables — it won't add
    columns to tables that already exist.  This function inspects the
    model metadata and issues ``ALTER TABLE ADD COLUMN`` for any columns
    missing from the live schema.  Safe to call on every startup.
    """
    from sqlalchemy import inspect as sa_inspect, text

    inspector = sa_inspect(engine)
    with engine.connect() as conn:
        for table_name, table in Base.metadata.tables.items():
            if not inspector.has_table(table_name):
                continue
            existing = {c["name"] for c in inspector.get_columns(table_name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                col_type = col.type.compile(dialect=engine.dialect)
                nullable = "NULL" if col.nullable else "NOT NULL"
                default = _col_default_sql(col)
                sql = f'ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type} {nullable}{default}'
                logger.info(f"Auto-migrate: {sql}")
                conn.execute(text(sql))
        conn.commit()


def init_db():
    """Create all tables if they don't exist, then add any missing columns."""
    Base.metadata.create_all(bind=engine)
    if settings.database_url.startswith("sqlite"):
        _auto_migrate_sqlite()
    logger.info("Database tables ensured")
