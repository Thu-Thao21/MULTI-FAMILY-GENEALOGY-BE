from datetime import datetime, timedelta, timezone
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.db.postgres import get_db
from app.models.postgres import Account, AccountRole, Admin, Member, PasswordReset, UserSession
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


class LoginSchema(BaseModel):
    email_or_phone: str
    password: str


async def create_session(db: AsyncSession, account_id: str) -> str:
    token = f"session_{secrets.token_urlsafe(32)}"
    db.add(UserSession(
        user_id=account_id,
        session_token=token,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    ))
    await db.commit()
    return token


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

    if len(username_str) < 3:
        raise HTTPException(status_code=400, detail="Tên đăng nhập phải có ít nhất 3 ký tự.")
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Mật khẩu phải có ít nhất 6 ký tự.")

    is_email = "@" in input_str
    email_val = input_str if is_email else None
    phone_val = input_str if not is_email else None
    now = datetime.now(timezone.utc)
    display_name = payload.display_name.strip() if payload.display_name else payload.username.strip()

    # Account is the canonical authentication record. A genealogy Member profile
    # can be linked later without making registration depend on its schema.
    conditions = [Account.username == username_str]
    if email_val:
        conditions.append(Account.email == email_val)
    if phone_val:
        conditions.append(Account.phone_e164 == phone_val)

    stmt = select(Account).where(or_(*conditions))
    result = await db.execute(stmt)
    existing_account = result.scalars().first()
    if existing_account:
        if existing_account.username == username_str:
            detail_msg = "Tên đăng nhập này đã tồn tại trong hệ thống."
        elif email_val and existing_account.email == email_val:
            detail_msg = "Email này đã được đăng ký."
        else:
            detail_msg = "Số điện thoại này đã được đăng ký."
        raise HTTPException(
            status_code=400,
            detail=detail_msg
        )

    account_id = f"account_{int(now.timestamp() * 1000)}"
    account_obj = Account(
        id=account_id,
        firebase_uid=f"local_{account_id}",
        username=username_str,
        email=email_val,
        phone_e164=phone_val,
        display_name=display_name,
        password_hash=hash_password(payload.password),
        email_verified=False,
        phone_verified=False,
        status="active",
        created_at=now,
        updated_at=now,
    )
    db.add(account_obj)
    db.add(AccountRole(account_id=account_id, role="member", status="active"))
    try:
        await db.commit()
        await db.refresh(account_obj)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Tên đăng nhập, email hoặc số điện thoại đã được sử dụng.",
        )

    session_token = await create_session(db, account_obj.id)
    return {
        "user": {
            "id": account_obj.id,
            "username": account_obj.username,
            "displayName": account_obj.display_name,
            "email": account_obj.email,
            "phone": account_obj.phone_e164,
            "role": "member",
        },
        "token": session_token,
        "message": "Đăng ký tài khoản Thành Viên thành công.",
    }


@router.post("/login")
async def login(payload: LoginSchema, db: AsyncSession = Depends(get_db)):
    input_str = payload.email_or_phone.strip().lower()
    stmt = select(Account).options(selectinload(Account.roles)).where(
        or_(
            Account.username == input_str,
            Account.email == input_str,
            Account.phone_e164 == input_str,
        )
    )
    result = await db.execute(stmt)
    account = result.scalars().first()
    if not account:
        raise HTTPException(
            status_code=400,
            detail="Tài khoản hoặc Email/Số điện thoại chưa tồn tại trong hệ thống."
        )

    if not account.password_hash or not verify_password(payload.password, account.password_hash):
        raise HTTPException(
            status_code=400,
            detail="Mật khẩu không chính xác."
        )

    if account.status != "active":
        raise HTTPException(status_code=403, detail="Tài khoản đã bị khóa hoặc tạm ngưng hoạt động.")

    if not any(role.status == "active" for role in account.roles):
        raise HTTPException(status_code=403, detail="Tài khoản chưa được cấp quyền truy cập.")

    target_role = calculate_primary_role(account.roles)
    session_token = await create_session(db, account.id)
    return {
        "user": {
            "id": account.id,
            "username": account.username,
            "displayName": account.display_name or account.username,
            "email": account.email,
            "phone": account.phone_e164,
            "role": target_role,
        },
        "account": format_account_me(account),
        "token": session_token,
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
        for ModelClass, r_name in [(Admin, "admin"), (Member, "member")]:
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
