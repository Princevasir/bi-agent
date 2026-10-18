import os
import uuid
import requests

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


class BackendError(Exception):
    """The backend is unreachable or returned an error."""


def get_json(path: str, timeout: float = 5.0) -> dict:
    try:
        r = requests.get(
        f"{BACKEND_URL}{path}",
        headers={"X-Request-ID": str(uuid.uuid4())},
        timeout=timeout,
        )
        r.raise_for_status()
        return r.json()
    except requests.Timeout as e:
        raise BackendError("The backend took too long to respond.") from e
    except requests.ConnectionError as e:
        raise BackendError("Cannot reach the backend. Is it running?") from e
    except requests.HTTPError as e:
        raise BackendError(f"Backend returned status {r.status_code}.") from e
    except ValueError as e:
        raise BackendError("Backend returned invalid JSON.") from e