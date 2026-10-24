"""Personal data never reaches the model, the logs or the audit trail (GR-PRIV-01, GR-PRIV-02).

Columns the catalog flags as personal (names, email, phone, street, postal code, salary) are masked
whole; in any other text, email addresses and phone numbers are masked by pattern. Dates, amounts
and product codes are left alone. The user's own screen still gets the full result their role may
see: this only cleans what is sent onwards.
"""
import re
from functools import lru_cache

REDACTED = "[redacted]"
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
PHONE = re.compile(r"(?<![\w.])(?:\+\d[\d \-().]{6,}\d"            # +1-555-0000001, +31 555 000 0004
                   r"|\(\d{2,4}\)\s?\d[\d \-.]{4,}\d"                  # (555) 123-4567
                   r"|\d{3}[ .-]\d{3}[ .-]\d{4})(?![\w])")             # 555-123-4567


@lru_cache(maxsize=1)
def personal_column_names():
    from app import catalog
    return frozenset(c.name.lower() for t in catalog.get().tables.values() for c in t.columns.values() if c.pii)


def redact_text(text):
    """(text with emails and phone numbers masked, how many were masked)."""
    text, emails = EMAIL.subn(REDACTED, text)
    text, phones = PHONE.subn(REDACTED, text)
    return text, emails + phones


def redact_rows(columns, rows):
    """(rows safe to show the model, how many values were masked)."""
    personal = {i for i, c in enumerate(columns) if str(c).lower() in personal_column_names()}
    out, count = [], 0
    for row in rows:
        clean = []
        for i, v in enumerate(row):
            if i in personal and v is not None:
                clean.append(REDACTED)
                count += 1
            elif isinstance(v, str):
                masked, n = redact_text(v)
                clean.append(masked)
                count += n
            else:
                clean.append(v)
        out.append(clean)
    return out, count


def redact_value(value):
    """Mask emails and phone numbers anywhere in a log or audit value (strings, dicts, lists)."""
    if isinstance(value, str):
        return redact_text(value)[0]
    if isinstance(value, dict):
        return {k: redact_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(v) for v in value]
    return value
