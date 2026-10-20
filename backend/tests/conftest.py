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

from app.appdb import User  # noqa: E402
from app.auth import current_user  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def signed_in_analyst():
    app.dependency_overrides[current_user] = lambda: User(username="test-analyst", role="analyst")
    yield
