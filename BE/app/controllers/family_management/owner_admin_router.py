"""System Admin routes for the Owner of a clan (api_contract.md section 4, Mốc E6a). Mounted under
/api/v1. System Admin only: anyone else gets 403 (authorization runs before the path, header or body
is validated). NOT rate limited: authenticated administrator endpoints.

POST /admin/clans/{clan_id}/owner answers with a TEMPORARY PASSWORD: it is shown once, in this
response only, and every response of these routes is `Cache-Control: no-store`. So do the retry of a job
(POST /admin/provisioning-jobs/{id}/retry) and the reissue of the Owner's temporary password
(POST /admin/clans/{id}/owner/temporary-password) (Mốc E6b). The job list and the abandon route never
carry a password, an e-mail or a phone.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers.auth_access.use_cases import ClientInfo
from app.controllers.family_management import owner_password_reset_use_cases as reset_use_cases
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
from app.schemas.business import (
    OwnerPasswordResetResponse,
    OwnerProvisionRequest,
    OwnerProvisionResponse,
    ProvisioningJobListQuery,
    ProvisioningJobResponse,
)
from app.schemas.common import Page
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


@router.get(
    "/admin/provisioning-jobs",
    response_model=Page[ProvisioningJobResponse],
    dependencies=[Depends(require_action(Action.PROVISIONING_JOB_READ))],
    responses=error_responses(*AUTHENTICATED, ErrorCode.FORBIDDEN, ErrorCode.VALIDATION_ERROR),
)
async def list_provisioning_jobs(
    response: Response,
    query: ProvisioningJobListQuery = Depends(),
    jobs: ProvisioningRepository = Depends(get_provisioning_repo),
) -> Page[ProvisioningJobResponse]:
    """Jobs, newest first, filtered by clan_id and status (page_size at most 100). Never the e-mail,
    the phone, the Firebase uid or a password."""
    response.headers["Cache-Control"] = NO_STORE
    return await use_cases.list_jobs(jobs=jobs, query=query)


@router.post(
    "/admin/provisioning-jobs/{job_id}/retry",
    response_model=OwnerProvisionResponse,
    responses=error_responses(
        *AUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.NOT_FOUND,
        ErrorCode.STATE_CONFLICT,
        ErrorCode.DUPLICATE_RESOURCE,
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.PROVIDER_UNAVAILABLE,
    ),
)
async def retry_provisioning_job(
    job_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_action(Action.CLAN_OWNER_PROVISION)),
    db: AsyncSession = Depends(get_db),
    users: UserAccessRepository = Depends(get_user_access_repo),
    family: FamilyRepository = Depends(get_family_repo),
    jobs: ProvisioningRepository = Depends(get_provisioning_repo),
    idempotency: IdempotencyRepository = Depends(get_idempotency_repo),
    provider: IdentityProvider = Depends(get_identity_provider),
    sender: EmailSender = Depends(get_email_sender),
) -> JSONResponse:
    """Run a job again: FAILED_RETRYABLE, a PENDING that nobody started, a RUNNING whose lease ran out, or
    (clean-up only, no password) a FAILED job that still owes the Firebase clean-up. Every success that
    creates the Owner makes a NEW temporary password, shown once. Any other state is 409 naming it."""
    result = await use_cases.retry_job(
        db=db, users=users, family=family, jobs=jobs, idempotency=idempotency, provider=provider,
        sender=sender, principal=principal, job_id=job_id, client=ClientInfo.from_request(request),
    )
    return JSONResponse(
        status_code=result.status, content=result.response.model_dump(mode="json"),
        headers={"Cache-Control": NO_STORE},
    )


@router.post(
    "/admin/provisioning-jobs/{job_id}/abandon",
    response_model=ProvisioningJobResponse,
    responses=error_responses(
        *AUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.NOT_FOUND,
        ErrorCode.STATE_CONFLICT,
        ErrorCode.VALIDATION_ERROR,
    ),
)
async def abandon_provisioning_job(
    job_id: uuid.UUID,
    request: Request,
    response: Response,
    principal: Principal = Depends(require_action(Action.CLAN_OWNER_PROVISION)),
    db: AsyncSession = Depends(get_db),
    users: UserAccessRepository = Depends(get_user_access_repo),
    jobs: ProvisioningRepository = Depends(get_provisioning_repo),
    idempotency: IdempotencyRepository = Depends(get_idempotency_repo),
    provider: IdentityProvider = Depends(get_identity_provider),
) -> ProvisioningJobResponse:
    """Give a job up: FAILED_RETRYABLE, a stuck PENDING or a RUNNING whose lease ran out. The Firebase
    user own-<job_id> is deleted when a run ever started; if that fails, needs_cleanup stays true."""
    response.headers["Cache-Control"] = NO_STORE
    return await use_cases.abandon_job(
        db=db, users=users, jobs=jobs, idempotency=idempotency, provider=provider, principal=principal,
        job_id=job_id, client=ClientInfo.from_request(request),
    )


@router.post(
    "/admin/clans/{clan_id}/owner/temporary-password",
    response_model=OwnerPasswordResetResponse,
    responses=error_responses(
        *AUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.NOT_FOUND,
        ErrorCode.STATE_CONFLICT,
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.PROVIDER_UNAVAILABLE,
    ),
)
async def reissue_owner_temporary_password(
    clan_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_action(Action.CLAN_OWNER_TEMP_PASSWORD_RESET)),
    db: AsyncSession = Depends(get_db),
    users: UserAccessRepository = Depends(get_user_access_repo),
    family: FamilyRepository = Depends(get_family_repo),
    idempotency: IdempotencyRepository = Depends(get_idempotency_repo),
    provider: IdentityProvider = Depends(get_identity_provider),
    sender: EmailSender = Depends(get_email_sender),
) -> JSONResponse:
    """A new temporary password (valid 72 hours, shown once) for the Owner of a clan, only while the Owner
    has not yet chosen their own password. All the Owner's sessions are revoked. 409 for an Owner who is
    ACTIVE, LOCKED or DISABLED."""
    result = await reset_use_cases.reset_owner_password(
        db=db, users=users, family=family, idempotency=idempotency, provider=provider, sender=sender,
        principal=principal, clan_id=clan_id, client=ClientInfo.from_request(request),
    )
    return JSONResponse(
        status_code=200, content=result.model_dump(mode="json"), headers={"Cache-Control": NO_STORE}
    )
