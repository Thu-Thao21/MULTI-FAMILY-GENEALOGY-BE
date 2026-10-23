"""Mốc C3 - dev seed for the real PostgreSQL branch.

Usage (from BE/, Windows):
    $env:ALLOW_DEV_SEED = "1"
    .venv\\Scripts\\python.exe scripts\\seed_dev.py            # create / top up
    .venv\\Scripts\\python.exe scripts\\seed_dev.py --cleanup  # delete DEV-* data only
    .venv\\Scripts\\python.exe scripts\\seed_dev.py --plans-only  # only the DEV-* service plans
    .venv\\Scripts\\python.exe scripts\\seed_dev.py --plans-only --cleanup  # only unreferenced DEV-* plans

Rules:
  - Refuses to run unless ALLOW_DEV_SEED=1.
  - No DDL. Never writes roles, permissions or role_permissions (SELECT only; a
    missing role/permission aborts with a clear message).
  - Idempotent: every row is looked up by its natural key first.
  - Everything it writes is identifiable: clans DEV-*, users dev-*@example.test with
    firebase_uid dev-*. --cleanup deletes only clans DEV-* and users dev-*@example.test
    (example.test is a reserved domain, so no real account can match).
  - Optional DEV_SA_FIREBASE_UID: if set, dev-sa gets that firebase_uid so a real
    Firebase account can sign in as the dev System Admin (Mốc D). The value is never
    printed and must never be written into code, docs or tests. If unset, dev-sa keeps
    its current UID (the fake dev-sa for a new row).
  - No password hash, no session, no token. Prints counts and e-mails, never secrets
    or DATABASE_URL.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ENV_FLAG = "ALLOW_DEV_SEED"
CLAN_PREFIX = "DEV-"
EMAIL_PREFIX = "dev-"
EMAIL_SUFFIX = "@example.test"
UID_PREFIX = "dev-"
FA_PERMISSION = "MEMBER_ACCOUNT_MANAGE"
SA_UID_ENV = "DEV_SA_FIREBASE_UID"

# (key, status) of every dev user; e-mail = dev-<key>@example.test
USERS: list[tuple[str, str, str]] = [
    ("sa", "ACTIVE", "DEV System Admin"),
    ("bo-a", "ACTIVE", "DEV Business Owner A"),
    ("bo-b", "ACTIVE", "DEV Business Owner B"),
    ("fa-a", "ACTIVE", "DEV Family Admin A"),
    ("member-a", "ACTIVE", "DEV Member A"),
    ("member-b", "ACTIVE", "DEV Member B"),
    ("locked-a", "LOCKED", "DEV Locked User A"),
]

# clan key -> (clan_code, name, status, owner user key)
CLANS: dict[str, tuple[str, str, str, str]] = {
    "a": (f"{CLAN_PREFIX}CLAN-A", "DEV Clan A (ACTIVE)", "ACTIVE", "bo-a"),
    "b": (f"{CLAN_PREFIX}CLAN-B", "DEV Clan B (PENDING)", "PENDING", "bo-b"),
}

# (user key, clan key, role code). BO rows are added from CLANS; SA is system scope.
EXTRA_MEMBERS: list[tuple[str, str, str]] = [
    ("fa-a", "a", "FAMILY_ADMIN"),
    ("member-a", "a", "FAMILY_MEMBER"),
    ("locked-a", "a", "FAMILY_MEMBER"),
    ("member-b", "b", "FAMILY_MEMBER"),
]


# Service plans for dev (Mốc E, step E3). The public catalog needs plans to show and to register
# against. They are DEV data: production plans are decided by the team and entered through a
# separate channel, never by this script or a migration (docs/known_issues.md KI-19).
PLAN_PREFIX = "DEV-"
PLANS: list[dict] = [
    dict(
        code="DEV-TRIAL", name="DEV Trial", status="ACTIVE", price="0.00", billing_period_months=1,
        description="Gói dùng thử cho dev (không phải gói thật).",
        max_members=20, max_family_admins=1, storage_mb=256,
        features=[("MAX_PERSONS", True, 500), ("TREE_VIEW_3D", False, None)],
    ),
    dict(
        code="DEV-STANDARD", name="DEV Standard", status="ACTIVE", price="199000.00", billing_period_months=12,
        description="Gói tiêu chuẩn cho dev (không phải gói thật).",
        max_members=200, max_family_admins=5, storage_mb=2048,
        features=[("MAX_PERSONS", True, 5000), ("TREE_VIEW_3D", True, None), ("DATA_EXPORT", True, None)],
    ),
    dict(
        code="DEV-LEGACY", name="DEV Legacy (ngừng bán)", status="INACTIVE", price="99000.00", billing_period_months=12,
        description="Gói đã ngừng bán: để thử nhánh 'gói không hợp lệ' bằng tay.",
        max_members=100, max_family_admins=2, storage_mb=1024,
        features=[("TREE_VIEW_3D", False, None)],
    ),
]


class SeedError(Exception):
    """Expected failure with a message that is safe to print."""


def dev_sa_uid() -> str | None:
    """Real Firebase UID for dev-sa from the environment, validated, never printed."""
    value = os.environ.get(SA_UID_ENV, "").strip()
    if not value:
        return None
    if len(value) > 128 or any(ch.isspace() for ch in value):
        raise SeedError(f"{SA_UID_ENV} không hợp lệ (tối đa 128 ký tự, không có khoảng trắng).")
    return value


def email_of(key: str) -> str:
    return f"{EMAIL_PREFIX}{key}{EMAIL_SUFFIX}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def seed_plans(session, specs: list[dict] | None = None) -> tuple[Counter, Counter]:
    """Get-or-create the service plans and their feature limits. Returns (made, had).

    Idempotent and non-destructive: a plan is looked up by its unique code and a feature by
    (plan, feature_code). Anything that already exists is left exactly as it is (never
    overwritten, so a hand edit survives); only what is missing is added.
    """
    from decimal import Decimal

    from app.models.family.entities import PlanFeatureLimit, SubscriptionPlan
    from app.models.family.repository import FamilyRepository

    fam = FamilyRepository(session)
    made: Counter = Counter()
    had: Counter = Counter()
    for spec in PLANS if specs is None else specs:
        plan = await fam.get_plan_by_code(spec["code"])
        if plan is None:
            plan = SubscriptionPlan(
                plan_id=uuid.uuid4(),
                code=spec["code"],
                name=spec["name"],
                description=spec.get("description"),
                price=Decimal(spec["price"]),
                billing_period_months=spec["billing_period_months"],
                max_members=spec.get("max_members"),
                max_family_admins=spec.get("max_family_admins"),
                storage_mb=spec.get("storage_mb"),
                status=spec["status"],
            )
            session.add(plan)
            await session.flush()
            made["subscription_plans"] += 1
        else:
            had["subscription_plans"] += 1
        present = {f.feature_code for f in await fam.list_plan_feature_limits(plan.plan_id)}
        for feature_code, enabled, limit in spec.get("features", []):
            if feature_code in present:
                had["plan_feature_limits"] += 1
                continue
            session.add(
                PlanFeatureLimit(
                    plan_feature_id=uuid.uuid4(),
                    plan_id=plan.plan_id,
                    feature_code=feature_code,
                    enabled=enabled,
                    limit_value=None if limit is None else Decimal(str(limit)),
                    feature_metadata={},
                )
            )
            await session.flush()
            made["plan_feature_limits"] += 1
    return made, had


async def cleanup_plans(session, prefix: str = PLAN_PREFIX) -> tuple[int, int]:
    """Delete the plans whose code starts with `prefix` that nothing references. Returns
    (deleted, kept). A plan used by a registration or by a clan subscription is kept (the
    database would refuse to delete it anyway), and so is every plan without the prefix.
    Its feature limits go with it (ON DELETE CASCADE)."""
    from sqlalchemy import delete, exists, func, or_, select

    from app.models.family.entities import BusinessRegistration, ClanSubscription, SubscriptionPlan

    referenced = or_(
        exists().where(BusinessRegistration.requested_plan_id == SubscriptionPlan.plan_id),
        exists().where(ClanSubscription.plan_id == SubscriptionPlan.plan_id),
    )
    mine = SubscriptionPlan.code.startswith(prefix, autoescape=True)
    kept = (
        await session.execute(select(func.count()).select_from(SubscriptionPlan).where(mine, referenced))
    ).scalar_one()
    deleted = await session.execute(delete(SubscriptionPlan).where(mine, ~referenced))
    return deleted.rowcount, kept


def print_counts(title: str, made: Counter, had: Counter) -> None:
    print(title)
    for kind in sorted(set(made) | set(had)):
        print(f"  {kind:<34} tạo mới: {made[kind]:>2}   đã có: {had[kind]:>2}")


async def seed(session) -> Counter:
    from app.models.family.entities import (
        Clan,
        ClanMembership,
        ClanOwnershipHistory,
        FamilyAdminAssignment,
        FamilyAdminPermission,
    )
    from app.models.family.repository import FamilyRepository
    from app.models.user_access.entities import CredentialMetadata, User, UserRole
    from app.models.user_access.repository import UserAccessRepository

    ua, fam = UserAccessRepository(session), FamilyRepository(session)
    made: Counter = Counter()
    had: Counter = Counter()

    def mark(kind: str, created: bool) -> None:
        (made if created else had)[kind] += 1

    roles = {}
    for code in ("SYSTEM_ADMIN", "BUSINESS_OWNER", "FAMILY_ADMIN", "FAMILY_MEMBER"):
        role = await ua.get_role_by_code(code)
        if role is None:
            raise SeedError(f"Thiếu role {code} trong bảng roles. Seed không tự tạo role; dừng.")
        roles[code] = role
    if await ua.get_permission_by_code(FA_PERMISSION) is None:
        raise SeedError(
            f"Thiếu permission {FA_PERMISSION} trong bảng permissions. Seed không tự tạo; dừng."
        )

    real_sa_uid = dev_sa_uid()

    async def ensure_uid_free(uid: str, owner_id: uuid.UUID | None) -> None:
        other = await ua.get_user_by_firebase_uid(uid)
        if other is not None and other.user_id != owner_id:
            raise SeedError(f"UID trong {SA_UID_ENV} đã gắn với một user khác. Dừng.")

    users: dict[str, User] = {}
    for key, status, display_name in USERS:
        email = email_of(key)
        user = await ua.get_user_by_email(email)
        if user is not None:
            current = user.firebase_uid or ""
            # dev-sa may legitimately hold a real UID linked by an earlier run.
            if not current.startswith(UID_PREFIX) and key != "sa":
                raise SeedError(
                    f"E-mail {email} đã tồn tại nhưng không phải dữ liệu seed (firebase_uid "
                    f"không có tiền tố {UID_PREFIX}). Dừng để không chiếm tài khoản thật."
                )
            if key == "sa" and real_sa_uid and current != real_sa_uid:
                await ensure_uid_free(real_sa_uid, user.user_id)
                user.firebase_uid = real_sa_uid
                await session.flush()
                mark("users (đổi firebase_uid dev-sa)", True)
            mark("users", False)
        else:
            if key == "sa" and real_sa_uid:
                await ensure_uid_free(real_sa_uid, None)
            user = User(
                user_id=uuid.uuid4(),
                firebase_uid=real_sa_uid if key == "sa" and real_sa_uid else f"{UID_PREFIX}{key}",
                email=email,
                display_name=display_name,
                status=status,
                email_verified=True,
                first_login_required=False,
            )
            session.add(user)
            await session.flush()
            mark("users", True)
        users[key] = user

        if await ua.get_credential_metadata(user.user_id) is None:
            session.add(
                CredentialMetadata(
                    user_id=user.user_id,
                    auth_provider="FIREBASE",
                    must_change_password=False,
                    failed_login_count=0,
                )
            )
            mark("credential_metadata", True)
        else:
            mark("credential_metadata", False)
    await session.flush()

    sa_id = users["sa"].user_id

    async def ensure_role(user: User, code: str, clan_id: uuid.UUID | None) -> None:
        if await ua.has_active_role(user.user_id, code, clan_id=clan_id):
            mark("user_roles", False)
            return
        session.add(
            UserRole(
                user_role_id=uuid.uuid4(),
                user_id=user.user_id,
                role_id=roles[code].role_id,
                clan_id=clan_id,
                granted_by=sa_id,
            )
        )
        await session.flush()
        mark("user_roles", True)

    async def ensure_membership(clan: Clan, user: User) -> None:
        if await fam.get_membership(clan.clan_id, user.user_id) is None:
            session.add(
                ClanMembership(
                    membership_id=uuid.uuid4(),
                    clan_id=clan.clan_id,
                    user_id=user.user_id,
                    status="ACTIVE",
                    joined_at=_now(),
                )
            )
            await session.flush()
            mark("clan_memberships", True)
        else:
            mark("clan_memberships", False)

    # System Admin: system scope (clan_id NULL).
    await ensure_role(users["sa"], "SYSTEM_ADMIN", None)

    clans: dict[str, Clan] = {}
    for ckey, (code, name, status, owner_key) in CLANS.items():
        clan = await fam.get_clan_by_code(code)
        if clan is None:
            clan = Clan(
                clan_id=uuid.uuid4(),
                clan_code=code,
                name=name,
                status=status,
                created_by=sa_id,
                activated_at=_now() if status == "ACTIVE" else None,
            )
            session.add(clan)
            await session.flush()
            mark("clans", True)
        else:
            mark("clans", False)
        clans[ckey] = clan

        owner = users[owner_key]
        await ensure_role(owner, "BUSINESS_OWNER", clan.clan_id)
        active_owner = await fam.get_active_owner(clan.clan_id)
        if active_owner is None:
            session.add(
                ClanOwnershipHistory(
                    ownership_id=uuid.uuid4(),
                    clan_id=clan.clan_id,
                    user_id=owner.user_id,
                    started_at=_now(),
                )
            )
            await session.flush()
            mark("clan_ownership_history", True)
        elif active_owner.user_id != owner.user_id:
            raise SeedError(f"Clan {code} đã có Owner hiệu lực khác dữ liệu seed. Dừng.")
        else:
            mark("clan_ownership_history", False)
        await ensure_membership(clan, owner)

    for ukey, ckey, role_code in EXTRA_MEMBERS:
        await ensure_membership(clans[ckey], users[ukey])
        await ensure_role(users[ukey], role_code, clans[ckey].clan_id)

    # Family Admin of clan A: clan-wide assignment (branch_id NULL) + MEMBER_ACCOUNT_MANAGE.
    clan_a, fa = clans["a"], users["fa-a"]
    assignments = await fam.list_active_fa_assignments(clan_a.clan_id, user_id=fa.user_id)
    if assignments:
        assignment_id = assignments[0].assignment_id
        mark("family_admin_assignments", False)
    else:
        assignment_id = uuid.uuid4()
        session.add(
            FamilyAdminAssignment(
                assignment_id=assignment_id,
                user_id=fa.user_id,
                clan_id=clan_a.clan_id,
                assigned_by=users["bo-a"].user_id,
            )
        )
        await session.flush()
        mark("family_admin_assignments", True)
    if FA_PERMISSION in await fam.list_fa_permission_codes(clan_a.clan_id, fa.user_id):
        mark("family_admin_permissions", False)
    else:
        session.add(
            FamilyAdminPermission(
                assignment_id=assignment_id,
                permission_code=FA_PERMISSION,
                granted_by=users["bo-a"].user_id,
            )
        )
        await session.flush()
        mark("family_admin_permissions", True)

    plans_made, plans_had = await seed_plans(session)
    made.update(plans_made)
    had.update(plans_had)

    kinds = sorted(set(made) | set(had))
    print("Seed dev (một transaction):")
    for kind in kinds:
        print(f"  {kind:<34} tạo mới: {made[kind]:>2}   đã có: {had[kind]:>2}")
    sa_uid = users["sa"].firebase_uid or ""
    source = (
        f"lấy từ {SA_UID_ENV}" if real_sa_uid
        else "giá trị giả dev-sa" if sa_uid.startswith(UID_PREFIX)
        else f"UID thật đã gắn từ trước (giữ nguyên; không đặt {SA_UID_ENV})"
    )
    print(f"  firebase_uid của dev-sa: {source} (không in giá trị)")
    return made


async def cleanup(session) -> None:
    from sqlalchemy import delete

    from app.models.family.entities import Clan
    from app.models.user_access.entities import User

    # Clans first: ownership/membership/assignments cascade from clans, while
    # clan_ownership_history.user_id has no ON DELETE action.
    clans = await session.execute(delete(Clan).where(Clan.clan_code.startswith(CLAN_PREFIX)))
    # By e-mail only: dev-sa may carry a real Firebase UID. Nothing is deleted in
    # Firebase itself, only the DB rows.
    users = await session.execute(
        delete(User).where(
            User.email.startswith(EMAIL_PREFIX),
            User.email.endswith(EMAIL_SUFFIX),
        )
    )
    plans_deleted, plans_kept = await cleanup_plans(session)
    print("Cleanup dev (một transaction):")
    print(f"  clans đã xóa: {clans.rowcount}   users đã xóa: {users.rowcount}")
    print(f"  gói {PLAN_PREFIX}* đã xóa: {plans_deleted}   gói giữ lại vì còn được tham chiếu: {plans_kept}")


async def run(do_cleanup: bool, plans_only: bool = False) -> None:
    from app.db.postgres import async_session_maker, engine

    try:
        async with async_session_maker() as session:
            async with session.begin():
                if plans_only and do_cleanup:
                    deleted, kept = await cleanup_plans(session)
                    print("Cleanup gói dev (một transaction):")
                    print(f"  gói {PLAN_PREFIX}* đã xóa: {deleted}   gói giữ lại vì còn được tham chiếu: {kept}")
                elif plans_only:
                    made, had = await seed_plans(session)
                    print_counts("Seed gói dev (một transaction):", made, had)
                elif do_cleanup:
                    await cleanup(session)
                else:
                    await seed(session)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="Seed (or clean) dev data on the real DB.")
    parser.add_argument("--cleanup", action="store_true", help="delete only DEV-* seed data")
    parser.add_argument(
        "--plans-only",
        action="store_true",
        help="only the DEV-* service plans (no users, clans or memberships); with --cleanup, only unreferenced DEV-* plans",
    )
    args = parser.parse_args(argv)

    if os.environ.get(ENV_FLAG) != "1":
        print(f"Từ chối chạy: cần đặt {ENV_FLAG}=1 (script ghi vào database thật).")
        return 2

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        # Import before asyncio.run: it installs the Windows selector loop policy psycopg needs.
        import app.db.postgres  # noqa: F401

        asyncio.run(run(args.cleanup, args.plans_only))
    except SeedError as exc:
        print(f"Lỗi seed: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - never print exception text (may embed DATABASE_URL)
        print(f"Lỗi không lường trước ({type(exc).__name__}); transaction đã rollback.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
