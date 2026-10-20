import pytest
import requests

import client


class FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {"message": "Hello, BI Agent!"}


class FakePostResponse:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError()

    def json(self):
        return self.data


def test_get_json_success(monkeypatch):
    monkeypatch.setattr(client.requests, "get", lambda *a, **k: FakeResponse())
    assert client.get_json("/hello") == {"message": "Hello, BI Agent!"}


def test_unreachable_backend(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError()

    monkeypatch.setattr(client.requests, "get", boom)
    with pytest.raises(client.BackendError):
        client.get_json("/hello")


def test_post_json_success(monkeypatch):
    monkeypatch.setattr(client.requests, "post", lambda *a, **k: FakePostResponse({"answer": "ok"}))
    assert client.post_json("/ask", {"message": "hi"}) == {"answer": "ok"}


def test_post_json_error_keeps_status_and_detail(monkeypatch):
    resp = FakePostResponse({"detail": "Conversation not found."}, 404)
    monkeypatch.setattr(client.requests, "post", lambda *a, **k: resp)
    with pytest.raises(client.BackendError) as exc:
        client.post_json("/ask", {})
    assert exc.value.status_code == 404
    assert "Conversation not found." in str(exc.value)


def test_post_json_unreachable(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError()

    monkeypatch.setattr(client.requests, "post", boom)
    with pytest.raises(client.BackendError):
        client.post_json("/ask", {})