"""Firebase Authentication adapter (Mốc D). Fail closed.

- ID tokens are verified only by the Admin SDK: RS256 signature against Google's
  public certificates, issuer, audience (= FIREBASE_PROJECT_ID), expiry, subject.
  That needs only the project ID. There is NO decode-without-signature path, and a
  configuration problem never downgrades verification: it raises ProviderUnavailable.
- FIREBASE_SERVICE_ACCOUNT_PATH is used only for the Admin API (set_password and the
  revocation check). App code never reads, prints or logs the file or its path; the SDK
  loads it. If the path is set but unusable, everything fails closed.
- FIREBASE_AUTH_EMULATOR_HOST makes the SDK accept unsigned tokens, so its presence
  is treated as a misconfiguration (fail closed), not as a dev convenience.
- Exceptions carry a short reason code only, never the token or SDK messages.
- EVERY firebase_admin call runs through `_call`: asyncio.to_thread, bounded by
  FIREBASE_CALL_TIMEOUT_SECONDS (a timeout is ProviderUnavailable("timeout")). The caller must not
  hold a database transaction or connection open across a call.
- Owner provisioning (Mốc E6) adds create_user / get_user / delete_user, ALL by uid. The adapter has
  no lookup or delete by e-mail, and delete_user refuses any uid that is not `own-<uuid>`: a
  clean-up can only ever remove the user a job itself created.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials
from firebase_admin import exceptions as firebase_exceptions
from google.auth.credentials import AnonymousCredentials

from app.core.config import settings

logger = logging.getLogger("mfg.firebase")

_APP_NAME = "mfg-auth"
CLOCK_SKEW_SECONDS = 10
EMULATOR_ENV = "FIREBASE_AUTH_EMULATOR_HOST"


@dataclass(frozen=True)
class VerifiedIdentity:
    """Claims of a verified Firebase ID token that the app relies on."""

    uid: str
    email: str | None
    email_verified: bool
    auth_time: datetime  # when the user actually signed in (UTC)
    sign_in_provider: str | None


class InvalidIdToken(Exception):
    """Token rejected: bad signature/issuer/audience, expired, revoked or malformed."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ProviderUnavailable(Exception):
    """Firebase is not configured or not reachable. Never fall back to a weaker check."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class PasswordRejected(Exception):
    """Firebase refused the new password (password policy)."""


class ProviderUserExists(Exception):
    """create_user: the uid is already taken (an earlier attempt of the same job created it)."""


class ProviderEmailTaken(Exception):
    """create_user: the e-mail belongs to ANOTHER Firebase account. That account is never touched."""


class ProviderInvalidUser(Exception):
    """Firebase refused the user data itself (not the password). Retrying cannot help."""


class UnsafeUid(Exception):
    """A uid that is not `own-<uuid>` was given to a call that only accepts those."""


@dataclass(frozen=True)
class ProviderUser:
    """What the app reads back about a Firebase user. Never a password or a token."""

    uid: str
    email: str | None
    display_name: str | None
    disabled: bool


def own_uid(job_id: uuid.UUID) -> str:
    """The Firebase uid of the user a provisioning job creates (also its provisioning_jobs row CHECK)."""
    return f"own-{job_id}"


def require_own_uid(uid: str) -> str:
    """`own-<canonical uuid>` or UnsafeUid. Checked BEFORE any SDK call that creates or deletes."""
    if isinstance(uid, str) and uid.startswith("own-"):
        try:
            if str(uuid.UUID(uid[4:])) == uid[4:]:
                return uid
        except ValueError:
            pass
    raise UnsafeUid()


class IdentityProvider(Protocol):
    admin_api_enabled: bool

    async def verify_id_token(self, id_token: str) -> VerifiedIdentity: ...

    async def set_password(self, uid: str, new_password: str) -> None: ...

    async def get_user(self, uid: str) -> ProviderUser | None: ...

    async def create_user(self, *, uid: str, email: str, display_name: str, password: str) -> ProviderUser: ...

    async def delete_user(self, uid: str) -> bool: ...


def identity_from_claims(claims: dict[str, Any]) -> VerifiedIdentity:
    uid = claims.get("uid") or claims.get("sub")
    auth_time = claims.get("auth_time")
    if not isinstance(uid, str) or not uid or not isinstance(auth_time, (int, float)):
        raise InvalidIdToken("missing_claims")
    firebase_claims = claims.get("firebase") or {}
    return VerifiedIdentity(
        uid=uid,
        email=claims.get("email"),
        email_verified=bool(claims.get("email_verified", False)),
        auth_time=datetime.fromtimestamp(auth_time, tz=timezone.utc),
        sign_in_provider=firebase_claims.get("sign_in_provider"),
    )


class _VerifyOnlyCredential(credentials.Base):
    """Credential with no secret, used when no service account is configured.

    ID-token verification only needs Google's public certificates. Without this the
    SDK would fall back to Application Default Credentials (whatever the machine has).
    Admin API calls are refused before reaching the SDK (set_password checks first).
    """

    def get_credential(self):
        return AnonymousCredentials()


class FirebaseIdentityProvider:
    def __init__(
        self, project_id: str, service_account_path: str = "", call_timeout_seconds: float | None = None
    ) -> None:
        self._project_id = (project_id or "").strip()
        self._service_account_path = (service_account_path or "").strip()
        self._call_timeout = float(
            call_timeout_seconds if call_timeout_seconds is not None else settings.FIREBASE_CALL_TIMEOUT_SECONDS
        )
        self._app: firebase_admin.App | None = None
        self._lock = threading.Lock()

    @property
    def admin_api_enabled(self) -> bool:
        return bool(self._service_account_path)

    async def _call(self, function, *args, **kwargs):
        """Run one blocking SDK call in a worker thread, bounded by the per-call timeout.

        A thread cannot be cancelled: after a timeout the call may still finish on Firebase's side
        (a user may exist that we never heard about). The provisioning job handles that by asking
        get_user(uid) before it creates anything.
        """
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(function, *args, **kwargs), timeout=self._call_timeout
            )
        except asyncio.TimeoutError:
            raise ProviderUnavailable("timeout") from None

    def _get_app(self) -> firebase_admin.App:
        if not self._project_id:
            raise ProviderUnavailable("project_id_not_configured")
        if os.environ.get(EMULATOR_ENV):
            # In emulator mode the Admin SDK accepts UNSIGNED ID tokens. Refuse it.
            raise ProviderUnavailable("emulator_mode_refused")
        if self._app is not None:
            return self._app
        with self._lock:
            if self._app is None:
                credential: credentials.Base = _VerifyOnlyCredential()
                if self._service_account_path:
                    if not os.path.isfile(self._service_account_path):
                        raise ProviderUnavailable("service_account_not_found")
                    try:
                        credential = credentials.Certificate(self._service_account_path)
                    except Exception:  # noqa: BLE001 - never surface file details
                        raise ProviderUnavailable("service_account_invalid") from None
                # One named SDK app per (project, mode) so two configurations never share
                # an app (and its credential) by accident.
                mode = "verify" if isinstance(credential, _VerifyOnlyCredential) else "admin"
                name = f"{_APP_NAME}:{self._project_id}:{mode}"
                try:
                    self._app = firebase_admin.get_app(name)
                except ValueError:
                    self._app = firebase_admin.initialize_app(
                        credential,
                        # httpTimeout: the SDK's own HTTP timeout, so a worker thread ends close to
                        # the moment _call gives up on it.
                        options={"projectId": self._project_id, "httpTimeout": self._call_timeout},
                        name=name,
                    )
        return self._app

    async def verify_id_token(self, id_token: str) -> VerifiedIdentity:
        app = self._get_app()
        try:
            claims = await self._call(
                firebase_auth.verify_id_token,
                id_token,
                app=app,
                # Revocation lookup is an Admin API call: only with a service account.
                check_revoked=self.admin_api_enabled,
                clock_skew_seconds=CLOCK_SKEW_SECONDS,
            )
        except firebase_auth.CertificateFetchError:
            raise ProviderUnavailable("certificate_fetch_failed") from None
        except firebase_auth.ExpiredIdTokenError:
            raise InvalidIdToken("expired") from None
        except firebase_auth.RevokedIdTokenError:
            raise InvalidIdToken("revoked") from None
        except firebase_auth.UserDisabledError:
            raise InvalidIdToken("user_disabled") from None
        except (firebase_auth.InvalidIdTokenError, ValueError):
            raise InvalidIdToken("invalid") from None
        except firebase_exceptions.FirebaseError:
            raise ProviderUnavailable("firebase_error") from None
        return identity_from_claims(claims)

    async def set_password(self, uid: str, new_password: str) -> None:
        """Set the password and revoke the user's Firebase refresh tokens."""
        if not self.admin_api_enabled:
            raise ProviderUnavailable("admin_api_not_configured")
        app = self._get_app()
        try:
            await self._call(firebase_auth.update_user, uid, password=new_password, app=app)
        except (ValueError, firebase_exceptions.InvalidArgumentError):
            raise PasswordRejected() from None
        except firebase_exceptions.FirebaseError:
            raise ProviderUnavailable("update_user_failed") from None
        try:
            await self._call(firebase_auth.revoke_refresh_tokens, uid, app=app)
        except (ValueError, firebase_exceptions.FirebaseError):
            raise ProviderUnavailable("revoke_refresh_tokens_failed") from None

    # ----- Owner provisioning (Mốc E6): by uid only -----

    def _require_admin(self) -> firebase_admin.App:
        if not self.admin_api_enabled:
            raise ProviderUnavailable("admin_api_not_configured")
        return self._get_app()

    async def get_user(self, uid: str) -> ProviderUser | None:
        """The user with this uid, or None when there is none."""
        app = self._require_admin()
        try:
            record = await self._call(firebase_auth.get_user, uid, app=app)
        except firebase_auth.UserNotFoundError:
            return None
        except ValueError:
            raise ProviderInvalidUser() from None
        except firebase_exceptions.FirebaseError:
            raise ProviderUnavailable("get_user_failed") from None
        return _provider_user(record)

    async def create_user(
        self, *, uid: str, email: str, display_name: str, password: str
    ) -> ProviderUser:
        """Create the user `uid` (an `own-<uuid>`). The e-mail is NOT verified. No phone is sent."""
        require_own_uid(uid)
        app = self._require_admin()
        try:
            record = await self._call(
                firebase_auth.create_user,
                uid=uid,
                email=email,
                display_name=display_name,
                password=password,
                email_verified=False,
                disabled=False,
                app=app,
            )
        except firebase_auth.UidAlreadyExistsError:
            raise ProviderUserExists() from None
        except firebase_auth.EmailAlreadyExistsError:
            raise ProviderEmailTaken() from None
        except (ValueError, firebase_exceptions.InvalidArgumentError) as exc:
            raise _classify_invalid(exc) from None
        except firebase_exceptions.FirebaseError:
            raise ProviderUnavailable("create_user_failed") from None
        return _provider_user(record)

    async def delete_user(self, uid: str) -> bool:
        """Delete the user `uid`, only if it is an `own-<uuid>`. True if deleted, False if there was none."""
        require_own_uid(uid)
        app = self._require_admin()
        try:
            await self._call(firebase_auth.delete_user, uid, app=app)
        except firebase_auth.UserNotFoundError:
            return False
        except ValueError:
            raise ProviderInvalidUser() from None
        except firebase_exceptions.FirebaseError:
            raise ProviderUnavailable("delete_user_failed") from None
        return True


def _provider_user(record) -> ProviderUser:
    return ProviderUser(
        uid=record.uid,
        email=getattr(record, "email", None),
        display_name=getattr(record, "display_name", None),
        disabled=bool(getattr(record, "disabled", False)),
    )


def _classify_invalid(exc: BaseException) -> Exception:
    """Password policy or the user data? The SDK's own messages name the password; the text is
    only inspected, never kept or logged (it could echo what we sent)."""
    return PasswordRejected() if "password" in str(exc).lower() else ProviderInvalidUser()


_provider: FirebaseIdentityProvider | None = None


def get_identity_provider() -> IdentityProvider:
    """FastAPI dependency. Tests override it with a fake; nothing here calls Firebase."""
    global _provider
    if _provider is None:
        _provider = FirebaseIdentityProvider(
            settings.FIREBASE_PROJECT_ID, settings.FIREBASE_SERVICE_ACCOUNT_PATH
        )
    return _provider
