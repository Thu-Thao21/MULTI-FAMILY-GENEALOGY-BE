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
