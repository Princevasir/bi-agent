"""Demo gap D4: the project sets itself up in three commands (scripts/setup.sh and its helpers)."""
import importlib.util
import io
from pathlib import Path

import pytest

from app import cli

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("prepare_env", ROOT / "scripts" / "prepare_env.py")
prepare_env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_env)

EXAMPLE = "LOG_LEVEL=INFO\n# a comment\nLLM_PROVIDER=ollama\nDATA_SOURCE=retail\nJWT_SECRET=\n"


@pytest.fixture
def files(tmp_path):
    example = tmp_path / ".env.example"
    example.write_text(EXAMPLE)
    return tmp_path / ".env", example


def values(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if line and not line.startswith("#"))


# ---- preparing .env -------------------------------------------------------------------------------------

def test_a_missing_env_file_is_created_from_the_example_with_a_secret(files):
    env, example = files
    changed = prepare_env.prepare(env, example)
    v = values(env)
    assert v["LLM_PROVIDER"] == "ollama" and v["DATA_SOURCE"] == "retail"
    assert len(v["JWT_SECRET"]) == 64 and int(v["JWT_SECRET"], 16) >= 0
    assert "JWT_SECRET" in changed


def test_existing_values_are_never_changed(files):
    env, example = files
    env.write_text("LLM_PROVIDER=groq\nJWT_SECRET=" + "k" * 40 + "\n")
    prepare_env.prepare(env, example)
    v = values(env)
    assert v["LLM_PROVIDER"] == "groq" and v["JWT_SECRET"] == "k" * 40


def test_missing_keys_are_added_from_the_example(files):
    env, example = files
    env.write_text("LLM_PROVIDER=groq\nJWT_SECRET=" + "k" * 40 + "\n")
    assert prepare_env.prepare(env, example) == ["LOG_LEVEL", "DATA_SOURCE"]
    assert values(env)["DATA_SOURCE"] == "retail"


def test_a_short_or_empty_secret_is_replaced(files):
    env, example = files
    env.write_text("JWT_SECRET=short\n")
    prepare_env.prepare(env, example)
    assert len(values(env)["JWT_SECRET"]) == 64


def test_a_file_without_a_final_newline_is_not_corrupted(files):
    env, example = files
    env.write_text("JWT_SECRET=" + "k" * 40)                  # no newline: appending must not glue lines
    prepare_env.prepare(env, example)
    assert values(env)["JWT_SECRET"] == "k" * 40 and values(env)["LLM_PROVIDER"] == "ollama"


def test_the_old_file_is_backed_up_before_any_change(files):
    env, example = files
    env.write_text("JWT_SECRET=short\n")
    prepare_env.prepare(env, example)
    [backup] = list(env.parent.glob(".env.backup-*"))
    assert backup.read_text() == "JWT_SECRET=short\n"


def test_nothing_to_do_means_no_backup_and_no_change(files):
    env, example = files
    full = "LOG_LEVEL=INFO\nLLM_PROVIDER=ollama\nDATA_SOURCE=retail\nJWT_SECRET=" + "k" * 40 + "\n"
    env.write_text(full)
    assert prepare_env.prepare(env, example) == []
    assert env.read_text() == full and not list(env.parent.glob(".env.backup-*"))


def test_values_are_never_printed(files, capsys):
    env, example = files
    prepare_env.main([str(env), str(example)])
    out = capsys.readouterr().out
    assert values(env)["JWT_SECRET"] not in out and "JWT_SECRET" in out


def test_the_real_example_is_ready_for_the_demo():
    v = values(ROOT / ".env.example")
    assert v["LLM_PROVIDER"] == "ollama" and v["DATA_SOURCE"] == "retail" and v["JWT_SECRET"] == ""
    assert int(v["LLM_TIMEOUT_SECONDS"]) >= 60


# ---- creating demo users without a terminal ------------------------------------------------------------

@pytest.fixture
def users(monkeypatch):
    made = {}
    monkeypatch.setattr(cli, "create_user", lambda name, hashed, role: made.__setitem__(name, role))
    monkeypatch.setattr(cli, "get_user", lambda name: object() if name in ("taken",) else None)
    monkeypatch.setattr(cli, "hash_password", lambda p: "hashed")
    return made


def test_the_password_can_come_from_standard_input(users, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("a-long-demo-password\n"))
    assert cli.main(["cli", "create-user", "demo-analyst", "analyst", "--password-stdin"]) == 0
    assert users == {"demo-analyst": "analyst"}


def test_a_short_password_from_standard_input_is_refused(users, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    assert cli.main(["cli", "create-user", "demo-analyst", "analyst", "--password-stdin"]) == 1
    assert users == {}


def test_an_existing_user_is_fine_with_exist_ok(users, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("a-long-demo-password\n"))
    assert cli.main(["cli", "create-user", "taken", "analyst", "--password-stdin", "--exist-ok"]) == 0
    assert users == {} and "already exists" in capsys.readouterr().out


def test_unknown_options_and_roles_are_refused(users):
    assert cli.main(["cli", "create-user", "x", "analyst", "--sudo"]) == 2
    assert cli.main(["cli", "create-user", "x", "admin"]) == 2
