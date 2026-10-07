"""In-memory fakes for the auth/permission repositories. No DB, no Firebase."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from types import SimpleNamespace

from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.firebase import InvalidIdToken, ProviderUnavailable, VerifiedIdentity
from app.core.tokens import hash_session_token
from app.models.family.entities import (
    BusinessRegistration,
    Clan,
    ClanMembership,
    ClanOwnershipHistory,
    FamilyAdminAssignment,
    PlanFeatureLimit,
    RegistrationStatusHistory,
    SubscriptionPlan,
)
from app.models.user_access.entities import CredentialMetadata, LoginHistory, User, UserSession

NOW = datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)


def make_user(
    status: str = "ACTIVE",
    *,
    first_login_required: bool = False,
    firebase_uid: str | None = None,
) -> User:
    return User(
        user_id=uuid.uuid4(),
        firebase_uid=firebase_uid or f"fake-uid-{uuid.uuid4().hex[:12]}",
        email=f"{uuid.uuid4().hex[:8]}@example.test",
        display_name="Test User",
        status=status,
        first_login_required=first_login_required,
        email_verified=False,
        phone_verified=False,
        created_at=NOW - timedelta(days=1),
        updated_at=NOW - timedelta(days=1),
    )


@dataclass
class FakeIdentityProvider:
    """Stands in for Firebase. Tokens are opaque strings mapped to identities.

    Never stores passwords: set_password records only the UID.
    """

    identities: dict[str, VerifiedIdentity] = field(default_factory=dict)
    unavailable: bool = False
    set_password_error: Exception | None = None
    password_changes: list[str] = field(default_factory=list)

    def issue(
        self,
        uid: str,
        *,
        auth_time: datetime | None = None,
        email: str | None = "someone@example.test",
    ) -> str:
        token = f"fake-id-token-{uuid.uuid4().hex}"
        self.identities[token] = VerifiedIdentity(
            uid=uid,
            email=email,
            email_verified=False,
            auth_time=auth_time or datetime.now(timezone.utc) - timedelta(seconds=30),
            sign_in_provider="password",
        )
        return token

    async def verify_id_token(self, id_token: str) -> VerifiedIdentity:
        if self.unavailable:
            raise ProviderUnavailable("fake_unavailable")
        identity = self.identities.get(id_token)
        if identity is None:
            raise InvalidIdToken("invalid")
        return identity

    async def set_password(self, uid: str, new_password: str) -> None:
        if self.set_password_error is not None:
            raise self.set_password_error
        self.password_changes.append(uid)


class _DbError(Exception):
    """Stands in for psycopg's error object: IntegrityError.orig.diag.constraint_name."""

    def __init__(self, constraint_name: str) -> None:
        super().__init__("simulated")
        self.diag = SimpleNamespace(constraint_name=constraint_name)


@dataclass
class FakeDb:
    """Unit of work. commit() snapshots what the repo holds, to prove commit order."""

    repo: "FakeUserAccessRepo | None" = None
    fail_commit: bool = False
    commits: int = 0
    rollbacks: int = 0
    committed_login_history: list[LoginHistory] = field(default_factory=list)

    async def commit(self) -> None:
        if self.fail_commit:
            raise OperationalError("COMMIT", {}, Exception("simulated"))
        self.commits += 1
        if self.repo is not None:
            self.committed_login_history = list(self.repo.login_history)

    async def rollback(self) -> None:
        self.rollbacks += 1


@dataclass
class RoleGrant:
    user_id: uuid.UUID
    role_code: str
    clan_id: uuid.UUID | None
    revoked: bool = False


