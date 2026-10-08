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
    BusinessRegistration,
    Clan,
    ClanMembership,
    ClanOwnershipHistory,
    FamilyAdminAssignment,
    FamilyAdminPermission,
    IdempotencyKey,
    ProvisioningJob,
    SubscriptionPlan,
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

    async def plan(self, status: str = "ACTIVE") -> SubscriptionPlan:
        """A plan of our own (inside the rolled-back transaction); real plans are never touched."""
        plan = SubscriptionPlan(
            plan_id=uuid.uuid4(),
            code=f"ITEST-{uuid.uuid4().hex[:12].upper()}",
            name="Integration Test Plan",
            price=0,
            billing_period_months=12,
            status=status,
        )
        self.s.add(plan)
        await self.s.flush()
        return plan

    async def registration(
        self,
        plan: SubscriptionPlan,
        *,
        email: str | None = None,
        clan_name: str | None = None,
        status: str = "PENDING",
        name: str = "Integration Test Applicant",
        phone: str | None = None,
        origin_place: str | None = None,
        created_at: datetime | None = None,
    ) -> BusinessRegistration:
        tag = uuid.uuid4().hex[:12]
        row = BusinessRegistration(
            registration_id=uuid.uuid4(),
            requested_plan_id=plan.plan_id,
            representative_name=name,
            representative_email=email or f"itest-reg-{tag}{EMAIL_DOMAIN}",
            representative_phone=phone,
            clan_name=clan_name or f"Itest Clan {tag}",
            origin_place=origin_place,
            status=status,
            tracking_code_hash=hash_session_token(uuid.uuid4().hex),  # stands in for sha256(tracking code)
        )
        if created_at is not None:
            row.created_at = created_at
            row.updated_at = created_at
        self.s.add(row)
        await self.s.flush()
        return row

    async def job(
        self,
        clan: Clan,
        *,
        status: str = "PENDING",
        email: str | None = None,
        needs_cleanup: bool = False,
        firebase_user_created: bool | None = None,
        lease_expires_in: timedelta | None = None,
        requested_by: User | None = None,
    ) -> ProvisioningJob:
        """A provisioning job with the uid the CHECK demands ('own-' + job_id)."""
        job_id = uuid.uuid4()
        if status == "RUNNING" and lease_expires_in is None:
            lease_expires_in = timedelta(minutes=1)
        row = ProvisioningJob(
            job_id=job_id,
            clan_id=clan.clan_id,
            status=status,
            requested_by=requested_by.user_id if requested_by else None,
            email=email or f"itest-job-{uuid.uuid4().hex[:12]}{EMAIL_DOMAIN}",
            display_name="Integration Test Owner",
            firebase_uid=f"own-{job_id}",
            firebase_user_created=needs_cleanup if firebase_user_created is None else firebase_user_created,
            needs_cleanup=needs_cleanup,
            lease_expires_at=now() + lease_expires_in if lease_expires_in else None,
        )
        self.s.add(row)
        await self.s.flush()
        return row

    async def idempotency(
        self,
        actor: User,
        *,
        endpoint: str = "business.create",
        key: str | None = None,
        status: str = "IN_PROGRESS",
        response_status: int | None = None,
    ) -> IdempotencyKey:
        row = IdempotencyKey(
            idempotency_id=uuid.uuid4(),
            actor_id=actor.user_id,
            endpoint=endpoint,
            idempotency_key=uuid.uuid4().hex if key is None else key,
            request_hash="a" * 64,
            status=status,
            response_status=response_status,
            expires_at=now() + timedelta(days=7),
        )
        self.s.add(row)
        await self.s.flush()
        return row

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


def build_full_app(session, *, rate_limiters=None) -> FastAPI:
    """The REAL routers (auth, user administration, public registration, registration administration)
    on a real DB session.

    Use this when the route itself is under test; build_app() above is the older stub
    app kept for the C3 authorization tests. The rate limiters are OFF by default so a test
    that registers several times is not throttled; pass `rate_limiters` to test the limit.
    """
    from app.controllers.auth_access.router import router as auth_router
    from app.controllers.auth_access.user_admin_router import router as user_admin_router
    from app.controllers.family_management.public_router import router as public_router
    from app.controllers.family_management.owner_admin_router import router as owner_admin_router
    from app.controllers.family_management.registration_admin_router import (
        router as registration_admin_router,
    )
    from app.core.rate_limit import RateLimiters, SlidingWindowLimiter

    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(user_admin_router, prefix="/api/v1")
    app.include_router(public_router, prefix="/api/v1")
    app.include_router(registration_admin_router, prefix="/api/v1")
    app.include_router(owner_admin_router, prefix="/api/v1")
    app.state.rate_limiters = rate_limiters or RateLimiters(
        enabled=False,
        registration=SlidingWindowLimiter(5, 3600),
        track=SlidingWindowLimiter(20, 600),
    )

    async def db_override():
        yield session

    app.dependency_overrides[get_db] = db_override
    return app
