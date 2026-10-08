from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Select, func, or_, select, update
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


SYSTEM_ADMIN_ROLE = "SYSTEM_ADMIN"


def active_system_admin_roles_for_update_stmt() -> Select[tuple[uuid.UUID]]:
    """Row-lock every active system-scope SYSTEM_ADMIN grant (FOR UPDATE OF user_roles).

    Serializes concurrent lock/disable/revoke operations on System Admins so the
    "last active SA" check cannot be raced. Must run inside the caller's transaction.

    LOCK ORDER (everything that locks rows for a status change follows it):
      1. this statement: ORDER BY user_id, user_role_id, the same fixed order for every
         caller, so two callers can never hold the set in opposite orders;
      2. only then the target user row (get_user_for_update, FOR NO KEY UPDATE).
    A request that waits here holds no other lock yet, so it cannot be part of a cycle.
    """
    return (
        select(UserRole.user_role_id)
        .join(Role, Role.role_id == UserRole.role_id)
        .where(
            Role.code == SYSTEM_ADMIN_ROLE,
            UserRole.clan_id.is_(None),
            UserRole.revoked_at.is_(None),
        )
        .order_by(UserRole.user_id, UserRole.user_role_id)
        .with_for_update(of=UserRole)
    )


class UserAccessRepository:
    """Queries plus plain inserts/updates. Use cases own transactions; never commit here."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_user_by_id(self, user_id: uuid.UUID) -> User | None:
        stmt = select(User).where(User.user_id == user_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_user_for_update(self, user_id: uuid.UUID) -> User | None:
        """Lock the user row with FOR NO KEY UPDATE and return fresh column values.

        NO KEY UPDATE (not FOR UPDATE): the audit_logs / login_history / user_roles
        foreign keys to users take FOR KEY SHARE on this row, which FOR UPDATE would
        block. Two requests that each lock a user and then insert an audit row naming
        the other as actor would deadlock. NO KEY UPDATE still serializes concurrent
        changes of the same user. Take the SA lock first when it is needed.
        """
        stmt = (
            select(User)
            .where(User.user_id == user_id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_user_by_firebase_uid(self, firebase_uid: str) -> User | None:
        stmt = select(User).where(User.firebase_uid == firebase_uid)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_user_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_user_by_email_ci(self, email: str) -> User | None:
        """The user with this e-mail in ANY letter case (uq_users_email_lower is the matching index)."""
        stmt = select(User).where(func.lower(User.email) == email.lower())
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create_user_account(
        self,
        *,
        user_id: uuid.UUID,
        firebase_uid: str,
        email: str,
        display_name: str,
        phone: str | None,
        status: str,
        first_login_required: bool,
        now: datetime,
    ) -> User:
        """A new account. The e-mail is stored as given (never lower-cased). Flush only."""
        user = User(
            user_id=user_id,
            firebase_uid=firebase_uid,
            email=email,
            phone=phone,
            display_name=display_name,
            status=status,
            email_verified=False,
            phone_verified=False,
            first_login_required=first_login_required,
            created_at=now,
            updated_at=now,
        )
        self._session.add(user)
        await self._session.flush()
        return user

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

    # ----- Authorization helpers (C2) -----

    async def has_active_role(
        self,
        user_id: uuid.UUID,
        role_code: str,
        *,
        clan_id: uuid.UUID | None,
    ) -> bool:
        """Active (revoked_at IS NULL) grant of role_code. clan_id=None means system scope."""
        stmt = (
            select(UserRole.user_role_id)
            .join(Role, Role.role_id == UserRole.role_id)
            .where(
                UserRole.user_id == user_id,
                Role.code == role_code,
                UserRole.revoked_at.is_(None),
                UserRole.clan_id.is_(None) if clan_id is None else UserRole.clan_id == clan_id,
            )
            .limit(1)
        )
        return (await self._session.execute(stmt)).first() is not None

    async def list_active_role_grants(
        self, user_id: uuid.UUID
    ) -> list[tuple[str, uuid.UUID | None]]:
        """(role_code, clan_id) for every active grant of the user."""
        stmt = (
            select(Role.code, UserRole.clan_id)
            .join(Role, Role.role_id == UserRole.role_id)
            .where(UserRole.user_id == user_id, UserRole.revoked_at.is_(None))
        )
        return [(row[0], row[1]) for row in (await self._session.execute(stmt)).all()]

    async def lock_active_system_admin_roles(self) -> None:
        """SELECT ... FOR UPDATE on active SA grants. Caller owns the transaction."""
        await self._session.execute(active_system_admin_roles_for_update_stmt())

    async def count_active_system_admins(
        self, *, exclude_user_id: uuid.UUID | None = None
    ) -> int:
        """Distinct ACTIVE users holding an active system-scope SYSTEM_ADMIN grant.

        Run after lock_active_system_admin_roles() as a separate statement so that,
        under READ COMMITTED, it sees changes committed by the transaction it waited on.
        """
        stmt = (
            select(func.count(func.distinct(UserRole.user_id)))
            .join(Role, Role.role_id == UserRole.role_id)
            .join(User, User.user_id == UserRole.user_id)
            .where(
                Role.code == SYSTEM_ADMIN_ROLE,
                UserRole.clan_id.is_(None),
                UserRole.revoked_at.is_(None),
                User.status == "ACTIVE",
            )
        )
        if exclude_user_id is not None:
            stmt = stmt.where(UserRole.user_id != exclude_user_id)
        return int((await self._session.execute(stmt)).scalar_one())

    # ----- Writes for sessions and login (Mốc D). Flush only; the caller commits. -----

    async def add_session(
        self,
        *,
        user_id: uuid.UUID,
        token_jti_hash: str,
        created_at: datetime,
        expires_at: datetime,
        ip_address: str | None,
        user_agent: str | None,
    ) -> UserSession:
        row = UserSession(
            session_id=uuid.uuid4(),
            user_id=user_id,
            token_jti_hash=token_jti_hash,
            created_at=created_at,
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def revoke_session(self, session_id: uuid.UUID, *, reason: str, now: datetime) -> int:
        stmt = (
            update(UserSession)
            .where(UserSession.session_id == session_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=now, revoke_reason=reason)
        )
        return (await self._session.execute(stmt)).rowcount or 0

    async def revoke_all_sessions(self, user_id: uuid.UUID, *, reason: str, now: datetime) -> int:
        stmt = (
            update(UserSession)
            .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=now, revoke_reason=reason)
        )
        return (await self._session.execute(stmt)).rowcount or 0

    async def add_login_history(
        self,
        *,
        user_id: uuid.UUID | None,
        identifier: str | None,
        success: bool,
        failure_reason: str | None,
        ip_address: str | None,
        user_agent: str | None,
        occurred_at: datetime,
    ) -> LoginHistory:
        row = LoginHistory(
            login_id=uuid.uuid4(),
            user_id=user_id,
            identifier=identifier,
            success=success,
            failure_reason=failure_reason,
            ip_address=ip_address,
            user_agent=user_agent,
            occurred_at=occurred_at,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def add_credential_metadata(self, user_id: uuid.UUID, *, now: datetime) -> CredentialMetadata:
        row = CredentialMetadata(
            user_id=user_id,
            auth_provider="FIREBASE",
            must_change_password=False,
            failed_login_count=0,
            updated_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def add_audit_log(
        self,
        *,
        actor_id: uuid.UUID | None,
        action: str,
        entity_type: str,
        entity_id: uuid.UUID | None,
        old_data: dict | None,
        new_data: dict | None,
        ip_address: str | None,
        occurred_at: datetime,
        clan_id: uuid.UUID | None = None,
        reason: str | None = None,
    ) -> AuditLog:
        row = AuditLog(
            log_id=uuid.uuid4(),
            clan_id=clan_id,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            old_data=old_data,
            new_data=new_data,
            reason=reason,
            ip_address=ip_address,
            occurred_at=occurred_at,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    # ----- Clan role rows (Mốc F2). Flush/execute only; the caller commits. -----

    async def add_clan_role(
        self,
        *,
        user_id: uuid.UUID,
        role_id: uuid.UUID,
        clan_id: uuid.UUID,
        granted_by: uuid.UUID,
        now: datetime,
    ) -> UserRole:
        """Grant a role INSIDE a clan. uq_active_user_role_scope rejects a second active
        grant of the same (user, role, clan); revoked rows do not count."""
        row = UserRole(
            user_role_id=uuid.uuid4(),
            user_id=user_id,
            role_id=role_id,
            clan_id=clan_id,
            granted_by=granted_by,
            granted_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def revoke_clan_role(
        self, *, user_id: uuid.UUID, clan_id: uuid.UUID, role_code: str, now: datetime
    ) -> int:
        """Set revoked_at on the user's active grants of role_code in this clan."""
        role_id = select(Role.role_id).where(Role.code == role_code).scalar_subquery()
        result = await self._session.execute(
            update(UserRole)
            .where(
                UserRole.user_id == user_id,
                UserRole.clan_id == clan_id,
                UserRole.role_id == role_id,
                UserRole.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        return result.rowcount or 0

    # ----- User administration (Mốc F) -----

    @staticmethod
    def _user_filters(status: str | None, q: str | None) -> list:
        conditions = []
        if status is not None:
            conditions.append(User.status == status)
        if q:
            # Case-insensitive search; LIKE wildcards in the input are escaped. Stored
            # e-mails are never changed or lowercased.
            escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            conditions.append(
                or_(
                    User.email.ilike(pattern, escape="\\"),
                    User.display_name.ilike(pattern, escape="\\"),
                )
            )
        return conditions

    async def list_users(
        self, *, status: str | None, q: str | None, limit: int, offset: int
    ) -> list[User]:
        stmt = (
            select(User)
            .where(*self._user_filters(status, q))
            .order_by(User.created_at.desc(), User.user_id)
            .limit(limit)
            .offset(offset)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def count_users(self, *, status: str | None, q: str | None) -> int:
        stmt = select(func.count()).select_from(User).where(*self._user_filters(status, q))
        return int((await self._session.execute(stmt)).scalar_one())

    async def list_clan_role_codes(
        self, clan_id: uuid.UUID, user_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[str]]:
        """Active role codes held IN THIS CLAN for each given user (one query)."""
        if not user_ids:
            return {}
        stmt = (
            select(UserRole.user_id, Role.code)
            .join(Role, Role.role_id == UserRole.role_id)
            .where(
                UserRole.clan_id == clan_id,
                UserRole.revoked_at.is_(None),
                UserRole.user_id.in_(user_ids),
            )
        )
        out: dict[uuid.UUID, set[str]] = {}
        for user_id, code in (await self._session.execute(stmt)).all():
            out.setdefault(user_id, set()).add(code)
        return {uid: sorted(codes) for uid, codes in out.items()}

    async def existing_permission_codes(self, codes: list[str]) -> set[str]:
        """Which of these codes exist in the permissions table (SELECT only)."""
        if not codes:
            return set()
        stmt = select(Permission.code).where(Permission.code.in_(codes))
        return set((await self._session.execute(stmt)).scalars().all())
