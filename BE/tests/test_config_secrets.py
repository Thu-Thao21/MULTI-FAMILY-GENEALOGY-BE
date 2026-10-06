"""A malformed DATABASE_URL must not be echoed anywhere (Mốc G).

pydantic's ValidationError prints `input_value='<the value>'`, and the value is a
connection string with the password. Settings uses hide_input_in_errors=True. These
tests run the real import in a subprocess with a FAKE password and inspect everything it
prints (stdout, stderr and DEBUG logging).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

BE_DIR = Path(__file__).resolve().parents[1]
FAKE_PASSWORD = "FAKE-PASSWORD-9f3a7c1e"
FAKE_USER = "fakeuser9f3a"
FAKE_HOST = "db-9f3a.example.invalid"
FAKE_DB = "fakedb9f3a"

BAD_URLS = {
    "wrong-scheme": f"mysql://{FAKE_USER}:{FAKE_PASSWORD}@{FAKE_HOST}:3306/{FAKE_DB}",
    "sqlite": f"sqlite:///C:/{FAKE_USER}/{FAKE_PASSWORD}/{FAKE_DB}.db",
    "sqlite-async": f"sqlite+aiosqlite://{FAKE_USER}:{FAKE_PASSWORD}@{FAKE_HOST}/{FAKE_DB}",
    "no-colon-after-scheme": f"postgresql+psycopg//{FAKE_USER}:{FAKE_PASSWORD}@{FAKE_HOST}/{FAKE_DB}",
    "unknown-driver": f"postgresql+asyncpg://{FAKE_USER}:{FAKE_PASSWORD}@{FAKE_HOST}/{FAKE_DB}",
}
LEAKS = [FAKE_PASSWORD, "9f3a7c1e", FAKE_USER, FAKE_HOST, FAKE_DB, "mysql://", "sqlite:", "asyncpg://"]

PROGRAM = (
    "import logging; logging.basicConfig(level=logging.DEBUG); "
    "import app.core.config"
)


def run_import(tmp_path, database_url: str | None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    env["PYTHONPATH"] = str(BE_DIR)
    if database_url is not None:
        env["DATABASE_URL"] = database_url
    # cwd is an empty temp dir, so no BE/.env is read: the only source is the variable.
    return subprocess.run(
        [sys.executable, "-W", "ignore", "-c", PROGRAM],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120,
    )


@pytest.mark.parametrize("name", sorted(BAD_URLS))
def test_bad_database_url_is_rejected_without_echoing_any_part_of_it(tmp_path, name):
    result = run_import(tmp_path, BAD_URLS[name])
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "ValidationError" in output and "DATABASE_URL" in output  # still a clear error
    for leak in LEAKS:
        assert leak not in output, f"{leak!r} leaked in the error output"
    assert "input_value" not in output


def test_the_error_message_tells_how_to_fix_it(tmp_path):
    output = run_import(tmp_path, BAD_URLS["wrong-scheme"])
    text = output.stdout + output.stderr
    assert "postgresql+psycopg://" in text  # the template, not the user's value


def test_blank_database_url_is_rejected_clearly(tmp_path):
    result = run_import(tmp_path, "   ")
    output = result.stdout + result.stderr
    assert result.returncode != 0 and "DATABASE_URL is required" in output


def test_missing_database_url_is_rejected_clearly(tmp_path):
    result = run_import(tmp_path, None)
    output = result.stdout + result.stderr
    assert result.returncode != 0 and "DATABASE_URL" in output and "Field required" in output


@pytest.mark.parametrize(
    "url",
    [
        f"postgresql://{FAKE_USER}:{FAKE_PASSWORD}@{FAKE_HOST}/{FAKE_DB}",
        f"postgres://{FAKE_USER}:{FAKE_PASSWORD}@{FAKE_HOST}/{FAKE_DB}",
        f"postgresql+psycopg://{FAKE_USER}:{FAKE_PASSWORD}@{FAKE_HOST}/{FAKE_DB}?sslmode=require",
    ],
)
def test_valid_urls_import_silently(tmp_path, url):
    """Accepted forms (normalized to postgresql+psycopg://) must not print the URL either."""
    result = run_import(tmp_path, url)
    assert result.returncode == 0, result.stderr[-500:]
    for leak in (FAKE_PASSWORD, FAKE_HOST, FAKE_USER):
        assert leak not in result.stdout + result.stderr


def test_in_process_validation_error_has_no_input(monkeypatch):
    """Same guarantee at the pydantic level, independent of how the import is run."""
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None, DATABASE_URL=BAD_URLS["wrong-scheme"])
    text = str(exc.value) + repr(exc.value)
    for leak in LEAKS:
        assert leak not in text
    assert all("input" not in err or err.get("input") is None for err in exc.value.errors(include_input=False))
