from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.db.postgres import get_db
from app.models.postgres import Account, Admin, FamilyHead, Member, PasswordReset
from app.schemas.auth_schemas import AccountOut
from app.services.auth_service import bootstrap_account, format_account_me, calculate_primary_role
from app.dependencies.auth import get_current_account
from app.core.firebase import verify_firebase_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/bootstrap", response_model=AccountOut)
async def bootstrap(
    account: Account = Depends(get_current_account),
):
    """
    Initializes or syncs current Firebase authenticated user in PostgreSQL.
    Returns Account details including roles and primary_role.
    """
    return format_account_me(account)


@router.get("/me", response_model=AccountOut)
async def get_me(
    account: Account = Depends(get_current_account),
):
    """
    Returns current authenticated user profile, roles, and status from PostgreSQL.
    """
    return format_account_me(account)



class RegisterSchema(BaseModel):
    username: str
    email_or_phone: str
    display_name: Optional[str] = None
    password: str
    role: Optional[str] = "member"  # "family_head" hoặc "member"


class LoginSchema(BaseModel):
    email_or_phone: str
    password: str
    role: Optional[str] = "member"  # "admin", "family_head", "member"


class RequestOTPSchema(BaseModel):
    email_or_phone: str


class ResetPasswordSchema(BaseModel):
    email_or_phone: str
    otp_code: str
    new_password: str


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterSchema, db: AsyncSession = Depends(get_db)):
    input_str = payload.email_or_phone.strip().lower()
    username_str = payload.username.strip().lower()
    user_role = payload.role if payload.role in ["family_head", "member"] else "member"

    is_email = "@" in input_str
    email_val = input_str if is_email else None
    phone_val = input_str if not is_email else None
    now = datetime.now(timezone.utc)
    display_name = payload.display_name.strip() if payload.display_name else payload.username.strip()

    if user_role == "family_head":
        # Check existing in family_heads
        stmt = select(FamilyHead).where(
            or_(
                FamilyHead.username == username_str,
                FamilyHead.email == email_val,
                FamilyHead.phone == phone_val,
            )
        )
        result = await db.execute(stmt)
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=400,
                detail="Tài khoản Trưởng Họ này đã tồn tại trong hệ thống."
            )

        head_obj = FamilyHead(
            id=f"head_{int(now.timestamp() * 1000)}",
            username=username_str,
            email=email_val,
            phone=phone_val,
            full_name=display_name,
            password_hash=hash_password(payload.password),
            role="family_head",
            status="active",
            created_at=now,
            updated_at=now,
        )
        db.add(head_obj)
        await db.commit()
        await db.refresh(head_obj)

        return {
            "user": {
                "id": head_obj.id,
                "username": head_obj.username,
                "displayName": head_obj.full_name,
                "email": head_obj.email,
                "phone": head_obj.phone,
                "role": head_obj.role,
            },
            "message": "Đăng ký tài khoản Trưởng Họ thành công vào PostgreSQL.",
        }

    else:
        # Check existing in members
        stmt = select(Member).where(
            or_(
                Member.username == username_str,
                Member.email == email_val,
                Member.phone == phone_val,
            )
        )
        result = await db.execute(stmt)
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=400,
                detail="Tài khoản Thành Viên này đã tồn tại trong hệ thống."
            )

        member_obj = Member(
            id=f"member_{int(now.timestamp() * 1000)}",
            username=username_str,
            email=email_val,
            phone=phone_val,
            full_name=display_name,
            password_hash=hash_password(payload.password),
            role="member",
            status="active",
            created_at=now,
            updated_at=now,
        )
        db.add(member_obj)
        await db.commit()
        await db.refresh(member_obj)

        return {
            "user": {
                "id": member_obj.id,
                "username": member_obj.username,
                "displayName": member_obj.full_name,
                "email": member_obj.email,
                "phone": member_obj.phone,
                "role": member_obj.role,
            },
            "message": "Đăng ký tài khoản Thành Viên thành công vào PostgreSQL.",
        }


