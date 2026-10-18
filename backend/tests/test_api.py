from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_hello():
    r = client.get("/hello")
    assert r.status_code == 200
    assert r.json() == {"message": "Hello, BI Agent!"}


def test_unknown_route_returns_404():
    assert client.get("/nope").status_code == 404


def test_request_id_generated_when_missing():
    r = client.get("/health")
    assert r.headers["X-Request-ID"]


def test_request_id_echoed_when_provided():
    r = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert r.headers["X-Request-ID"] == "abc-123"