import logging
from typing import Dict, Any, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.postgres import Account, AccountRole, Member
from app.schemas.auth_schemas import AccountOut, RoleOut

logger = logging.getLogger("mfg.auth_service")


from sqlalchemy import or_

async def get_account_by_firebase_uid(db: AsyncSession, firebase_uid: str) -> Optional[Account]:
    stmt = select(Account).options(selectinload(Account.roles)).where(Account.firebase_uid == firebase_uid)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_account_by_uid_or_email(db: AsyncSession, firebase_uid: str, email: Optional[str] = None) -> Optional[Account]:
    conditions = [Account.firebase_uid == firebase_uid]
    if email:
        conditions.append(Account.email == email)
    stmt = select(Account).options(selectinload(Account.roles)).where(or_(*conditions))
    result = await db.execute(stmt)
    return result.scalars().first()


async def bootstrap_account(
    db: AsyncSession,
    decoded_token: Dict[str, Any],
) -> Account:
    """
    Finds an existing account by firebase_uid or email, or creates a new Account with default 'member' role.
    If the account email matches default super-admin, grants 'admin' role automatically.
    """
    firebase_uid = decoded_token.get("uid")
    email = decoded_token.get("email")
    email_verified = decoded_token.get("email_verified", False)
    phone_e164 = decoded_token.get("phone_number")
    display_name = decoded_token.get("name") or decoded_token.get("email") or phone_e164 or "Thành viên gia phả"

    if not firebase_uid:
        raise ValueError("Firebase token không chứa UID.")

    account = await get_account_by_uid_or_email(db, firebase_uid, email)

    if account:
        # Link firebase_uid if missing or updated
        if account.firebase_uid != firebase_uid:
            account.firebase_uid = firebase_uid
        if email and account.email != email:
            account.email = email
        if email_verified != account.email_verified:
            account.email_verified = email_verified
        if phone_e164 and account.phone_e164 != phone_e164:
            account.phone_e164 = phone_e164
            account.phone_verified = True
        if display_name and not account.display_name:
            account.display_name = display_name
        
        if not account.roles:
            default_role = "admin" if (email and email.lower() == "thuthaor120608@gmail.com") else "member"
            role_obj = AccountRole(
                account_id=account.id,
                role=default_role,
                status="active",
            )
            db.add(role_obj)

        await db.commit()
        await db.refresh(account)
    else:
        # Create new account
        account = Account(
            firebase_uid=firebase_uid,
            email=email,
            email_verified=email_verified,
            phone_e164=phone_e164,
            phone_verified=True if phone_e164 else False,
            display_name=display_name,
            status="active",
        )
        db.add(account)
        await db.flush()

        # Determine default roles
        default_role = "admin" if (email and email.lower() == "thuthaor120608@gmail.com") else "member"

        role_obj = AccountRole(
            account_id=account.id,
            role=default_role,
            status="active",
        )
        db.add(role_obj)

        await db.commit()
        
        # --- Sync to Member Table ---
        member_conditions = []
        if email:
            member_conditions.append(Member.email == email)
        if phone_e164:
            member_conditions.append(Member.phone == phone_e164)
            
        member = None
        if member_conditions:
            stmt = select(Member).where(or_(*member_conditions))
            res = await db.execute(stmt)
            member = res.scalars().first()
            
        if not member:
            # Use same ID as account for easy reference, but ensure it's a string
            new_member = Member(
                id=account.id,
                email=email,
                phone=phone_e164,
                full_name=display_name,
                username=None,  # Null is safe for unique constraint
                role=default_role,
                status="active"
            )
            db.add(new_member)
            try:
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.warning(f"Could not sync Member for Account {account.id}: {e}")
        # ---------------------------

    return await get_account_by_firebase_uid(db, firebase_uid)


def calculate_primary_role(roles: List[AccountRole]) -> str:
    active_roles = [r.role.lower() for r in roles if r.status == "active"]
    if "admin" in active_roles:
        return "admin"
    return "member"


def format_account_me(account: Account) -> AccountOut:
    primary_role = calculate_primary_role(account.roles)
    role_outs = [
        RoleOut(
            id=r.id,
            account_id=r.account_id,
            role=r.role,
            family_id=r.family_id,
            status=r.status,
            created_at=r.created_at,
        )
        for r in account.roles
    ]

    return AccountOut(
        id=account.id,
        firebase_uid=account.firebase_uid,
        username=account.username,
        email=account.email,
        phone_e164=account.phone_e164,
        display_name=account.display_name,
        email_verified=account.email_verified,
        phone_verified=account.phone_verified,
        status=account.status,
        roles=role_outs,
        primary_role=primary_role,
    )
