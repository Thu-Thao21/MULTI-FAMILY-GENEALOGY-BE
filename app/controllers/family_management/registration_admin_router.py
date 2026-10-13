"""System Admin routes for Business registrations (api_contract.md section 4). Mounted under
/api/v1. System Admin only: anyone else gets 403 (authorization runs before the path, query,
header or body is validated). NOT rate limited: these are authenticated administrator endpoints.

Every response may hold personal data of an applicant, so it is `Cache-Control: no-store`.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers.auth_access.use_cases import ClientInfo
from app.controllers.family_management import business_admin_use_cases
from app.controllers.family_management import registration_admin_use_cases as use_cases
from app.core.idempotency import (
    IDEMPOTENCY_REPLAYED_HEADER,
    idempotency_key_header,
)
from app.core.openapi_responses import AUTHENTICATED, error_responses
from app.db.postgres import get_db
from app.dependencies.auth import Principal, get_user_access_repo
from app.dependencies.permissions import Action, get_family_repo, get_idempotency_repo, require_action
from app.models.family.idempotency_repository import IdempotencyRepository
from app.models.family.repository import FamilyRepository
from app.models.user_access.repository import UserAccessRepository
from app.schemas.business import (
    BusinessCreateRequest,
    BusinessCreateResponse,
    BusinessRegistrationDetail,
    BusinessRegistrationListQuery,
    BusinessRegistrationSummary,
    RegistrationReviewRequest,
    RegistrationReviewResponse,
)
from app.schemas.common import Page
from app.schemas.errors import ErrorCode

router = APIRouter(tags=["registration-admin"])

NO_STORE = "no-store"


@router.get(
    "/admin/business-registrations",
    response_model=Page[BusinessRegistrationSummary],
    dependencies=[Depends(require_action(Action.REGISTRATION_LIST))],
    responses=error_responses(*AUTHENTICATED, ErrorCode.FORBIDDEN, ErrorCode.VALIDATION_ERROR),
)
async def list_registrations(
    response: Response,
    query: BusinessRegistrationListQuery = Depends(),
    family: FamilyRepository = Depends(get_family_repo),
) -> Page[BusinessRegistrationSummary]:
    response.headers["Cache-Control"] = NO_STORE
    return await use_cases.list_registrations(family=family, query=query)


@router.get(
    "/admin/business-registrations/{registration_id}",
    response_model=BusinessRegistrationDetail,
    dependencies=[Depends(require_action(Action.REGISTRATION_READ))],
    responses=error_responses(
        *AUTHENTICATED, ErrorCode.FORBIDDEN, ErrorCode.NOT_FOUND, ErrorCode.VALIDATION_ERROR
    ),
)
async def get_registration(
    registration_id: uuid.UUID,
    response: Response,
    family: FamilyRepository = Depends(get_family_repo),
) -> BusinessRegistrationDetail:
    response.headers["Cache-Control"] = NO_STORE
    return await use_cases.get_registration_detail(family=family, registration_id=registration_id)


@router.post(
    "/admin/business-registrations/{registration_id}/review",
    response_model=RegistrationReviewResponse,
    responses=error_responses(
        *AUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.NOT_FOUND,
        ErrorCode.STATE_CONFLICT,
        ErrorCode.VALIDATION_ERROR,
    ),
)
async def review_registration(
    registration_id: uuid.UUID,
    body: RegistrationReviewRequest,
    request: Request,
    response: Response,
    principal: Principal = Depends(require_action(Action.REGISTRATION_REVIEW)),
    db: AsyncSession = Depends(get_db),
    users: UserAccessRepository = Depends(get_user_access_repo),
    family: FamilyRepository = Depends(get_family_repo),
) -> RegistrationReviewResponse:
    """Approve or reject a PENDING registration.

    A rejection reason is shown to the applicant (tracking, public_reason); an approval note is
    internal. The response says which one it was (reason_visible_to_applicant).
    """
    response.headers["Cache-Control"] = NO_STORE
    return await use_cases.review_registration(
        db=db,
        users=users,
        family=family,
        principal=principal,
        registration_id=registration_id,
        body=body,
        client=ClientInfo.from_request(request),
    )


@router.post(
    "/admin/business-registrations/{registration_id}/business",
    status_code=201,
    response_model=BusinessCreateResponse,
    responses=error_responses(
        *AUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.NOT_FOUND,
        ErrorCode.STATE_CONFLICT,
        ErrorCode.DUPLICATE_RESOURCE,
        ErrorCode.IDEMPOTENCY_KEY_CONFLICT,
        ErrorCode.VALIDATION_ERROR,
    ),
)
async def create_business(
    registration_id: uuid.UUID,
    request: Request,
    body: Optional[BusinessCreateRequest] = None,
    principal: Principal = Depends(require_action(Action.BUSINESS_CREATE)),
    key: str = Depends(idempotency_key_header),
    db: AsyncSession = Depends(get_db),
    users: UserAccessRepository = Depends(get_user_access_repo),
    family: FamilyRepository = Depends(get_family_repo),
    idempotency: IdempotencyRepository = Depends(get_idempotency_repo),
) -> JSONResponse:
    """Create the PENDING Business (clan, profile, subscription) of an APPROVED registration.

    The Idempotency-Key header is required. The same key with the same request replays the first
    201 (header Idempotency-Replayed: true); the same key with a different request is 409
    IDEMPOTENCY_KEY_CONFLICT. The plan comes from the registration, never from the request.
    """
    result = await business_admin_use_cases.create_business(
        db=db,
        users=users,
        family=family,
        idempotency=idempotency,
        principal=principal,
        registration_id=registration_id,
        body=body or BusinessCreateRequest(),
        key=key,
        client=ClientInfo.from_request(request),
    )
    headers = {"Cache-Control": NO_STORE}
    if result.replayed:
        headers[IDEMPOTENCY_REPLAYED_HEADER] = "true"
    return JSONResponse(status_code=result.status, content=result.body, headers=headers)
