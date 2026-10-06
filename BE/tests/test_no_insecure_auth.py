"""Guards for KI-01 / KI-02: no unsigned JWT decoding, no local password store."""

from __future__ import annotations

import importlib
import pkgutil
import re
from pathlib import Path

import pytest

import app

BE_DIR = Path(__file__).resolve().parents[1]
APP_DIR = BE_DIR / "app"

FORBIDDEN = {
    "verify_signature": re.compile(r"verify_signature"),
    "PyJWT import": re.compile(r"^\s*(import jwt|from jwt\b)", re.M),
    "bcrypt": re.compile(r"\bbcrypt\b"),
    "passlib": re.compile(r"\bpasslib\b"),
    "password hashing helpers": re.compile(r"\b(hash_password|verify_password)\b"),
}


def test_local_password_module_is_gone():
    assert not (APP_DIR / "core" / "security.py").exists()
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.core.security")


@pytest.mark.parametrize("name", sorted(FORBIDDEN))
def test_app_code_has_no_insecure_auth_pattern(name):
    pattern = FORBIDDEN[name]
    hits = [
        str(p.relative_to(BE_DIR))
        for p in APP_DIR.rglob("*.py")
        if pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert hits == []


def test_requirements_drop_local_password_libs():
    text = (BE_DIR / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "passlib" not in text and "bcrypt" not in text


def test_every_app_module_imports():
    """Removing passlib/jwt must not break any import."""
    failures = []
    for module in pkgutil.walk_packages(app.__path__, prefix="app."):
        try:
            importlib.import_module(module.name)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{module.name}: {type(exc).__name__}")
    assert failures == []
