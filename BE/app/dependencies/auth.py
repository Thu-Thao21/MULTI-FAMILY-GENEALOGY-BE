from __future__ import annotations

from typing import Annotated, Callable, List

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.firebase import verify_firebase_token
from app.db.postgres import get_db
from app.models.postgres import Account
from app.services.auth_service import bootstrap_account, get_account_by_firebase_uid


firebase_bearer = HTTPBearer(
    scheme_name="FirebaseBearer",
    bearerFormat="JWT",
    description="Nhập Firebase ID token (không thêm tiền tố Bearer).",
    auto_error=False,
)


async def get_current_account(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(firebase_bearer),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Account:
    """Verify Firebase and resolve its canonical Neon users row."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Thiếu Authorization header dạng Bearer <Firebase ID token>.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    id_token = credentials.credentials.strip()
    if not id_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firebase ID token không hợp lệ.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        decoded_token = verify_firebase_token(id_token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firebase ID token không hợp lệ hoặc đã hết hạn.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    firebase_uid = decoded_token.get("uid")
    if not firebase_uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firebase ID token không có UID.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    account = await get_account_by_firebase_uid(db, firebase_uid)
    if account is None:
        try:
            account = await bootstrap_account(db, decoded_token)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    if account.status.upper() != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản đã bị khóa hoặc tạm ngưng hoạt động.",
        )
    return account


def require_roles(allowed_roles: List[str]) -> Callable:
    async def role_checker(
        account: Account = Depends(get_current_account),
    ) -> Account:
        active_roles = {
            assignment.role_record.code.lower()
            for assignment in account.roles
            if assignment.revoked_at is None
        }
        allowed = {role.lower() for role in allowed_roles}
        if "admin" not in active_roles and active_roles.isdisjoint(allowed):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bạn không có vai trò cần thiết để truy cập tính năng này.",
            )
        return account

    return role_checker