@router.post("/login")
async def login(payload: LoginSchema, db: AsyncSession = Depends(get_db)):
    input_str = payload.email_or_phone.strip().lower()
    requested_role = (payload.role or "member").lower()

    account = None
    target_role = requested_role

    if requested_role == "admin":
        stmt = select(Admin).where(
            or_(
                Admin.username == input_str,
                Admin.email == input_str,
                Admin.phone == input_str
            )
        )
        result = await db.execute(stmt)
        account = result.scalar_one_or_none()
        target_role = "admin"

    elif requested_role == "family_head":
        stmt = select(FamilyHead).where(
            or_(
                FamilyHead.username == input_str,
                FamilyHead.email == input_str,
                FamilyHead.phone == input_str
            )
        )
        result = await db.execute(stmt)
        account = result.scalar_one_or_none()
        target_role = "family_head"

    else:
        stmt = select(Member).where(
            or_(
                Member.username == input_str,
                Member.email == input_str,
                Member.phone == input_str
            )
        )
        result = await db.execute(stmt)
        account = result.scalar_one_or_none()
        target_role = "member"

    # Fallback search across Account and all role tables if not found in requested table
    if not account:
        stmt = select(Account).options(selectinload(Account.roles)).where(
            or_(
                Account.username == input_str,
                Account.email == input_str,
                Account.phone_e164 == input_str
            )
        )
        res = await db.execute(stmt)
        acc = res.scalars().first()
        if acc:
            account = acc
            target_role = calculate_primary_role(acc.roles)

    if not account:
        for ModelClass, r_name in [(Admin, "admin"), (FamilyHead, "family_head"), (Member, "member")]:
            stmt = select(ModelClass).where(
                or_(
                    ModelClass.username == input_str,
                    ModelClass.email == input_str,
                    ModelClass.phone == input_str
                )
            )
            res = await db.execute(stmt)
            acc = res.scalars().first()
            if acc:
                account = acc
                target_role = r_name
                break


    if not account:
        raise HTTPException(
            status_code=400,
            detail="Tài khoản hoặc Email/Số điện thoại chưa tồn tại trong hệ thống."
        )

    is_valid = False
    if account.password_hash:
        try:
            is_valid = verify_password(payload.password, account.password_hash)
        except Exception:
            is_valid = False

    if not is_valid:
        raise HTTPException(
            status_code=400,
            detail="Mật khẩu không chính xác."
        )

    return {
        "user": {
            "id": account.id,
            "username": getattr(account, "username", input_str),
            "displayName": getattr(account, "full_name", input_str),
            "email": getattr(account, "email", None),
            "phone": getattr(account, "phone", None),
            "role": target_role,
        },
        "token": f"token_{target_role}_{account.id}",
        "message": f"Đăng nhập thành công với vai trò {target_role.upper()}.",
    }