@dataclass
class FakeUserAccessRepo:
    users: dict[uuid.UUID, User] = field(default_factory=dict)
    sessions: dict[str, UserSession] = field(default_factory=dict)  # by token hash
    creds: dict[uuid.UUID, CredentialMetadata] = field(default_factory=dict)
    roles: list[RoleGrant] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    seen_hashes: list[str] = field(default_factory=list)
    login_history: list[LoginHistory] = field(default_factory=list)
    audit: list[dict] = field(default_factory=list)

    # --- setup helpers ---
    def add_user(self, user: User) -> User:
        self.users[user.user_id] = user
        return user

    def seed_session(
        self,
        user: User,
        token: str = "tok-valid",
        *,
        created_at: datetime = NOW - timedelta(hours=1),
        expires_at: datetime = NOW + timedelta(hours=7),
        revoked_at: datetime | None = None,
    ) -> str:
        self.sessions[hash_session_token(token)] = UserSession(
            session_id=uuid.uuid4(),
            user_id=user.user_id,
            token_jti_hash=hash_session_token(token),
            created_at=created_at,
            expires_at=expires_at,
            revoked_at=revoked_at,
        )
        return token

    def set_cred(self, user: User, **kwargs) -> None:
        values = {"must_change_password": False, "failed_login_count": 0, **kwargs}
        self.creds[user.user_id] = CredentialMetadata(user_id=user.user_id, **values)

    def grant(self, user: User, role_code: str, clan_id: uuid.UUID | None = None, *, revoked=False):
        self.roles.append(RoleGrant(user.user_id, role_code, clan_id, revoked))

    # --- AuthRepository ---
    async def get_session_by_token_hash(self, token_jti_hash: str):
        self.seen_hashes.append(token_jti_hash)
        return self.sessions.get(token_jti_hash)

    async def get_user_by_id(self, user_id):
        self.calls.append("get_user_by_id")
        return self.users.get(user_id)

    async def get_credential_metadata(self, user_id):
        return self.creds.get(user_id)

    # --- RoleRepository / SystemAdminGuardRepository ---
    async def has_active_role(self, user_id, role_code, *, clan_id):
        return any(
            g.user_id == user_id and g.role_code == role_code and g.clan_id == clan_id
            and not g.revoked
            for g in self.roles
        )

    async def lock_active_system_admin_roles(self) -> None:
        self.calls.append("lock")

    async def count_active_system_admins(self, *, exclude_user_id=None) -> int:
        self.calls.append("count")
        ids = {
            g.user_id
            for g in self.roles
            if g.role_code == "SYSTEM_ADMIN" and g.clan_id is None and not g.revoked
            and self.users.get(g.user_id) is not None
            and self.users[g.user_id].status == "ACTIVE"
        }
        ids.discard(exclude_user_id)
        return len(ids)

    async def list_active_role_grants(self, user_id):
        return [(g.role_code, g.clan_id) for g in self.roles if g.user_id == user_id and not g.revoked]

    # --- Mốc D: login / session writes ---
    async def get_user_by_firebase_uid(self, firebase_uid):
        return next((u for u in self.users.values() if u.firebase_uid == firebase_uid), None)

    async def add_session(self, **values) -> UserSession:
        row = UserSession(session_id=uuid.uuid4(), **values)
        self.sessions[values["token_jti_hash"]] = row
        return row

    def _revoke(self, rows, reason, now) -> int:
        count = 0
        for s in rows:
            if s.revoked_at is None:
                s.revoked_at, s.revoke_reason = now, reason
                count += 1
        return count

    async def revoke_session(self, session_id, *, reason, now) -> int:
        return self._revoke([s for s in self.sessions.values() if s.session_id == session_id], reason, now)

    async def revoke_all_sessions(self, user_id, *, reason, now) -> int:
        return self._revoke([s for s in self.sessions.values() if s.user_id == user_id], reason, now)

    async def add_login_history(self, **values) -> LoginHistory:
        row = LoginHistory(login_id=uuid.uuid4(), **values)
        self.login_history.append(row)
        return row

    async def add_credential_metadata(self, user_id, *, now) -> CredentialMetadata:
        self.set_cred(self.users[user_id])
        return self.creds[user_id]

    async def add_audit_log(self, **values) -> None:
        self.audit.append(values)

    # --- Mốc F ---
    known_permissions: set[str] = field(
        default_factory=lambda: {
            "MEMBER_ACCOUNT_MANAGE", "ADMIN_MANAGE", "PERSON_VIEW", "TREE_VIEW", "AUDIT_VIEW",
        }
    )

    async def get_user_for_update(self, user_id):
        self.calls.append("lock_user")
        return self.users.get(user_id)

    def _filtered(self, status, q):
        needle = (q or "").lower()
        rows = [
            u for u in self.users.values()
            if (status is None or u.status == status)
            and (not needle or needle in u.email.lower() or needle in u.display_name.lower())
        ]
        return sorted(rows, key=lambda u: str(u.user_id))

    async def list_users(self, *, status, q, limit, offset):
        return self._filtered(status, q)[offset : offset + limit]

    async def count_users(self, *, status, q):
        return len(self._filtered(status, q))

    async def list_clan_role_codes(self, clan_id, user_ids):
        out: dict = {}
        for g in self.roles:
            if g.clan_id == clan_id and not g.revoked and g.user_id in user_ids:
                out.setdefault(g.user_id, set()).add(g.role_code)
        return {uid: sorted(codes) for uid, codes in out.items()}

    async def existing_permission_codes(self, codes):
        return set(codes) & self.known_permissions

    # --- Mốc F2: clan role rows ---
    role_codes_present: set[str] = field(
        default_factory=lambda: {"SYSTEM_ADMIN", "BUSINESS_OWNER", "FAMILY_ADMIN", "FAMILY_MEMBER"}
    )

    async def get_role_by_code(self, code):
        if code not in self.role_codes_present:
            return None

        class _Role:
            pass

        role = _Role()
        role.role_id = uuid.uuid5(uuid.NAMESPACE_DNS, code)
        role.code = code
        return role

    async def add_clan_role(self, *, user_id, role_id, clan_id, granted_by, now):
        self.calls.append("add_clan_role")
        code = next(c for c in self.role_codes_present if uuid.uuid5(uuid.NAMESPACE_DNS, c) == role_id)
        # uq_active_user_role_scope: a second ACTIVE grant of (user, role, clan) is rejected.
        if any(
            g.user_id == user_id and g.role_code == code and g.clan_id == clan_id and not g.revoked
            for g in self.roles
        ):
            from sqlalchemy.exc import IntegrityError

            raise IntegrityError("INSERT user_roles", {}, Exception("uq_active_user_role_scope"))
        self.roles.append(RoleGrant(user_id, code, clan_id))

    async def revoke_clan_role(self, *, user_id, clan_id, role_code, now):
        self.calls.append("revoke_clan_role")
        count = 0
        for g in self.roles:
            if g.user_id == user_id and g.clan_id == clan_id and g.role_code == role_code and not g.revoked:
                g.revoked = True
                count += 1
        return count


