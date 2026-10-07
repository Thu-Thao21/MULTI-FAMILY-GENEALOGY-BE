"""Opaque application session tokens (plan section 5).

The bearer token is random; only its SHA-256 hex digest is stored in
user_sessions.token_jti_hash. The raw token is returned to the client once.
"""

from __future__ import annotations

import hashlib
import secrets

SESSION_TOKEN_BYTES = 32  # 256 bits of entropy


def generate_session_token() -> str:
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ----- Business registration tracking code (Mốc E, step E3) -----
# 32 random bytes = 256 bits of entropy (43 URL-safe characters). Only the SHA-256 hex digest is
# stored (business_registrations.tracking_code_hash); the code itself is shown once, in the 201
# response, and is never logged or audited.
TRACKING_CODE_BYTES = 32


def generate_tracking_code() -> str:
    return secrets.token_urlsafe(TRACKING_CODE_BYTES)


def hash_tracking_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()