@router.post("/request-otp")
async def request_otp(payload: RequestOTPSchema, db: AsyncSession = Depends(get_db)):
    import random
    input_str = payload.email_or_phone.strip().lower()

    # Find account across Account (Google/Firebase users), Admin, FamilyHead, Member
    account = None
    account_type = None

    # 1. Check Account table (Google / Firebase users)
    stmt = select(Account).where(
        or_(
            Account.username == input_str,
            Account.email == input_str,
            Account.phone_e164 == input_str,
        )
    )
    res = await db.execute(stmt)
    acc = res.scalars().first()
    if acc:
        account = acc
        account_type = "account"

    # 2. Fallback check in Admin, FamilyHead, Member tables
    if not account:
        for ModelClass, r_name in [(Admin, "admin"), (FamilyHead, "family_head"), (Member, "member")]:
            stmt = select(ModelClass).where(
                or_(
                    ModelClass.username == input_str,
                    ModelClass.email == input_str,
                    ModelClass.phone == input_str,
                )
            )
            res = await db.execute(stmt)
            acc = res.scalars().first()
            if acc:
                account = acc
                account_type = r_name
                break

    if not account:
        raise HTTPException(
            status_code=400,
            detail="Tài khoản hoặc Email/Số điện thoại không tồn tại trong hệ thống."
        )

    # Generate 6-digit OTP
    otp_code = f"{random.randint(100000, 999999)}"
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=10)

    reset_record = PasswordReset(
        id=f"reset_{int(now.timestamp() * 1000)}",
        user_id=account.id,
        email_or_phone=input_str,
        otp_code=otp_code,
        expires_at=expires_at,
        is_used=False,
        created_at=now,
    )
    db.add(reset_record)
    await db.commit()

    print(f"\n[OTP SERVICE] Ma OTP khoi phuc mat khau cho {input_str}: {otp_code} (Het han luc: {expires_at.strftime('%H:%M:%S')})\n")

    # Send real email via SMTP if user input is email
    if "@" in input_str:
        import asyncio
        from app.services.email_service import send_otp_email
        await asyncio.to_thread(send_otp_email, input_str, otp_code)


    target_type = "email" if "@" in input_str else "số điện thoại"
    return {
        "message": f"Mã OTP xác thực (6 chữ số) đã được gửi tới {target_type} {input_str}. Vui lòng kiểm tra tin nhắn/hộp thư của bạn.",
    }



@router.post("/reset-password")
async def reset_password(payload: ResetPasswordSchema, db: AsyncSession = Depends(get_db)):
    input_str = payload.email_or_phone.strip().lower()
    otp_code_str = payload.otp_code.strip()
    new_password_str = payload.new_password.strip()

    if len(new_password_str) < 6:
        raise HTTPException(status_code=400, detail="Mật khẩu mới phải có ít nhất 6 ký tự.")

    now = datetime.now(timezone.utc)

    stmt = (
        select(PasswordReset)
        .where(
            PasswordReset.email_or_phone == input_str,
            PasswordReset.otp_code == otp_code_str,
            PasswordReset.is_used == False,
        )
        .order_by(PasswordReset.created_at.desc())
    )
    res = await db.execute(stmt)
    reset_record = res.scalars().first()

    if not reset_record:
        raise HTTPException(
            status_code=400,
            detail="Mã OTP không chính xác hoặc đã được sử dụng."
        )

    # Make sure expires_at is timezone-aware for offset-safe comparison
    exp_at = reset_record.expires_at
    if exp_at and exp_at.tzinfo is None:
        exp_at = exp_at.replace(tzinfo=timezone.utc)

    if exp_at < now:
        raise HTTPException(
            status_code=400,
            detail="Mã OTP đã hết hạn sử dụng. Vui lòng yêu cầu mã OTP mới."
        )


    # Mark OTP as used
    reset_record.is_used = True

    # Update account password_hash across Account, Admin, FamilyHead, Member
    account = None

    # Check Account table first
    stmt = select(Account).where(
        or_(
            Account.username == input_str,
            Account.email == input_str,
            Account.phone_e164 == input_str,
            Account.id == reset_record.user_id,
        )
    )
    res = await db.execute(stmt)
    acc = res.scalars().first()
    if acc:
        account = acc
    else:
        for ModelClass in [Admin, FamilyHead, Member]:
            stmt = select(ModelClass).where(
                or_(
                    ModelClass.username == input_str,
                    ModelClass.email == input_str,
                    ModelClass.phone == input_str,
                    ModelClass.id == reset_record.user_id,
                )
            )
            res = await db.execute(stmt)
            acc = res.scalars().first()
            if acc:
                account = acc
                break

    if not account:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy thông tin tài khoản cần cập nhật mật khẩu."
        )

    account.password_hash = hash_password(new_password_str)
    account.updated_at = now

    await db.commit()


    return {
        "message": "Đặt lại mật khẩu thành công! Bạn có thể đăng nhập bằng mật khẩu mới."
    }

