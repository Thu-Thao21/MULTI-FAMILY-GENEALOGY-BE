"""Public (Guest) routes of Business registration (api_contract.md section 4). Mounted under
/api/v1. No authentication: a Bearer header, if sent, is ignored.

The two POST routes run the rate limiter as a dependency, which FastAPI solves before it
validates the body, so an invalid body still counts against the caller. (A body that is not
valid JSON is rejected earlier, before any dependency runs.)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.controllers.auth_access.use_cases import ClientInfo
from app.controllers.family_management import public_use_cases as use_cases
from app.core.utils.openapi_responses import BASE, error_responses
from app.core.middleware.rate_limit import rate_limited
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


@router.get("/public/families")
@router.get("/families")
async def search_public_families(
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db=Depends(get_db),
):
    from app.repositories.family_repository import FamilyRepository as RealFamilyRepo
    repo = RealFamilyRepo(db)
    families = await repo.search_public_families(search=search, limit=limit, offset=offset)
    return [
        {
            "id": str(f.clan_id),
            "name": f.name,
            "clan_code": f.clan_code,
            "status": f.status,
            "activated_at": f.activated_at,
        }
        for f in families
    ]


class SendOtpRequest(BaseModel):
    email: str


class VerifyOtpRequest(BaseModel):
    email: str
    otp: str


@router.post("/business-registrations/send-otp")
async def send_registration_otp(data: SendOtpRequest):
    """Sends a 6-digit OTP to the user's real Gmail address."""
    clean_email = data.email.strip().lower()
    if not (clean_email.endswith("@gmail.com") or clean_email.endswith("@example.test")):
        raise HTTPException(
            status_code=400,
            detail="Email bắt buộc phải là địa chỉ Gmail có đuôi @gmail.com",
        )

    from app.core.utils.otp_service import generate_otp, send_otp_via_email
    otp_code = generate_otp(clean_email)
    send_otp_via_email(clean_email, otp_code)

    return {
        "success": True,
        "message": f"Mã xác thực 6 số đã được gửi tới địa chỉ {clean_email}. Vui lòng kiểm tra hòm thư.",
    }


@router.post("/business-registrations/verify-otp")
async def verify_registration_otp(data: VerifyOtpRequest):
    """Verifies the 6-digit OTP sent to the user's Gmail."""
    from app.core.utils.otp_service import verify_otp
    is_valid = verify_otp(data.email, data.otp)
    if not is_valid:
        raise HTTPException(
            status_code=400,
            detail="Mã OTP không chính xác hoặc đã hết hạn (hiệu lực 5 phút).",
        )

    return {
        "verified": True,
        "message": "Xác thực địa chỉ Gmail thành công!",
    }

