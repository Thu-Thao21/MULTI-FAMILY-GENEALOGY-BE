import logging
import os
from typing import Any, Dict

import firebase_admin
from firebase_admin import auth as firebase_auth, credentials
from app.core.config import settings

logger = logging.getLogger("mfg.firebase")

_firebase_app = None


def get_firebase_app():
    global _firebase_app
    if _firebase_app is None:
        if not firebase_admin._apps:
            cred_path = settings.FIREBASE_CREDENTIALS_PATH or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            if cred_path and os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
                _firebase_app = firebase_admin.initialize_app(cred)
                logger.info(f"Firebase Admin initialized with certificate: {cred_path}")
            else:
                _firebase_app = firebase_admin.initialize_app(
                    options={"projectId": settings.FIREBASE_PROJECT_ID}
                )
                logger.info(f"Firebase Admin initialized with project ID: {settings.FIREBASE_PROJECT_ID}")
        else:
            _firebase_app = firebase_admin.get_app()
    return _firebase_app


import time
import jwt

def verify_firebase_token(id_token: str) -> Dict[str, Any]:
    """
    Verifies a Firebase ID token sent from Frontend.
    Returns decoded token dict or raises Exception on invalid/expired token.
    Unsigned decoding is available only when explicitly enabled for local development.
    """
    try:
        get_firebase_app()
        return firebase_auth.verify_id_token(id_token, clock_skew_seconds=10)
    except Exception as verification_error:
        if not settings.ALLOW_INSECURE_FIREBASE_DEV:
            logger.warning("Firebase token verification failed")
            raise ValueError("Firebase token verification failed") from verification_error

    logger.warning("Using explicitly enabled insecure Firebase token decoding for local development")
    try:
        decoded = jwt.decode(id_token, options={"verify_signature": False})

        # Basic validation of claims
        now = time.time()
        if decoded.get("exp") and decoded["exp"] < now:
            raise ValueError("Token đã hết hạn.")

        uid = decoded.get("uid") or decoded.get("user_id") or decoded.get("sub")
        if not uid:
            raise ValueError("Token thiếu UID hợp lệ.")

        # Standardize claims to match firebase_admin output
        decoded["uid"] = uid
        decoded["email"] = decoded.get("email")
        decoded["name"] = decoded.get("name") or decoded.get("displayName")
        decoded["email_verified"] = decoded.get("email_verified", False)

        return decoded
    except Exception as jwt_err:
        logger.error("Insecure local Firebase token decoding failed")
        raise ValueError("Firebase token verification failed") from jwt_err
