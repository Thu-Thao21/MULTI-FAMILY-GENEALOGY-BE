from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.models.postgres import Admin, Member

router = APIRouter(prefix="/users", tags=["users"])


class UserOut(BaseModel):
    id: str
    username: Optional[str] = None
    full_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    role: str
    status: str

    class Config:
        from_attributes = True


@router.get("/", response_model=List[UserOut])
async def list_users(role: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    """Lấy danh sách tất cả tài khoản từ 2 bảng (admins, members)."""
    results: List[UserOut] = []

    if not role or role == "admin":
        res = await db.execute(select(Admin))
        for item in res.scalars().all():
            results.append(
                UserOut(
                    id=item.id,
                    username=item.username,
                    full_name=item.full_name,
                    email=item.email,
                    phone=item.phone,
                    role="admin",
                    status=item.status,
                )
            )

    if not role or role == "member":
        res = await db.execute(select(Member))
        for item in res.scalars().all():
            if item.username:
                results.append(
                    UserOut(
                        id=item.id,
                        username=item.username,
                        full_name=item.full_name,
                        email=item.email,
                        phone=item.phone,
                        role="member",
                        status=item.status,
                    )
                )

    return results


@router.get("/admins")
async def list_admins(db: AsyncSession = Depends(get_db)):
    """Lấy danh sách tài khoản từ bảng admins."""
    result = await db.execute(select(Admin))
    admins = result.scalars().all()
    return admins

