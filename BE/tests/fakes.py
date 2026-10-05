"""In-memory fakes for the auth/permission repositories. No DB, no Firebase."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.core.tokens import hash_session_token
from app.models.family.entities import Clan, ClanMembership, ClanOwnershipHistory
from app.models.user_access.entities import CredentialMetadata, User, UserSession

NOW = datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)


def make_user(status: str = "ACTIVE", *, first_login_required: bool = False) -> User:
    return User(
        user_id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex[:8]}@example.test",
        display_name="Test User",
        status=status,
        first_login_required=first_login_required,
    )


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

    # --- setup helpers ---
    def add_user(self, user: User) -> User:
        self.users[user.user_id] = user
        return user

    def add_session(
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


@dataclass
class FaGrant:
    clan_id: uuid.UUID
    user_id: uuid.UUID
    branch_id: uuid.UUID | None
    permission_code: str
    revoked: bool = False
    assignment_id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass
class FakeFamilyRepo:
    clans: dict[uuid.UUID, Clan] = field(default_factory=dict)
    memberships: list[ClanMembership] = field(default_factory=list)
    owners: list[ClanOwnershipHistory] = field(default_factory=list)
    fa: list[FaGrant] = field(default_factory=list)

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
        self.fa.append(FaGrant(clan.clan_id, user.user_id, branch_id, code, revoked))

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
            (g.assignment_id, g.branch_id, g.permission_code)
            for g in self.fa
            if g.clan_id == clan_id and g.user_id == user_id and not g.revoked
        ]
