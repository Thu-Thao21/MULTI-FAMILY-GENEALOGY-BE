"""Auth routes (api_contract.md section 3). Mounted under /api/v1."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers.auth_access import use_cases
from app.controllers.auth_access.use_cases import ClientInfo
from app.core.integrations.firebase import IdentityProvider, get_identity_provider
from app.core.utils.openapi_responses import (
    AUTHENTICATED_RESTRICTED_OK,
    BASE,
    error_responses,
)
from app.core.middleware.rate_limit import rate_limited
from app.core.security.security_headers import NoStoreRoute
from app.db.postgres import get_db
from app.dependencies.auth import Principal, get_principal_allow_restricted, get_user_access_repo
from app.dependencies.permissions import get_family_repo
from app.models.family.repository import FamilyRepository
from app.models.user_access.repository import UserAccessRepository
from app.schemas.errors import ErrorCode
from app.schemas.auth import (
    ChangePasswordRequest,
    MeResponse,
    SessionCreateRequest,
    SessionCreateResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"], route_class=NoStoreRoute)


@router.post(
    "/session",
    status_code=201,
    response_model=SessionCreateResponse,
    dependencies=[Depends(rate_limited("session"))],
    responses=error_responses(
        ErrorCode.INVALID_ID_TOKEN,
        ErrorCode.ACCOUNT_BLOCKED,
        ErrorCode.TEMPORARY_PASSWORD_EXPIRED,
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.RATE_LIMITED,
        ErrorCode.PROVIDER_UNAVAILABLE,
        *BASE,
    ),
)
async def create_session(
    body: SessionCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    users: UserAccessRepository = Depends(get_user_access_repo),
    provider: IdentityProvider = Depends(get_identity_provider),
) -> SessionCreateResponse:
    return await use_cases.create_session(
        db=db,
        users=users,
        provider=provider,
        id_token=body.id_token.get_secret_value(),
        client=ClientInfo.from_request(request),
    )


from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
from sqlalchemy import select
from app.core.config import settings
from app.core.errors import AppError
from app.core.security.tokens import generate_session_token, hash_session_token
from app.models.user_access.entities import User
from app.schemas.auth import SessionUser


class DevSessionRequest(BaseModel):
    email: str = "dev-sa@example.test"


@router.post(
    "/dev-session",
    status_code=201,
    response_model=SessionCreateResponse,
)
async def dev_session(
    body: DevSessionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    users: UserAccessRepository = Depends(get_user_access_repo),
) -> SessionCreateResponse:
    if not settings.DEBUG:
        raise AppError(ErrorCode.FORBIDDEN)

    target_email = body.email.strip().lower()
    user_map = {
        "thangvo": "thangvo250904@gmail.com",
        "phuchau": "maiphuchau144@gmail.com",
        "giahuy": "huy13052005@gmail.com",
        "minhquan": "quankophaiwibu@gmail.com",
    }
    if target_email in user_map:
        target_email = user_map[target_email]

    stmt = select(User).where((User.email == target_email) | (User.username == target_email))
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if not user:
        raise AppError(ErrorCode.ACCOUNT_BLOCKED)

    now = datetime.now(timezone.utc)
    token = generate_session_token()
    expires_at = now + timedelta(hours=settings.SESSION_TTL_HOURS)
    client = ClientInfo.from_request(request)

    await users.add_session(
        user_id=user.user_id,
        token_jti_hash=hash_session_token(token),
        created_at=now,
        expires_at=expires_at,
        ip_address=client.ip_address,
        user_agent=client.user_agent,
    )
    user.last_login_at = now
    await users.add_login_history(
        user_id=user.user_id,
        identifier=user.email,
        success=True,
        failure_reason=None,
        ip_address=client.ip_address,
        user_agent=client.user_agent,
        occurred_at=now,
    )
    await db.commit()

    return SessionCreateResponse(
        access_token=token,
        expires_at=expires_at,
        user=SessionUser(
            user_id=user.user_id,
            display_name=user.display_name,
            email=user.email,
            status=user.status,
        ),
        requires_password_change=False,
    )


# The three routes below are the ONLY ones using get_principal_allow_restricted.


@router.get(
    "/me", response_model=MeResponse, responses=error_responses(*AUTHENTICATED_RESTRICTED_OK)
)
async def me(
    principal: Principal = Depends(get_principal_allow_restricted),
    users: UserAccessRepository = Depends(get_user_access_repo),
    family: FamilyRepository = Depends(get_family_repo),
) -> MeResponse:
    return await use_cases.get_me(users=users, family=family, principal=principal)


@router.post(
    "/logout",
    status_code=204,
    response_class=Response,
    responses=error_responses(*AUTHENTICATED_RESTRICTED_OK),
)
async def logout(
    principal: Principal = Depends(get_principal_allow_restricted),
    db: AsyncSession = Depends(get_db),
    users: UserAccessRepository = Depends(get_user_access_repo),
) -> Response:
    await use_cases.logout(db=db, users=users, principal=principal)
    return Response(status_code=204)


@router.post(
    "/change-password",
    status_code=204,
    response_class=Response,
    responses=error_responses(
        *AUTHENTICATED_RESTRICTED_OK,
        ErrorCode.RECENT_LOGIN_REQUIRED,
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.PROVIDER_UNAVAILABLE,
    ),
)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    principal: Principal = Depends(get_principal_allow_restricted),
    db: AsyncSession = Depends(get_db),
    users: UserAccessRepository = Depends(get_user_access_repo),
    provider: IdentityProvider = Depends(get_identity_provider),
) -> Response:
    await use_cases.change_password(
        db=db,
        users=users,
        provider=provider,
        principal=principal,
        new_password=body.new_password.get_secret_value(),
        recent_id_token=body.recent_id_token.get_secret_value(),
        client=ClientInfo.from_request(request),
    )
    return Response(status_code=204)


import uuid
from fastapi import HTTPException
from app.core.utils.otp_service import generate_otp, verify_otp, is_email_verified, send_otp_via_email


class RegisterSendOtpRequest(BaseModel):
    email: str


class RegisterVerifyOtpRequest(BaseModel):
    email: str
    otp: str


class RegisterPublicRequest(BaseModel):
    email: str
    password: str
    display_name: str
    username: str | None = None
    phone: str | None = None
    otp: str | None = None


@router.post(
    "/register-send-otp",
    status_code=200,
)
async def register_send_otp(
    body: RegisterSendOtpRequest,
    users: UserAccessRepository = Depends(get_user_access_repo),
):
    email = body.email.strip().lower()
    if not (email.endswith("@gmail.com") or email.endswith("@example.test") or email.endswith(".test")):
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": "Email bắt buộc phải là địa chỉ Gmail có đuôi @gmail.com"}
        )
    existing = await users.get_user_by_email_ci(email)
    if existing:
        raise HTTPException(
            status_code=409,
            detail={"code": "EMAIL_ALREADY_EXISTS", "message": "Địa chỉ Gmail này đã được sử dụng để đăng ký tài khoản."}
        )
    otp = generate_otp(email)
    send_otp_via_email(email, otp)
    return {"message": "Mã xác thực 6 số đã được gửi tới Gmail của bạn. Vui lòng kiểm tra hộp thư."}


@router.post(
    "/register-verify-otp",
    status_code=200,
)
async def register_verify_otp(body: RegisterVerifyOtpRequest):
    email = body.email.strip().lower()
    if not (email.endswith("@gmail.com") or email.endswith("@example.test") or email.endswith(".test")):
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": "Email bắt buộc phải là địa chỉ Gmail có đuôi @gmail.com"}
        )
    success = verify_otp(email, body.otp)
    if not success:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_OTP", "message": "Mã xác thực OTP không đúng hoặc đã hết hạn."}
        )
    return {"message": "Xác thực Gmail thành công."}


@router.post(
    "/register-public",
    status_code=201,
    response_model=SessionCreateResponse,
)
async def register_public(
    body: RegisterPublicRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    users: UserAccessRepository = Depends(get_user_access_repo),
    provider: IdentityProvider = Depends(get_identity_provider),
) -> SessionCreateResponse:
    email = body.email.strip().lower()
    if not (email.endswith("@gmail.com") or email.endswith("@example.test") or email.endswith(".test")):
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": "Email bắt buộc phải là địa chỉ Gmail có đuôi @gmail.com"}
        )
    # Check OTP verification
    if not is_email_verified(email):
        if not body.otp or not verify_otp(email, body.otp):
            raise HTTPException(
                status_code=400,
                detail={"code": "EMAIL_NOT_VERIFIED", "message": "Địa chỉ Gmail chưa được xác thực bằng mã OTP."}
            )

    # Check unique email
    existing = await users.get_user_by_email_ci(email)
    if existing:
        raise HTTPException(
            status_code=409,
            detail={"code": "EMAIL_ALREADY_EXISTS", "message": "Địa chỉ Gmail này đã được sử dụng."}
        )

    now = datetime.now(timezone.utc)
    user_id = uuid.uuid4()
    firebase_uid = f"usr_{uuid.uuid4().hex[:16]}"

    # Try creating user in identity provider if available
    try:
        provider_user = await provider.create_user(
            uid=firebase_uid,
            email=email,
            display_name=body.display_name,
            password=body.password,
        )
        if provider_user and hasattr(provider_user, "uid") and provider_user.uid:
            firebase_uid = provider_user.uid
    except Exception:
        pass

    # Create user in PostgreSQL
    user = await users.create_user_account(
        user_id=user_id,
        firebase_uid=firebase_uid,
        email=body.email.strip(),
        display_name=body.display_name.strip(),
        phone=body.phone,
        status="ACTIVE",
        first_login_required=False,
        now=now,
    )
    user.email_verified = True
    if body.username:
        user.username = body.username.strip()

    cred = await users.add_credential_metadata(user_id, now=now)
    cred.must_change_password = False

    # Issue session token
    token = generate_session_token()
    expires_at = now + timedelta(hours=settings.SESSION_TTL_HOURS)
    client = ClientInfo.from_request(request)

    await users.add_session(
        user_id=user.user_id,
        token_jti_hash=hash_session_token(token),
        created_at=now,
        expires_at=expires_at,
        ip_address=client.ip_address,
        user_agent=client.user_agent,
    )
    user.last_login_at = now
    await users.add_login_history(
        user_id=user.user_id,
        identifier=user.email,
        success=True,
        failure_reason=None,
        ip_address=client.ip_address,
        user_agent=client.user_agent,
        occurred_at=now,
    )
    await db.commit()

    return SessionCreateResponse(
        access_token=token,
        expires_at=expires_at,
        user=SessionUser(
            user_id=user.user_id,
            display_name=user.display_name,
            email=user.email,
            status=user.status,
        ),
        requires_password_change=False,
    )

