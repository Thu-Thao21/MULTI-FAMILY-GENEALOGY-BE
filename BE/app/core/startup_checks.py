"""Runtime configuration checks (fail closed). Run from the app startup event ONLY.

Not run at import time on purpose: importing app.main, running alembic or starting a
TestClient without a startup context must keep working without Firebase settings.

Messages name the variable and the problem, never the value (a value can be a secret
or a file path).
"""

from __future__ import annotations

import os
from typing import Mapping

from app.core.config import Settings
from app.core.firebase import EMULATOR_ENV


class ConfigurationError(RuntimeError):
    """Startup must stop. str(exc) lists variable names and problems only."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("Invalid configuration: " + "; ".join(problems))


def find_config_problems(
    settings: Settings, environ: Mapping[str, str] | None = None
) -> list[str]:
    environ = os.environ if environ is None else environ
    problems: list[str] = []

    if not (settings.FIREBASE_PROJECT_ID or "").strip():
        problems.append(
            "FIREBASE_PROJECT_ID is not set (ID tokens cannot be verified, so login would fail)"
        )

    if environ.get(EMULATOR_ENV):
        problems.append(
            f"{EMULATOR_ENV} is set (the Firebase emulator mode accepts unsigned ID tokens; "
            "unset it)"
        )

    path = (settings.FIREBASE_SERVICE_ACCOUNT_PATH or "").strip()
    if path and not os.path.isfile(path):
        # Only existence is checked; the file is never opened by this code.
        problems.append(
            "FIREBASE_SERVICE_ACCOUNT_PATH is set but does not point to an existing file"
        )

    if "*" in settings.cors_origins:
        problems.append(
            "FRONTEND_ORIGINS contains '*' (a wildcard origin with credentials is not allowed; "
            "list the exact origins)"
        )

    return problems


def validate_runtime_config(
    settings: Settings, environ: Mapping[str, str] | None = None
) -> None:
    problems = find_config_problems(settings, environ)
    if problems:
        raise ConfigurationError(problems)
