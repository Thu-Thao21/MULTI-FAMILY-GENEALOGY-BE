from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_access.entities import (
    AuditLog,
    CredentialMetadata,
    LoginHistory,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    UserSession,
)


class UserAccessRepository:
    """Query-only repository. Use cases own transactions; do not commit here."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_user_by_id(self, user_id: uuid.UUID) -> User | None:
        stmt = select(User).where(User.user_id == user_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_user_by_firebase_uid(self, firebase_uid: str) -> User | None:
        stmt = select(User).where(User.firebase_uid == firebase_uid)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_user_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_credential_metadata(self, user_id: uuid.UUID) -> CredentialMetadata | None:
        stmt = select(CredentialMetadata).where(CredentialMetadata.user_id == user_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_session_by_id(self, session_id: uuid.UUID) -> UserSession | None:
        stmt = select(UserSession).where(UserSession.session_id == session_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_session_by_token_hash(self, token_jti_hash: str) -> UserSession | None:
        stmt = select(UserSession).where(UserSession.token_jti_hash == token_jti_hash)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_active_session_by_token_hash(self, token_jti_hash: str) -> UserSession | None:
        now = datetime.now(timezone.utc)
        stmt = select(UserSession).where(
            UserSession.token_jti_hash == token_jti_hash,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_sessions_by_user_id(self, user_id: uuid.UUID) -> list[UserSession]:
        stmt = select(UserSession).where(UserSession.user_id == user_id)
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_login_history_by_user_id(
        self,
        user_id: uuid.UUID,
        *,
        limit: int = 100,
    ) -> list[LoginHistory]:
        stmt = (
            select(LoginHistory)
            .where(LoginHistory.user_id == user_id)
            .order_by(LoginHistory.occurred_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_role_by_code(self, code: str) -> Role | None:
        stmt = select(Role).where(Role.code == code)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_role_by_id(self, role_id: uuid.UUID) -> Role | None:
        stmt = select(Role).where(Role.role_id == role_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_permission_by_code(self, code: str) -> Permission | None:
        stmt = select(Permission).where(Permission.code == code)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_permission_codes_for_role(self, role_id: uuid.UUID) -> list[str]:
        stmt = (
            select(Permission.code)
            .join(
                RolePermission,
                RolePermission.permission_id == Permission.permission_id,
            )
            .where(RolePermission.role_id == role_id)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_active_user_roles(
        self,
        user_id: uuid.UUID,
        *,
        clan_id: uuid.UUID | None = None,
    ) -> list[UserRole]:
        stmt: Select[tuple[UserRole]] = select(UserRole).where(
            UserRole.user_id == user_id,
            UserRole.revoked_at.is_(None),
        )
        if clan_id is not None:
            stmt = stmt.where(UserRole.clan_id == clan_id)
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_audit_logs_for_clan(
        self,
        clan_id: uuid.UUID,
        *,
        limit: int = 100,
    ) -> list[AuditLog]:
        stmt = (
            select(AuditLog)
            .where(AuditLog.clan_id == clan_id)
            .order_by(AuditLog.occurred_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())
