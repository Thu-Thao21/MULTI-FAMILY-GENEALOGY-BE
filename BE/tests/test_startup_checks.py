"""Startup configuration checks (fail closed) and their placement (Mốc G).

The checks run in the app startup event, never at import: importing app.main, alembic's
env.py or a TestClient without a startup context must work without Firebase settings.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.core.config import Settings
from app.core.firebase import EMULATOR_ENV
from app.core.startup_checks import ConfigurationError, find_config_problems, validate_runtime_config

BE_DIR = Path(__file__).resolve().parents[1]
DB_URL = "postgresql+psycopg://user:pw@localhost:5432/db"
SECRET_PATH = "Z:/definitely/secret-location/sa-key-7f3a9c.json"
SECRET_ORIGIN = "https://secret-frontend-7f3a9c.example"


def make_settings(**overrides) -> Settings:
    values = dict(
        DATABASE_URL=DB_URL,
        FIREBASE_PROJECT_ID="test-project",
        FIREBASE_SERVICE_ACCOUNT_PATH="",
        FRONTEND_ORIGINS="http://localhost:5173",
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_valid_configuration_has_no_problems(tmp_path):
    assert find_config_problems(make_settings(), {}) == []
    key = tmp_path / "sa.json"
    key.write_text("not a real key: the check must never open this file")
    assert find_config_problems(make_settings(FIREBASE_SERVICE_ACCOUNT_PATH=str(key)), {}) == []


@pytest.mark.parametrize("project_id", ["", "   "])
def test_missing_firebase_project_id_is_a_problem(project_id):
    problems = find_config_problems(make_settings(FIREBASE_PROJECT_ID=project_id), {})
    assert len(problems) == 1 and problems[0].startswith("FIREBASE_PROJECT_ID")


def test_emulator_variable_is_a_problem():
    problems = find_config_problems(make_settings(), {EMULATOR_ENV: "localhost:9099"})
    assert len(problems) == 1 and problems[0].startswith(EMULATOR_ENV)


def test_service_account_path_must_exist_when_set(tmp_path):
    missing = find_config_problems(make_settings(FIREBASE_SERVICE_ACCOUNT_PATH=SECRET_PATH), {})
    assert len(missing) == 1 and missing[0].startswith("FIREBASE_SERVICE_ACCOUNT_PATH")
    # A directory is not a file either.
    as_dir = find_config_problems(make_settings(FIREBASE_SERVICE_ACCOUNT_PATH=str(tmp_path)), {})
    assert len(as_dir) == 1


@pytest.mark.parametrize("origins", ["*", "http://localhost:5173,*", " * ", "*,http://a.example"])
def test_wildcard_origin_is_a_problem(origins):
    problems = find_config_problems(make_settings(FRONTEND_ORIGINS=origins), {})
    assert len(problems) == 1 and problems[0].startswith("FRONTEND_ORIGINS")


def test_all_problems_are_reported_together_without_values():
    settings = make_settings(
        FIREBASE_PROJECT_ID="",
        FIREBASE_SERVICE_ACCOUNT_PATH=SECRET_PATH,
        FRONTEND_ORIGINS=f"{SECRET_ORIGIN},*",
    )
    with pytest.raises(ConfigurationError) as exc:
        validate_runtime_config(settings, {EMULATOR_ENV: "secret-emulator-host:9099"})
    text = str(exc.value)
    assert len(exc.value.problems) == 4
    for name in ("FIREBASE_PROJECT_ID", EMULATOR_ENV, "FIREBASE_SERVICE_ACCOUNT_PATH", "FRONTEND_ORIGINS"):
        assert name in text
    for value in (SECRET_PATH, "secret-location", SECRET_ORIGIN, "secret-emulator-host", DB_URL, "user:pw"):
        assert value not in text


# ----- placement: startup event, not import -----


@pytest.fixture
def no_database(monkeypatch):
    """Startup also checks the DB; the unit tests must never connect to it."""
    calls: list[str] = []

    async def fake_init():
        calls.append("init_db")

    async def fake_close():
        calls.append("close_db")

    monkeypatch.setattr(main_module, "init_db", fake_init)
    monkeypatch.setattr(main_module, "close_db", fake_close)
    return calls


def test_startup_stops_on_bad_firebase_config_before_touching_the_db(monkeypatch, no_database):
    monkeypatch.setattr(main_module.settings, "FIREBASE_PROJECT_ID", "")
    with pytest.raises(ConfigurationError, match="FIREBASE_PROJECT_ID"):
        with TestClient(main_module.app):
            pass
    assert no_database == []  # validation runs first; the DB was not even checked


def test_startup_stops_on_wildcard_origin(monkeypatch, no_database):
    monkeypatch.setattr(main_module.settings, "FRONTEND_ORIGINS", "*")
    with pytest.raises(ConfigurationError, match="FRONTEND_ORIGINS"):
        with TestClient(main_module.app):
            pass


def test_startup_succeeds_with_valid_config(no_database):
    with TestClient(main_module.app) as client:
        assert client.get("/api/health").status_code == 200
    assert no_database == ["init_db", "close_db"]


def test_startup_failure_is_logged_without_values(monkeypatch, no_database, caplog):
    monkeypatch.setattr(main_module.settings, "FIREBASE_PROJECT_ID", "")
    monkeypatch.setattr(main_module.settings, "FIREBASE_SERVICE_ACCOUNT_PATH", SECRET_PATH)
    with pytest.raises(ConfigurationError):
        with TestClient(main_module.app):
            pass
    assert "FIREBASE_PROJECT_ID" in caplog.text
    assert SECRET_PATH not in caplog.text and "secret-location" not in caplog.text


def _run(code: str, **env_overrides) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(BE_DIR), **env_overrides}
    return subprocess.run(
        [sys.executable, "-W", "ignore", "-c", code],
        cwd=BE_DIR, env=env, capture_output=True, text=True, timeout=120,
    )


def test_importing_the_app_does_not_run_the_checks():
    """Bad Firebase/CORS config must not break `import app.main` (alembic, tooling)."""
    result = _run(
        "import app.main; print('imported')",
        FIREBASE_PROJECT_ID="",
        FRONTEND_ORIGINS="*",
        FIREBASE_SERVICE_ACCOUNT_PATH=SECRET_PATH,
    )
    assert result.returncode == 0, result.stderr[-500:]
    assert "imported" in result.stdout


def test_alembic_metadata_imports_without_firebase_settings():
    result = _run(
        "from app.core.config import settings; from app.models.registry import target_metadata; "
        "print(len(target_metadata.tables) > 0)",
        FIREBASE_PROJECT_ID="",
    )
    assert result.returncode == 0, result.stderr[-500:]
    assert result.stdout.strip() == "True"
