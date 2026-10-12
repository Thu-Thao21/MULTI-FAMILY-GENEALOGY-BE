from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers.genealogy import GenealogyController
from app.db.postgres import get_db
from app.dependencies.auth import get_current_account
from app.models.postgres import Account
from app.schemas.genealogy import (
    AncestorDescendantResponse,
    PersonCreate,
    PersonResponse,
    PersonUpdate,
    RelationshipCreate,
    RelationshipResponse,
    TreeDataResponse,
)


router = APIRouter(prefix="/api/v1/families/{family_id}", tags=["genealogy"])


def controller(db: AsyncSession, account: Account) -> GenealogyController:
    return GenealogyController(db, account)


@router.get("/persons", response_model=list[PersonResponse])
async def search_persons(
    family_id: str,
    search: Optional[str] = Query(None),
    gender: Optional[str] = Query(None),
    branch_id: Optional[str] = Query(None, alias="branchId"),
    is_living: Optional[bool] = Query(None, alias="isLiving"),
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    return await controller(db, account).search_persons(
        family_id, search, gender, branch_id, is_living, limit, offset
    )


@router.post(
    "/persons", response_model=PersonResponse, status_code=status.HTTP_201_CREATED
)
async def create_person(
    family_id: str,
    data: PersonCreate,
    db: AsyncSession = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    return await controller(db, account).create_person(family_id, data)


@router.get("/persons/{person_id}", response_model=PersonResponse)
async def get_person(
    family_id: str,
    person_id: str,
    db: AsyncSession = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    return await controller(db, account).get_person(family_id, person_id)


@router.patch("/persons/{person_id}", response_model=PersonResponse)
async def update_person(
    family_id: str,
    person_id: str,
    data: PersonUpdate,
    db: AsyncSession = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    return await controller(db, account).update_person(family_id, person_id, data)


@router.post(
    "/relationships",
    response_model=RelationshipResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_relationship(
    family_id: str,
    data: RelationshipCreate,
    db: AsyncSession = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    return await controller(db, account).create_relationship(family_id, data)


@router.delete("/relationships/{relationship_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_relationship(
    family_id: str,
    relationship_id: str,
    db: AsyncSession = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    await controller(db, account).delete_relationship(family_id, relationship_id)


@router.get(
    "/persons/{person_id}/ancestors",
    response_model=list[AncestorDescendantResponse],
)
async def get_ancestors(
    family_id: str,
    person_id: str,
    db: AsyncSession = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    return await controller(db, account).get_ancestors(family_id, person_id)


@router.get(
    "/persons/{person_id}/descendants",
    response_model=list[AncestorDescendantResponse],
)
async def get_descendants(
    family_id: str,
    person_id: str,
    db: AsyncSession = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    return await controller(db, account).get_descendants(family_id, person_id)


@router.get("/tree-data", response_model=TreeDataResponse)
async def get_tree_data(
    family_id: str,
    db: AsyncSession = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    return await controller(db, account).get_tree_data(family_id)
