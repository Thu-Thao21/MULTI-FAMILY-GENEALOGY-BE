"""The database engine options (E4b), checked WITHOUT a database.

Neon closes idle connections, so a pooled connection can be dead when it is next used. The engine
therefore pings on checkout (pool_pre_ping), never reuses a very old connection (pool_recycle) and
gives up on a connect that hangs (connect_timeout). The application and the integration tests build
their engines through the same helper, make_engine, so they cannot drift apart.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy.pool import NullPool

import app.db.postgres as postgres
from app.db.postgres import ENGINE_OPTIONS, make_engine

ROOT = Path(__file__).resolve().parents[1]


def test_the_options_are_exactly_the_approved_ones():
    assert ENGINE_OPTIONS == {
        "pool_pre_ping": True,
        "pool_recycle": 1800,
        "connect_args": {"connect_timeout": 15},
    }


def test_the_application_engine_really_has_them():
    pool = postgres.engine.pool
    assert pool._pre_ping is True
    assert pool._recycle == 1800
    assert pool.size() == 5  # the other pool parameters keep SQLAlchemy's defaults
    assert pool._max_overflow == 10
    assert pool._timeout == 30


@pytest.fixture
def captured(monkeypatch):
    calls: list[tuple[tuple, dict]] = []

    def fake_create(*args, **kwargs):
        calls.append((args, kwargs))
        return object()

    monkeypatch.setattr(postgres, "create_async_engine", fake_create)
    return calls


def test_make_engine_passes_the_options_and_the_url(captured):
    make_engine("postgresql+psycopg://u:p@h/db")
    [(args, kwargs)] = captured
    assert args == ("postgresql+psycopg://u:p@h/db",)
    assert kwargs == ENGINE_OPTIONS


def test_make_engine_defaults_to_the_configured_url(captured):
    make_engine()
    assert captured[0][0] == (postgres.settings.DATABASE_URL,)


def test_overrides_add_or_replace_options_but_never_drop_the_rest(captured):
    make_engine("postgresql+psycopg://u:p@h/db", pool_size=2, max_overflow=0, pool_recycle=60)
    make_engine("postgresql+psycopg://u:p@h/db", poolclass=NullPool)
    (_, first), (_, second) = captured
    assert first["pool_size"] == 2 and first["max_overflow"] == 0 and first["pool_recycle"] == 60
    assert first["pool_pre_ping"] is True and first["connect_args"] == {"connect_timeout": 15}
    assert second["poolclass"] is NullPool
    assert second["pool_pre_ping"] is True and second["connect_args"] == {"connect_timeout": 15}


def test_the_shared_options_are_not_mutated_by_a_call(captured):
    before = {key: (dict(value) if isinstance(value, dict) else value) for key, value in ENGINE_OPTIONS.items()}
    make_engine("postgresql+psycopg://u:p@h/db", pool_size=2)
    assert ENGINE_OPTIONS == before


def test_a_real_engine_built_with_overrides_keeps_pre_ping_and_recycle():
    engine = make_engine("postgresql+psycopg://u:p@localhost/none", pool_size=2, max_overflow=0)
    assert engine.pool._pre_ping is True and engine.pool._recycle == 1800
    assert engine.pool.size() == 2 and engine.pool._max_overflow == 0


# ------------------------------------------------------------------ nobody builds an engine on the side


def sources(*folders: str):
    for folder in folders:
        for path in (ROOT / folder).rglob("*.py"):
            if "__pycache__" not in path.parts:
                yield path


def test_only_make_engine_calls_create_async_engine_in_the_app_and_the_integration_tests():
    offenders = [
        str(path.relative_to(ROOT))
        for path in sources("app", "tests/integration")
        if re.search(r"\bcreate_async_engine\(", path.read_text(encoding="utf-8"))
        and path != ROOT / "app" / "db" / "postgres.py"
    ]
    assert offenders == []


def test_the_integration_fixtures_use_the_shared_helper():
    conftest = (ROOT / "tests" / "integration" / "conftest.py").read_text(encoding="utf-8")
    assert "make_engine(settings.DATABASE_URL, pool_size=2, max_overflow=0)" in conftest
    for name in ("test_registration_concurrency", "test_registration_review_concurrency",
                 "test_family_admin_concurrency", "test_last_sa_concurrency"):
        source = (ROOT / "tests" / "integration" / f"{name}.py").read_text(encoding="utf-8")
        assert "make_engine(settings.DATABASE_URL, poolclass=NullPool)" in source, name
