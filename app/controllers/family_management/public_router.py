"""Public (Guest) routes of Business registration (api_contract.md section 4). Mounted under
/api/v1. No authentication: a Bearer header, if sent, is ignored.

The two POST routes run the rate limiter as a dependency, which FastAPI solves before it
validates the body, so an invalid body still counts against the caller. (A body that is not
valid JSON is rejected earlier, before any dependency runs.)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from app.controllers.auth_access.use_cases import ClientInfo
from app.controllers.family_management import public_use_cases as use_cases
from app.core.openapi_responses import BASE, error_responses
from app.core.rate_limit import rate_limited
from app.db.postgres import get_db
from app.dependencies.auth import get_user_access_repo
from app.dependencies.permissions import get_family_repo
from app.models.family.repository import FamilyRepository
from app.models.user_access.repository import UserAccessRepository
from app.schemas.business import (
    BusinessRegistrationCreateRequest,
    BusinessRegistrationCreateResponse,
    BusinessRegistrationTrackRequest,
    BusinessRegistrationTrackResponse,
    ServicePlanResponse,
)
from app.schemas.common import Page, PageParams
from app.schemas.errors import ErrorCode

router = APIRouter(tags=["public-business"])

NO_STORE = "no-store"


@router.get(
    "/service-plans",
    response_model=Page[ServicePlanResponse],
    responses=error_responses(ErrorCode.VALIDATION_ERROR, *BASE),
)
async def list_service_plans(
    query: PageParams = Depends(),
    family: FamilyRepository = Depends(get_family_repo),
) -> Page[ServicePlanResponse]:
    return await use_cases.list_service_plans(family=family, query=query)


@router.post(
    "/business-registrations",
    status_code=201,
    response_model=BusinessRegistrationCreateResponse,
    dependencies=[Depends(rate_limited("registration"))],
    responses=error_responses(
        ErrorCode.DUPLICATE_RESOURCE, ErrorCode.VALIDATION_ERROR, ErrorCode.RATE_LIMITED, *BASE
    ),
)
async def create_registration(
    body: BusinessRegistrationCreateRequest,
    request: Request,
    response: Response,
    db=Depends(get_db),
    users: UserAccessRepository = Depends(get_user_access_repo),
    family: FamilyRepository = Depends(get_family_repo),
) -> BusinessRegistrationCreateResponse:
    response.headers["Cache-Control"] = NO_STORE  # the body holds the tracking code
    return await use_cases.create_registration(
        db=db, users=users, family=family, body=body, client=ClientInfo.from_request(request)
    )


@router.post(
    "/business-registrations/track",
    response_model=BusinessRegistrationTrackResponse,
    dependencies=[Depends(rate_limited("track"))],
    responses=error_responses(
        ErrorCode.NOT_FOUND, ErrorCode.VALIDATION_ERROR, ErrorCode.RATE_LIMITED, *BASE
    ),
)
async def track_registration(
    body: BusinessRegistrationTrackRequest,
    response: Response,
    family: FamilyRepository = Depends(get_family_repo),
) -> BusinessRegistrationTrackResponse:
    response.headers["Cache-Control"] = NO_STORE
    return await use_cases.track_registration(family=family, body=body)
