from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.postgres import Account, AccountRole, Role
from app.schemas.auth_schemas import AccountOut, RoleOut


async def assign_role_by_code(
    db: AsyncSession,
    account_id: str,
    role_code: str,
    family_id: str | None = None,
) -> None:
    result = await db.execute(select(Role).where(Role.code.ilike(role_code)))
    role = result.scalar_one_or_none()
    if role is not None:
        db.add(
            AccountRole(
                account_id=account_id,
                role_id=role.id,
                family_id=family_id,
            )
        )


async def get_account_by_firebase_uid(
    db: AsyncSession, firebase_uid: str
) -> Optional[Account]:
    result = await db.execute(
        select(Account)
        .options(selectinload(Account.roles))
        .where(Account.firebase_uid == firebase_uid)
    )
    return result.scalar_one_or_none()


async def get_account_by_uid_or_email(
    db: AsyncSession,
    firebase_uid: str,
    verified_email: Optional[str] = None,
) -> Optional[Account]:
    conditions = [Account.firebase_uid == firebase_uid]
    if verified_email:
        conditions.append(Account.email == verified_email)
    result = await db.execute(
        select(Account)
        .options(selectinload(Account.roles))
        .where(or_(*conditions))
    )
    return result.scalars().first()


async def bootstrap_account(
    db: AsyncSession,
    decoded_token: Dict[str, Any],
) -> Account:
    """Upsert a Neon users row from a verified Firebase ID token."""
    firebase_uid = decoded_token.get("uid")
    token_email = decoded_token.get("email")
    email_verified = bool(decoded_token.get("email_verified", False))
    phone = decoded_token.get("phone_number")
    display_name = (
        decoded_token.get("name")
        or token_email
        or phone
        or "Thành viên gia phả"
    )

    if not firebase_uid:
        raise ValueError("Firebase token không chứa UID")
    if not token_email:
        raise ValueError("Neon users.email là bắt buộc; Firebase token thiếu email")

    verified_email = token_email if email_verified else None
    account = await get_account_by_uid_or_email(
        db, firebase_uid, verified_email
    )
    now = datetime.now(timezone.utc)

    if account is None:
        account = Account(
            firebase_uid=firebase_uid,
            email=token_email,
            phone_e164=phone,
            display_name=display_name,
            status="ACTIVE",
            email_verified=email_verified,
            phone_verified=bool(phone),
            first_login_required=True,
            last_login_at=now,
        )
        db.add(account)
        await db.flush()
        await assign_role_by_code(db, account.id, "member")
    else:
        account.firebase_uid = firebase_uid
        account.email = token_email
        account.display_name = display_name
        account.email_verified = email_verified
        if phone:
            account.phone_e164 = phone
            account.phone_verified = True
        account.last_login_at = now

    await db.commit()
    return await get_account_by_firebase_uid(db, firebase_uid)


def calculate_primary_role(roles: List[AccountRole]) -> str:
    active_roles = [
        assignment.role_record.code.lower()
        for assignment in roles
        if assignment.revoked_at is None
    ]
    if "admin" in active_roles:
        return "admin"
    if "family_head" in active_roles:
        return "family_head"
    if "manager" in active_roles:
        return "manager"
    return active_roles[0] if active_roles else "member"


def format_account_me(account: Account) -> AccountOut:
    return AccountOut(
        id=account.id,
        firebase_uid=account.firebase_uid,
        username=account.username,
        email=account.email,
        phone_e164=account.phone_e164,
        display_name=account.display_name,
        email_verified=account.email_verified,
        phone_verified=account.phone_verified,
        first_login_required=account.first_login_required,
        last_login_at=account.last_login_at,
        status=account.status,
        roles=[
            RoleOut(
                id=assignment.id,
                account_id=assignment.account_id,
                role=assignment.role_record.code,
                family_id=assignment.family_id,
                granted_at=assignment.granted_at,
                revoked_at=assignment.revoked_at,
            )
            for assignment in account.roles
        ],
        primary_role=calculate_primary_role(account.roles),
    )
