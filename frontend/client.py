import os
import uuid
import requests

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


class BackendError(Exception):
    """The backend is unreachable or returned an error."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code

def _detail(r):
    try:
        return str(r.json()["detail"])
    except (ValueError, KeyError, TypeError):
        return f"Backend returned status {r.status_code}."

def get_json(path: str, timeout: float = 5.0, token=None) -> dict:
    headers = {"X-Request-ID": str(uuid.uuid4())}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.get(f"{BACKEND_URL}{path}", headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.Timeout as e:
        raise BackendError("The backend took too long to respond.") from e
    except requests.ConnectionError as e:
        raise BackendError("Cannot reach the backend. Is it running?") from e
    except requests.HTTPError as e:
        raise BackendError(_detail(r), r.status_code) from e
    except ValueError as e:
        raise BackendError("Backend returned invalid JSON.") from e

def post_json(path: str, payload: dict, timeout: float = 90.0, token=None) -> dict:
    headers = {"X-Request-ID": str(uuid.uuid4())}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.post(
            f"{BACKEND_URL}{path}",
            json=payload,
            headers=headers,
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json()
    except requests.Timeout as e:
        raise BackendError("The backend took too long to respond.") from e
    except requests.ConnectionError as e:
        raise BackendError("Cannot reach the backend. Is it running?") from e
    except requests.HTTPError as e:
        raise BackendError(_detail(r), r.status_code) from e
    except ValueError as e:
        raise BackendError("Backend returned invalid JSON.") from e


def login(username, password):
    return post_json("/auth/login", {"username": username, "password": password}, timeout=15.0)