"""System Admin routes on a clan (api_contract.md section 4, Mốc E7). Mounted under /api/v1. System Admin
only: anyone else gets 403 (authorization runs before the path is validated). NOT rate limited.

POST /admin/clans/{clan_id}/activate  PENDING -> ACTIVE, the SA's manual confirmation (D03).
GET  /admin/clans/{clan_id}           read only; no e-mail, name, phone or Firebase uid.
Both answer `Cache-Control: no-store`."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers.auth_access.use_cases import ClientInfo
from app.controllers.family_management import clan_admin_use_cases as use_cases
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
from app.schemas.business import ClanActivateResponse, ClanDetailResponse
from app.schemas.errors import ErrorCode

router = APIRouter(tags=["clan-admin"])

NO_STORE = "no-store"


@router.post(
    "/admin/clans/{clan_id}/activate",
    response_model=ClanActivateResponse,
    responses=error_responses(
        *AUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.NOT_FOUND,
        ErrorCode.STATE_CONFLICT,
        ErrorCode.VALIDATION_ERROR,
    ),
)
async def activate_clan(
    clan_id: uuid.UUID,
    request: Request,
    response: Response,
    principal: Principal = Depends(require_action(Action.CLAN_ACTIVATE)),
    db: AsyncSession = Depends(get_db),
    users: UserAccessRepository = Depends(get_user_access_repo),
    family: FamilyRepository = Depends(get_family_repo),
    idempotency: IdempotencyRepository = Depends(get_idempotency_repo),
) -> ClanActivateResponse:
    """Activate a PENDING clan: the clan and its PENDING subscription become ACTIVE, the subscription
    starts now. No Idempotency-Key and no body. A 409 saying the clan is ACTIVE after a lost response
    means the first call succeeded."""
    response.headers["Cache-Control"] = NO_STORE
    return await use_cases.activate_clan(
        db=db, users=users, family=family, idempotency=idempotency, principal=principal,
        clan_id=clan_id, client=ClientInfo.from_request(request),
    )


@router.get(
    "/admin/clans/{clan_id}",
    response_model=ClanDetailResponse,
    dependencies=[Depends(require_action(Action.CLAN_READ))],
    responses=error_responses(
        *AUTHENTICATED, ErrorCode.FORBIDDEN, ErrorCode.NOT_FOUND, ErrorCode.VALIDATION_ERROR
    ),
)
async def get_clan(
    clan_id: uuid.UUID,
    response: Response,
    family: FamilyRepository = Depends(get_family_repo),
    jobs: ProvisioningRepository = Depends(get_provisioning_repo),
) -> ClanDetailResponse:
    """A clan as the SA needs it: status, dates, registration id, a summary of its subscription, the
    Owner's user id and the latest Owner job. Never an e-mail, a name, a phone or a Firebase uid."""
    response.headers["Cache-Control"] = NO_STORE
    return await use_cases.get_clan(family=family, jobs=jobs, clan_id=clan_id)
