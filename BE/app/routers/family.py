from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers.family_controller import FamilyController
from app.db.postgres import get_db
from app.dependencies.auth import get_current_account
from app.models.postgres import Account
from app.schemas.family import (
    BranchCreate,
    BranchResponse,
    BranchUpdate,
    FamilyResponse,
    FamilyUpdate,
)


router = APIRouter(prefix="/api/v1/families", tags=["family"])


def controller(db: AsyncSession, account: Account) -> FamilyController:
    return FamilyController(db, account)


@router.get("/{family_id}", response_model=FamilyResponse)
async def get_family(
    family_id: str,
    db: AsyncSession = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    return await controller(db, account).get_family(family_id)


@router.patch("/{family_id}", response_model=FamilyResponse)
async def update_family(
    family_id: str,
    data: FamilyUpdate,
    db: AsyncSession = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    return await controller(db, account).update_family(family_id, data)


@router.get("/{family_id}/branches", response_model=list[BranchResponse])
async def get_branches(
    family_id: str,
    db: AsyncSession = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    return await controller(db, account).get_branches(family_id)


@router.post(
    "/{family_id}/branches",
    response_model=BranchResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_branch(
    family_id: str,
    data: BranchCreate,
    db: AsyncSession = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    return await controller(db, account).create_branch(family_id, data)


@router.patch("/{family_id}/branches/{branch_id}", response_model=BranchResponse)
async def update_branch(
    family_id: str,
    branch_id: str,
    data: BranchUpdate,
    db: AsyncSession = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    return await controller(db, account).update_branch(family_id, branch_id, data)
