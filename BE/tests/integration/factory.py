"""Row factory and a minimal FastAPI app wired to the real dependencies.

Factory methods only INSERT (and flush) through the ORM. Roles are SELECTed by code,
never written. Everything is created inside the test's rolled-back transaction.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import Depends, FastAPI, Response
from sqlalchemy import select, text, update

from app.core.errors import register_exception_handlers
from app.core.request_id import RequestIdMiddleware
from app.core.tokens import generate_session_token, hash_session_token
from app.db.postgres import get_db
from app.dependencies.auth import Principal, get_principal_allow_restricted
from app.dependencies.permissions import Action, clan_scope_from_path, require_action
from app.models.family.entities import (
    Clan,
    ClanMembership,
    ClanOwnershipHistory,
    FamilyAdminAssignment,
    FamilyAdminPermission,
)
from app.models.user_access.entities import (
    CredentialMetadata,
    Role,
    User,
    UserRole,
    UserSession,
)

EMAIL_DOMAIN = "@example.test"


def now() -> datetime:
    return datetime.now(timezone.utc)


class World:
    def __init__(self, session) -> None:
        self.s = session
        self._roles: dict[str, Role] = {}

    async def role(self, code: str) -> Role:
        if code not in self._roles:
            row = (await self.s.execute(select(Role).where(Role.code == code))).scalar_one_or_none()
            if row is None:
                pytest.fail(f"role {code} is missing in the DB (tests never create roles)")
            self._roles[code] = row
        return self._roles[code]

    async def user(
        self,
        status: str = "ACTIVE",
        *,
        first_login_required: bool = False,
        cred: dict | None = None,
        email: str | None = None,
        display_name: str = "Integration Test User",
    ) -> User:
        tag = uuid.uuid4().hex[:12]
        user = User(
            user_id=uuid.uuid4(),
            firebase_uid=f"itest-uid-{tag}",
            email=email or f"itest-{tag}{EMAIL_DOMAIN}",
            display_name=display_name,
            status=status,
            first_login_required=first_login_required,
        )
        self.s.add(user)
        await self.s.flush()
        if cred is not None:
            self.s.add(CredentialMetadata(user_id=user.user_id, **cred))
            await self.s.flush()
        return user

    async def session_for(
        self,
        user: User,
        *,
        token: str | None = None,
        created_ago: timedelta = timedelta(minutes=5),
        expires_in: timedelta = timedelta(hours=8),
        revoked: bool = False,
    ) -> str:
        """Insert a session whose only stored secret is SHA-256(token); return the raw token."""
        token = token or generate_session_token()
        t = now()
        self.s.add(
            UserSession(
                session_id=uuid.uuid4(),
                user_id=user.user_id,
                token_jti_hash=hash_session_token(token),
                created_at=t - created_ago,
                expires_at=t + expires_in,
                revoked_at=t - timedelta(minutes=1) if revoked else None,
            )
        )
        await self.s.flush()
        return token

    async def grant(
        self, user: User, role_code: str, clan: Clan | None = None, *, revoked: bool = False
    ) -> UserRole:
        row = UserRole(
            user_role_id=uuid.uuid4(),
            user_id=user.user_id,
            role_id=(await self.role(role_code)).role_id,
            clan_id=clan.clan_id if clan else None,
            revoked_at=now() if revoked else None,
        )
        self.s.add(row)
        await self.s.flush()
        return row

    async def clan(self, status: str = "ACTIVE") -> Clan:
        clan = Clan(
            clan_id=uuid.uuid4(),
            clan_code=f"ITEST-{uuid.uuid4().hex[:12].upper()}",
            name="Integration Test Clan",
            status=status,
        )
        self.s.add(clan)
        await self.s.flush()
        return clan

    async def member(
        self, clan: Clan, user: User, status: str = "ACTIVE", *, revoked_at=None
    ) -> ClanMembership:
        row = ClanMembership(
            membership_id=uuid.uuid4(),
            clan_id=clan.clan_id,
            user_id=user.user_id,
            status=status,
            joined_at=now(),
            revoked_at=revoked_at,
        )
        self.s.add(row)
        await self.s.flush()
        return row

    async def owner(self, clan: Clan, user: User, *, ended: bool = False) -> ClanOwnershipHistory:
        row = ClanOwnershipHistory(
            ownership_id=uuid.uuid4(),
            clan_id=clan.clan_id,
            user_id=user.user_id,
            started_at=now() - timedelta(days=1),
            ended_at=now() if ended else None,
        )
        self.s.add(row)
        await self.s.flush()
        return row

    async def fa(
        self,
        clan: Clan,
        user: User,
        *codes: str,
        branch_id: uuid.UUID | None = None,
        revoked: bool = False,
    ) -> FamilyAdminAssignment:
        assignment = FamilyAdminAssignment(
            assignment_id=uuid.uuid4(),
            user_id=user.user_id,
            clan_id=clan.clan_id,
            branch_id=branch_id,
            revoked_at=now() if revoked else None,
        )
        self.s.add(assignment)
        await self.s.flush()
        for code in codes:
            self.s.add(
                FamilyAdminPermission(assignment_id=assignment.assignment_id, permission_code=code)
            )
        await self.s.flush()
        return assignment

    async def branch(self, clan: Clan) -> uuid.UUID:
        """branches has no ORM model yet; raw INSERT inside the rolled-back transaction."""
        branch_id = uuid.uuid4()
        await self.s.execute(
            text("INSERT INTO branches (branch_id, clan_id, name) VALUES (:b, :c, 'itest branch')"),
            {"b": branch_id, "c": clan.clan_id},
        )
        return branch_id

    async def business_owner(self, clan_status: str = "ACTIVE") -> tuple[Clan, User]:
        """Clan + BO that satisfies all three BO conditions."""
        clan = await self.clan(clan_status)
        bo = await self.user()
        await self.grant(bo, "BUSINESS_OWNER", clan)
        await self.owner(clan, bo)
        await self.member(clan, bo)
        return clan, bo

    async def isolate_system_admins(self) -> None:
        """Make the txn see no ACTIVE SA except those created by this test.

        The guard counts every ACTIVE SA in the database, including real/dev ones. This
        UPDATE only lives in the test's transaction and is rolled back with it.
        """
        await self.s.execute(
            update(User)
            .where(
                User.firebase_uid.not_like("itest-%"),
                User.user_id.in_(
                    select(UserRole.user_id)
                    .join(Role, Role.role_id == UserRole.role_id)
                    .where(
                        Role.code == "SYSTEM_ADMIN",
                        UserRole.clan_id.is_(None),
                        UserRole.revoked_at.is_(None),
                    )
                ),
            )
            .values(status="SUSPENDED")
        )


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def build_app(session) -> FastAPI:
    """Real auth/permission dependencies on a real DB session; trivial handlers.

    The /auth/* handlers stand in for the real ones (Mốc D). The business routes only
    exist to exercise require_action wiring.
    """
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)

    async def db_override():
        yield session

    app.dependency_overrides[get_db] = db_override

    @app.get("/api/v1/auth/me")
    async def me(p: Principal = Depends(get_principal_allow_restricted)):
        return {"user_id": str(p.user_id), "restricted": p.requires_password_change}

    @app.post("/api/v1/auth/change-password", status_code=204)
    async def change_password(_p: Principal = Depends(get_principal_allow_restricted)):
        return Response(status_code=204)

    @app.post("/api/v1/auth/logout", status_code=204)
    async def logout(_p: Principal = Depends(get_principal_allow_restricted)):
        return Response(status_code=204)

    @app.get("/api/v1/admin/users", dependencies=[Depends(require_action(Action.USER_LIST))])
    async def admin_users():
        return {"ok": True}

    @app.get(
        "/api/v1/clans/{clan_id}/users",
        dependencies=[Depends(require_action(Action.CLAN_USERS_LIST, clan_scope_from_path()))],
    )
    async def clan_users(clan_id: str):
        return {"ok": True}

    @app.put(
        "/api/v1/clans/{clan_id}/admins/{user_id}/permissions",
        dependencies=[
            Depends(require_action(Action.CLAN_FA_PERMISSIONS_UPDATE, clan_scope_from_path()))
        ],
    )
    async def fa_permissions(clan_id: str, user_id: str):
        return {"ok": True}

    return app


def build_full_app(session) -> FastAPI:
    """The REAL routers (auth + user administration) on a real DB session.

    Use this when the route itself is under test; build_app() above is the older stub
    app kept for the C3 authorization tests.
    """
    from app.controllers.auth_access.router import router as auth_router
    from app.controllers.auth_access.user_admin_router import router as user_admin_router

    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(user_admin_router, prefix="/api/v1")

    async def db_override():
        yield session

    app.dependency_overrides[get_db] = db_override
    return app