@dataclass
class FakeAssignment:
    """One family_admin_assignments row with its family_admin_permissions codes."""

    clan_id: uuid.UUID
    user_id: uuid.UUID
    branch_id: uuid.UUID | None
    codes: set[str] = field(default_factory=set)
    revoked: bool = False
    assignment_id: uuid.UUID = field(default_factory=uuid.uuid4)

    def as_entity(self) -> FamilyAdminAssignment:
        return FamilyAdminAssignment(
            assignment_id=self.assignment_id, user_id=self.user_id, clan_id=self.clan_id,
            branch_id=self.branch_id, revoked_at=NOW if self.revoked else None,
        )


@dataclass
class FakeFamilyRepo:
    clans: dict[uuid.UUID, Clan] = field(default_factory=dict)
    memberships: list[ClanMembership] = field(default_factory=list)
    owners: list[ClanOwnershipHistory] = field(default_factory=list)
    assignments: list[FakeAssignment] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)

    users: dict[uuid.UUID, User] = field(default_factory=dict)  # for list_clan_members

    # --- Mốc E, step E3: public catalog and Guest registration ---
    plans: dict[uuid.UUID, SubscriptionPlan] = field(default_factory=dict)
    plan_features: list[PlanFeatureLimit] = field(default_factory=list)
    registrations: list[BusinessRegistration] = field(default_factory=list)
    registration_history: list[RegistrationStatusHistory] = field(default_factory=list)
    # Constraint names to raise (as IntegrityError) from the next create_registration calls.
    create_registration_errors: list[str] = field(default_factory=list)
    # True: exists_pending_registration says "no", so only the unique index can stop a duplicate.
    precheck_blind: bool = False

    def add_plan(
        self, code: str, *, price="0.00", status="ACTIVE", features=(), months=12, **extra
    ) -> SubscriptionPlan:
        from decimal import Decimal

        plan = SubscriptionPlan(
            plan_id=uuid.uuid4(), code=code, name=f"Plan {code}", description=None,
            price=Decimal(price), billing_period_months=months, status=status,
            created_at=NOW, updated_at=NOW, **extra,
        )
        self.plans[plan.plan_id] = plan
        for feature_code, enabled, limit in features:
            self.plan_features.append(PlanFeatureLimit(
                plan_feature_id=uuid.uuid4(), plan_id=plan.plan_id, feature_code=feature_code,
                enabled=enabled, limit_value=None if limit is None else Decimal(str(limit)),
                feature_metadata={},
            ))
        return plan

    async def get_plan_by_id(self, plan_id):
        self.calls.append("get_plan_by_id")
        return self.plans.get(plan_id)

    async def list_active_plans_page(self, *, limit, offset):
        self.calls.append("list_active_plans_page")
        rows = sorted(
            (p for p in self.plans.values() if p.status == "ACTIVE"), key=lambda p: (p.price, p.code)
        )
        return rows[offset : offset + limit]

    async def count_active_plans(self):
        self.calls.append("count_active_plans")
        return sum(1 for p in self.plans.values() if p.status == "ACTIVE")

    async def list_feature_limits_for_plans(self, plan_ids):
        self.calls.append("list_feature_limits_for_plans")
        wanted = set(plan_ids)
        return sorted(
            (f for f in self.plan_features if f.plan_id in wanted),
            key=lambda f: (str(f.plan_id), f.feature_code),
        )

    async def exists_pending_registration(self, *, email, clan_name):
        self.calls.append("exists_pending_registration")
        if self.precheck_blind:
            return False
        return self._pending_same(email, clan_name)

    def _pending_same(self, email, clan_name) -> bool:
        return any(
            r.status == "PENDING"
            and r.representative_email.lower() == email.lower()
            and r.clan_name.lower() == clan_name.lower()
            for r in self.registrations
        )

    async def create_registration(self, **v):
        self.calls.append("create_registration")
        if self.create_registration_errors:
            name = self.create_registration_errors.pop(0)
            raise IntegrityError("INSERT business_registrations", {}, _DbError(name))
        # What the database would enforce, so the index path is reachable without a database.
        if self._pending_same(v["representative_email"], v["clan_name"]):
            raise IntegrityError(
                "INSERT business_registrations", {}, _DbError("uq_registration_pending_same_applicant")
            )
        if any(r.tracking_code_hash == v["tracking_code_hash"] for r in self.registrations):
            raise IntegrityError(
                "INSERT business_registrations", {},
                _DbError("business_registrations_tracking_code_hash_key"),
            )
        row = BusinessRegistration(
            registration_id=v["registration_id"], requested_plan_id=v["requested_plan_id"],
            representative_name=v["representative_name"], representative_email=v["representative_email"],
            representative_phone=v["representative_phone"], clan_name=v["clan_name"],
            origin_place=v["origin_place"], status="PENDING",
            tracking_code_hash=v["tracking_code_hash"], created_at=v["now"], updated_at=v["now"],
        )
        self.registrations.append(row)
        return row

    async def add_registration_status_history(self, **v):
        self.calls.append("add_registration_status_history")
        row = RegistrationStatusHistory(
            history_id=uuid.uuid4(), registration_id=v["registration_id"], from_status=v["from_status"],
            to_status=v["to_status"], changed_by=v["changed_by"], reason=v["reason"], changed_at=v["now"],
        )
        self.registration_history.append(row)
        return row

    async def get_registration_by_tracking_hash(self, tracking_code_hash):
        self.calls.append("get_registration_by_tracking_hash")
        return next((r for r in self.registrations if r.tracking_code_hash == tracking_code_hash), None)

    def add_clan(self, status: str = "ACTIVE") -> Clan:
        clan = Clan(clan_id=uuid.uuid4(), clan_code=uuid.uuid4().hex[:8], name="Clan", status=status)
        self.clans[clan.clan_id] = clan
        return clan

    def add_member(self, clan: Clan, user: User, status: str = "ACTIVE", revoked_at=None):
        self.memberships.append(
            ClanMembership(
                membership_id=uuid.uuid4(), clan_id=clan.clan_id, user_id=user.user_id,
                status=status, revoked_at=revoked_at,
            )
        )

    def add_owner(self, clan: Clan, user: User, *, ended_at=None):
        self.owners.append(
            ClanOwnershipHistory(
                ownership_id=uuid.uuid4(), clan_id=clan.clan_id, user_id=user.user_id,
                started_at=NOW - timedelta(days=1), ended_at=ended_at,
            )
        )

    def add_fa(self, clan: Clan, user: User, code: str, branch_id=None, revoked=False):
        return self.add_fa_assignment(clan, user, [code], branch_id=branch_id, revoked=revoked)

    def add_fa_assignment(
        self, clan: Clan, user: User, codes: list[str], branch_id=None, revoked=False
    ) -> FakeAssignment:
        row = FakeAssignment(clan.clan_id, user.user_id, branch_id, set(codes), revoked)
        self.assignments.append(row)
        return row

    async def get_clan_by_id(self, clan_id):
        return self.clans.get(clan_id)

    async def get_membership(self, clan_id, user_id):
        return next(
            (m for m in self.memberships if m.clan_id == clan_id and m.user_id == user_id), None
        )

    async def get_active_owner(self, clan_id):
        return next(
            (o for o in self.owners if o.clan_id == clan_id and o.ended_at is None), None
        )

    async def list_active_fa_grants(self, clan_id, user_id):
        return [
            (a.assignment_id, a.branch_id, code)
            for a in self.assignments
            if a.clan_id == clan_id and a.user_id == user_id and not a.revoked
            for code in sorted(a.codes)
        ]

    async def list_fa_permission_codes(self, clan_id, user_id):
        return sorted({code for _a, _b, code in await self.list_active_fa_grants(clan_id, user_id)})

    # --- Mốc F ---
    async def list_clan_members(self, clan_id, *, membership_status, limit, offset):
        self.calls.append(f"list_clan_members:{clan_id}")
        rows = [
            (m, self.users[m.user_id])
            for m in self.memberships
            if m.clan_id == clan_id and (membership_status is None or m.status == membership_status)
        ]
        rows.sort(key=lambda r: (r[1].display_name, str(r[1].user_id)))
        return rows[offset : offset + limit]

    async def count_clan_members(self, clan_id, *, membership_status):
        return sum(
            1 for m in self.memberships
            if m.clan_id == clan_id and (membership_status is None or m.status == membership_status)
        )

    async def list_active_fa_user_ids(self, clan_id, user_ids):
        return {
            a.user_id for a in self.assignments
            if a.clan_id == clan_id and not a.revoked and a.user_id in user_ids
        }

    async def lock_active_fa_assignments(self, clan_id, user_id):
        self.calls.append("lock_fa")
        return [
            a.as_entity() for a in self.assignments
            if a.clan_id == clan_id and a.user_id == user_id and not a.revoked
        ]

    def _assignment(self, assignment_id) -> FakeAssignment:
        return next(a for a in self.assignments if a.assignment_id == assignment_id)

    async def list_assignment_permission_codes(self, assignment_id):
        return set(self._assignment(assignment_id).codes)

    async def add_fa_permissions(self, assignment_id, codes, *, granted_by, now):
        self.calls.append("add_fa_permissions")
        self._assignment(assignment_id).codes.update(codes)

    async def delete_fa_permissions(self, assignment_id, codes):
        self.calls.append("delete_fa_permissions")
        self._assignment(assignment_id).codes.difference_update(codes)

    # --- Mốc F2: Family Admin lifecycle ---
    async def lock_membership(self, clan_id, user_id):
        self.calls.append("lock_membership")
        return await self.get_membership(clan_id, user_id)

    async def create_fa_assignment(self, clan_id, user_id, *, assigned_by, now):
        self.calls.append("create_fa_assignment")
        row = FakeAssignment(clan_id, user_id, None, set(), False)
        self.assignments.append(row)
        return row.as_entity()

    async def revoke_fa_assignments(self, clan_id, user_id, *, now):
        self.calls.append("revoke_fa_assignments")
        ids = []
        for a in self.assignments:
            if a.clan_id == clan_id and a.user_id == user_id and not a.revoked:
                a.revoked = True
                ids.append(a.assignment_id)
        return sorted(ids)

    async def delete_all_fa_permissions(self, clan_id, assignment_ids):
        self.calls.append("delete_all_fa_permissions")
        count = 0
        for a in self.assignments:
            if a.clan_id == clan_id and a.assignment_id in assignment_ids:
                count += len(a.codes)
                a.codes.clear()
        return count

    async def list_memberships_with_clans(self, user_id):
        return [
            (m, self.clans[m.clan_id])
            for m in self.memberships
            if m.user_id == user_id and m.revoked_at is None and m.status != "REVOKED"
        ]
