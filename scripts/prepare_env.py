"""Prepare .env for the demo without ever printing a value (demo gap D4).

Creates .env from .env.example if it is missing, adds keys the example has and .env lacks, and
generates JWT_SECRET when it is empty or too short. Existing values are never changed. The old
file is backed up before any change, and a missing final newline is fixed before appending (an
append once glued a new line onto JWT_SECRET). Standard library only, so it runs before any setup.

Usage: python3 scripts/prepare_env.py [.env] [.env.example]
"""
import secrets
import shutil
import sys
import time
from pathlib import Path

MIN_SECRET = 32


def _keys(text):
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip()
    return out


def prepare(env, example):
    """Bring env up to date with example; returns the names of the keys added or filled in."""
    env, example = Path(env), Path(example)
    text = env.read_text() if env.exists() else ""
    current, wanted = _keys(text), _keys(example.read_text())
    lines, changed = text.splitlines(), []
    for key, value in wanted.items():
        if key not in current:
            lines.append(f"{key}={value}")
            current[key] = value
            changed.append(key)
    if len(current.get("JWT_SECRET", "")) < MIN_SECRET:
        secret = secrets.token_hex(32)
        lines = [f"JWT_SECRET={secret}" if ln.strip().startswith("JWT_SECRET=") else ln for ln in lines]
        if "JWT_SECRET" not in changed:
            changed.append("JWT_SECRET")
    if not changed:
        return []
    if env.exists():
        shutil.copy2(env, env.with_name(f".env.backup-{time.strftime('%Y%m%d-%H%M%S')}"))
    env.write_text("\n".join(lines) + "\n")
    return changed


def main(argv):
    env = argv[0] if argv else ".env"
    example = argv[1] if len(argv) > 1 else ".env.example"
    changed = prepare(env, example)
    print(f"{env}: " + (f"set {', '.join(changed)}" if changed else "already complete"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
