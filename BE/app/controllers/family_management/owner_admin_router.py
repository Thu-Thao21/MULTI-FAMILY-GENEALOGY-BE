"""System Admin routes for the Owner of a clan (api_contract.md section 4, Mốc E6a). Mounted under
/api/v1. System Admin only: anyone else gets 403 (authorization runs before the path, header or body
is validated). NOT rate limited: authenticated administrator endpoints.

POST /admin/clans/{clan_id}/owner answers with a TEMPORARY PASSWORD: it is shown once, in this
response only, and every response of these routes is `Cache-Control: no-store`.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers.auth_access.use_cases import ClientInfo
from app.controllers.family_management import owner_provisioning_use_cases as use_cases
from app.core.email_sender import EmailSender, get_email_sender
from app.core.firebase import IdentityProvider, get_identity_provider
from app.core.idempotency import IDEMPOTENCY_REPLAYED_HEADER, idempotency_key_header
from app.core.openapi_responses import AUTHENTICATED, error_responses
from app.db.postgres import get_db
from app.dependencies.auth import Principal, get_user_access_repo
from app.dependencies.permissions import (
    Action,
    get_family_repo,
    get_idempotency_repo,
    get_provisioning_repo,
    require_action,
)
from app.models.family.idempotency_repository import IdempotencyRepository
from app.models.family.provisioning_repository import ProvisioningRepository
from app.models.family.repository import FamilyRepository
from app.models.user_access.repository import UserAccessRepository
from app.schemas.business import OwnerProvisionRequest, OwnerProvisionResponse, ProvisioningJobResponse
from app.schemas.errors import ErrorCode

router = APIRouter(tags=["owner-admin"])

NO_STORE = "no-store"


@router.post(
    "/admin/clans/{clan_id}/owner",
    status_code=201,
    response_model=OwnerProvisionResponse,
    responses=error_responses(
        *AUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.NOT_FOUND,
        ErrorCode.STATE_CONFLICT,
        ErrorCode.DUPLICATE_RESOURCE,
        ErrorCode.IDEMPOTENCY_KEY_CONFLICT,
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.PROVIDER_UNAVAILABLE,
    ),
)
async def provision_owner(
    clan_id: uuid.UUID,
    request: Request,
    body: Optional[OwnerProvisionRequest] = None,
    principal: Principal = Depends(require_action(Action.CLAN_OWNER_PROVISION)),
    key: str = Depends(idempotency_key_header),
    db: AsyncSession = Depends(get_db),
    users: UserAccessRepository = Depends(get_user_access_repo),
    family: FamilyRepository = Depends(get_family_repo),
    jobs: ProvisioningRepository = Depends(get_provisioning_repo),
    idempotency: IdempotencyRepository = Depends(get_idempotency_repo),
    provider: IdentityProvider = Depends(get_identity_provider),
    sender: EmailSender = Depends(get_email_sender),
) -> JSONResponse:
    """Create the Owner account of a PENDING clan through Firebase.

    Idempotency-Key is required. The Owner's e-mail, name and phone default to the representative of
    the Business registration; the body may override them. The 201 carries the TEMPORARY PASSWORD,
    shown once and valid for 72 hours; the Owner must change it at the first login. A replay of the
    same key answers with the same job and a null password. A failure leaves a job that can be retried.
    """
    result = await use_cases.provision_owner(
        db=db,
        users=users,
        family=family,
        jobs=jobs,
        idempotency=idempotency,
        provider=provider,
        sender=sender,
        principal=principal,
        clan_id=clan_id,
        body=body or OwnerProvisionRequest(),
        key=key,
        client=ClientInfo.from_request(request),
    )
    headers = {"Cache-Control": NO_STORE}
    if result.replayed:
        headers[IDEMPOTENCY_REPLAYED_HEADER] = "true"
    return JSONResponse(
        status_code=result.status, content=result.response.model_dump(mode="json"), headers=headers
    )


@router.get(
    "/admin/provisioning-jobs/{job_id}",
    response_model=ProvisioningJobResponse,
    dependencies=[Depends(require_action(Action.PROVISIONING_JOB_READ))],
    responses=error_responses(
        *AUTHENTICATED, ErrorCode.FORBIDDEN, ErrorCode.NOT_FOUND, ErrorCode.VALIDATION_ERROR
    ),
)
async def get_provisioning_job(
    job_id: uuid.UUID,
    response: Response,
    jobs: ProvisioningRepository = Depends(get_provisioning_repo),
) -> ProvisioningJobResponse:
    """A job's state. Never the e-mail, the phone, the Firebase uid or a password."""
    response.headers["Cache-Control"] = NO_STORE
    return await use_cases.get_job(jobs=jobs, job_id=job_id)
