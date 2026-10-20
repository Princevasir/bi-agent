import time
import uuid

import jwt
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.appdb import User, create_user
from app.auth import (
    AuthConfigError, AuthError, authenticate, create_token, current_user,
    decode_token, hash_password, verify_password,
)
from app.main import app

client = TestClient(app)
SECRET = "test-secret-" + "x" * 32


def test_password_roundtrip_and_wrong_password():
    h = hash_password("correct horse battery")
    assert verify_password("correct horse battery", h)
    assert not verify_password("wrong", h)


def test_garbage_hash_is_a_failed_login_not_a_crash():
    assert not verify_password("anything", "not-a-hash")


def test_unknown_user_fails_and_inactive_user_fails():
    assert not authenticate(None, "x")
    h = hash_password("correct horse battery")
    assert not authenticate(User("a", "analyst", is_active=False, password_hash=h), "correct horse battery")


def test_token_roundtrip():
    claims = decode_token(create_token("alice", "analyst"))
    assert claims["sub"] == "alice"


def test_expired_token_is_rejected():
    token = jwt.encode({"sub": "a", "exp": int(time.time()) - 10}, SECRET, algorithm="HS256")
    with pytest.raises(AuthError):
        decode_token(token)


def test_token_signed_with_another_secret_is_rejected():
    token = jwt.encode({"sub": "a", "exp": int(time.time()) + 60}, "y" * 40, algorithm="HS256")
    with pytest.raises(AuthError):
        decode_token(token)


def test_unsigned_token_is_rejected():
    token = jwt.encode({"sub": "a", "exp": int(time.time()) + 60}, None, algorithm="none")
    with pytest.raises(AuthError):
        decode_token(token)


def test_missing_secret_is_a_config_error(monkeypatch):
    monkeypatch.delenv("JWT_SECRET")
    with pytest.raises(AuthConfigError):
        create_token("a", "analyst")
        

@pytest.fixture
def real_auth():
    app.dependency_overrides.pop(current_user, None)


@pytest.fixture
def account(real_auth):
    name = f"test-{uuid.uuid4().hex[:8]}"
    create_user(name, hash_password("correct horse battery"), "analyst")
    yield name
    import os
    with psycopg.connect(os.environ["TEST_ADMIN_APP_URL"]) as conn:
        conn.execute("DELETE FROM users WHERE username = %s", (name,))


def login(name, password="correct horse battery"):
    return client.post("/auth/login", json={"username": name, "password": password})


@pytest.mark.integration
def test_login_returns_a_token_that_opens_protected_routes(account):
    r = login(account)
    assert r.status_code == 200 and r.json()["role"] == "analyst"
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/schema", headers=headers).status_code == 200


@pytest.mark.integration
def test_wrong_password_and_unknown_user_get_the_same_error(account):
    wrong = login(account, "wrong password!!")
    unknown = login("nobody-here")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Invalid username or password."}


@pytest.mark.integration
def test_deactivated_user_loses_access_immediately(account):
    import os
    token = login(account).json()["access_token"]
    with psycopg.connect(os.environ["TEST_ADMIN_APP_URL"]) as conn:
        conn.execute("UPDATE users SET is_active = FALSE WHERE username = %s", (account,))
    r = client.get("/schema", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


@pytest.mark.parametrize("method, path", [
    ("GET", "/schema"), ("GET", "/db/ping"), ("POST", "/chat"), ("POST", "/ask"),
    ("POST", "/ask/sql"), ("GET", f"/conversations/{uuid.uuid4()}"),
])
def test_protected_routes_reject_missing_and_bad_tokens(real_auth, method, path):
    assert client.request(method, path).status_code == 401
    bad = {"Authorization": "Bearer not-a-token"}
    assert client.request(method, path, headers=bad).status_code == 401


def test_health_stays_public(real_auth):
    assert client.get("/health").status_code == 200