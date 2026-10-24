import json
import logging
import os
from datetime import datetime, timezone

from app.privacy import redact_text, redact_value

_STANDARD = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact_value(record.getMessage()),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD and not key.startswith("_"):
                entry[key] = redact_value(value)              # GR-PRIV-02
        if record.exc_info:
            entry["exc"] = redact_value(self.formatException(record.exc_info))
        return json.dumps(entry, default=str)


class RedactingFormatter(logging.Formatter):
    """The plain-text format, with the same masking (GR-PRIV-02)."""

    def format(self, record):
        return redact_text(super().format(record))[0]


def configure_logging():
    handler = logging.StreamHandler()
    if os.getenv("LOG_FORMAT", "json") == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(os.getenv("LOG_LEVEL", "INFO"))
