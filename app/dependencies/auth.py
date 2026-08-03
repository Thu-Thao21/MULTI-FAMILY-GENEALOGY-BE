from typing import Callable, List
from fastapi import Depends, HTTPException, Header, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.firebase import verify_firebase_token
from app.db.postgres import get_db
from app.models.postgres import Account
from app.services.auth_service import bootstrap_account, calculate_primary_role, get_account_by_firebase_uid


async def get_current_account(
    authorization: str = Header(None, description="Bearer <Token>"),
    db: AsyncSession = Depends(get_db),
) -> Account:
    """
    Extracts Bearer token (Firebase ID Token or Custom Backend Token),
    loads Account from PostgreSQL DB and verifies active status.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Thiếu Authorization header dạng Bearer <token>.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    id_token = authorization.split("Bearer ")[1].strip()
    if not id_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token không hợp lệ.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 1. Handle Custom Backend Tokens (e.g. token_admin_admin_default_001 or token_family_head_family_head_default_001)
    if id_token.startswith("token_"):
        raw = id_token[len("token_"):]
        account_id = None
        for r in ["admin", "family_head", "member"]:
            if raw.startswith(f"{r}_"):
                account_id = raw[len(f"{r}_"):]
                break
        if not account_id:
            account_id = raw

        stmt = select(Account).options(selectinload(Account.roles)).where(Account.id == account_id)
        res = await db.execute(stmt)
        account = res.scalar_one_or_none()

        if account:
            if account.status != "active":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Tài khoản của bạn đã bị khóa hoặc tạm ngưng hoạt động.",
                )
            return account

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tài khoản không tồn tại hoặc token không hợp lệ.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 2. Handle Firebase Auth Tokens
    try:
        decoded_token = verify_firebase_token(id_token)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token không hợp lệ hoặc đã hết hạn: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    firebase_uid = decoded_token.get("uid")
    account = await get_account_by_firebase_uid(db, firebase_uid)

    if not account:
        account = await bootstrap_account(db, decoded_token)

    if account.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản của bạn đã bị khóa hoặc tạm ngưng hoạt động.",
        )

    return account


def require_roles(allowed_roles: List[str]) -> Callable:
    """
    FastAPI Role Guard Dependency Factory.
    Ensures current authenticated account has at least one of allowed_roles in PostgreSQL.
    """
    async def role_checker(account: Account = Depends(get_current_account)) -> Account:
        user_roles = [r.role.lower() for r in account.roles if r.status == "active"]
        
        # Super admin always bypasses specific role checks
        if "admin" in user_roles:
            return account

        has_permission = any(role.lower() in user_roles for role in allowed_roles)
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Bạn không có quyền truy cập tính năng này. Yêu cầu một trong các quyền: {', '.join(allowed_roles)}.",
            )
        return account

    return role_checker
