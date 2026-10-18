import pytest
import requests

import client


class FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {"message": "Hello, BI Agent!"}


def test_get_json_success(monkeypatch):
    monkeypatch.setattr(client.requests, "get", lambda *a, **k: FakeResponse())
    assert client.get_json("/hello") == {"message": "Hello, BI Agent!"}


def test_unreachable_backend(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError()

    monkeypatch.setattr(client.requests, "get", boom)
    with pytest.raises(client.BackendError):
        client.get_json("/hello")