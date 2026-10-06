"""Test-wide environment. Loaded before any test module imports app code.

Firebase and CORS settings are forced here so no test depends on BE/.env and no test can
reach the real Firebase project or service account. DATABASE_URL still comes from
.env (unit tests never connect; integration tests need the real branch).
"""

import os

os.environ["FIREBASE_PROJECT_ID"] = "test-project"
os.environ["FRONTEND_ORIGINS"] = "http://localhost:5173,http://localhost:8080"
os.environ["FIREBASE_SERVICE_ACCOUNT_PATH"] = ""
os.environ.pop("FIREBASE_AUTH_EMULATOR_HOST", None)
os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
