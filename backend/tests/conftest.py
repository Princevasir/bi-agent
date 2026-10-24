import os

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 32)
os.environ.setdefault("APP_DATABASE_URL", "postgresql://app_rw:app_dev_pw@localhost:5433/appdb")
os.environ.setdefault("TEST_ADMIN_APP_URL", "postgresql://admin:admin_dev_pw@localhost:5433/appdb")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://bi_readonly:readonly_dev_pw@localhost:5433/analytics",
)
os.environ.setdefault("DATABASE_URL_LIMITED", "postgresql://bi_limited:limited_dev_pw@localhost:5433/analytics")
os.environ.setdefault("RETAIL_DATABASE_URL", "postgresql://retail_analyst:retail_analyst_dev_pw@localhost:5433/retail_test")
os.environ.setdefault("RETAIL_DATABASE_URL_LIMITED", "postgresql://retail_limited:retail_limited_dev_pw@localhost:5433/retail_test")
os.environ.pop("DATA_SOURCE", None)   # tests choose the data source themselves

from app.appdb import User  # noqa: E402
from app.auth import current_user  # noqa: E402
from app.main import app, get_knowledge  # noqa: E402
from app import audit  # noqa: E402
from app import main as main_module  # noqa: E402
from app.throttle import LoginThrottle  # noqa: E402


@pytest.fixture(autouse=True)
def signed_in_analyst():
    app.dependency_overrides[current_user] = lambda: User(username="test-analyst", role="analyst")
    yield


@pytest.fixture(autouse=True)
def no_knowledge():
    """RAG R6: tests never reach the embedding model or the real index unless they ask to."""
    app.dependency_overrides[get_knowledge] = lambda: (lambda question, role: [])
    yield


@pytest.fixture(autouse=True)
def audit_events(monkeypatch):
    events = []
    monkeypatch.setattr(audit, "_write", events.append)
    return events


@pytest.fixture(autouse=True)
def generous_request_limits(monkeypatch):
    """GR-COST-01/03: tests ask many questions as one user; tests of the limits install their own."""
    from app.request_limits import MemoryRunning, RateLimiter
    monkeypatch.setattr(main_module, "rate_limiter", RateLimiter(per_minute=10**6, per_day=10**6))
    monkeypatch.setattr(main_module, "running", MemoryRunning())


@pytest.fixture(autouse=True)
def fresh_login_throttle(monkeypatch):
    monkeypatch.setattr(main_module, "throttle", LoginThrottle())
