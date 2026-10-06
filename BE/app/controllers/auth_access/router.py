"""Auth routes (api_contract.md section 3). Mounted under /api/v1."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers.auth_access import use_cases
from app.controllers.auth_access.use_cases import ClientInfo
from app.core.firebase import IdentityProvider, get_identity_provider
from app.core.openapi_responses import (
    AUTHENTICATED_RESTRICTED_OK,
    BASE,
    error_responses,
)
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

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/session",
    status_code=201,
    response_model=SessionCreateResponse,
    responses=error_responses(
        ErrorCode.INVALID_ID_TOKEN,
        ErrorCode.ACCOUNT_BLOCKED,
        ErrorCode.TEMPORARY_PASSWORD_EXPIRED,
        ErrorCode.VALIDATION_ERROR,
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
