"""Shared pytest fixtures for PolicyDiff tests.

Uses a file-based SQLite temp database so that the app's module-level
engine, the lifespan ``init_db()``, and the test overrides all share
the same database.
"""

import os
import tempfile
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

# Override settings BEFORE importing the app
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"
os.environ["OPENAI_API_KEY"] = ""
os.environ["API_KEY"] = ""  # Disable auth for tests
os.environ["GOOGLE_CLIENT_ID"] = ""  # Disable Google OAuth for tests
os.environ["GOOGLE_CLIENT_SECRET"] = ""

from app.database import Base, get_db, engine, SessionLocal
from app.main import app
from app.models import Policy, Snapshot, Diff
from app.utils.datetime_helpers import utcnow


@pytest.fixture(autouse=True)
def _reset_tables():
    """Drop and recreate all tables before each test for isolation."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture(scope="function")
def db_session():
    """Provide a DB session for direct data manipulation in tests."""
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture(scope="function")
def client():
    """FastAPI TestClient — uses the app's own engine and SessionLocal."""
    with TestClient(app) as c:
        yield c


# ---- Factory Helpers ----

@pytest.fixture
def make_policy(db_session):
    """Factory fixture to create a Policy."""
    def _make(**kwargs):
        defaults = {
            "name": "Test Privacy Policy",
            "company": "TestCo",
            "url": "https://example.com/privacy",
            "policy_type": "privacy_policy",
            "is_active": True,
            "check_interval_hours": 24,
        }
        defaults.update(kwargs)
        policy = Policy(**defaults)
        db_session.add(policy)
        db_session.commit()
        db_session.refresh(policy)
        return policy
    return _make


@pytest.fixture
def make_snapshot(db_session):
    """Factory fixture to create a Snapshot."""
    def _make(policy_id, content="Test policy content " * 20, **kwargs):
        from app.services.scraper import compute_hash
        defaults = {
            "policy_id": policy_id,
            "content_text": content,
            "content_hash": compute_hash(content),
            "content_length": len(content),
        }
        defaults.update(kwargs)
        snap = Snapshot(**defaults)
        db_session.add(snap)
        db_session.commit()
        db_session.refresh(snap)
        return snap
    return _make
