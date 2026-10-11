from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

class FamilyResponse(BaseModel):
    id: str
    clan_code: str = Field(alias="clanCode")
    name: str
    status: str
    created_by: Optional[str] = Field(None, alias="createdBy")
    activated_at: Optional[datetime] = Field(None, alias="activatedAt")
    suspended_at: Optional[datetime] = Field(None, alias="suspendedAt")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

class FamilyUpdate(BaseModel):
    clan_code: Optional[str] = Field(None, alias="clanCode")
    name: Optional[str] = None
    status: Optional[str] = None

class BranchResponse(BaseModel):
    id: str
    family_id: str = Field(alias="familyId")
    name: str
    code: Optional[str] = None
    parent_branch_id: Optional[str] = Field(None, alias="parentBranchId")
    branch_order: int = Field(alias="branchOrder")
    description: Optional[str] = None
    status: str

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

class BranchCreate(BaseModel):
    name: str
    code: Optional[str] = None
    parent_branch_id: Optional[str] = Field(None, alias="parentBranchId")
    branch_order: Optional[int] = Field(0, alias="branchOrder")
    description: Optional[str] = None
    status: str = "ACTIVE"

class BranchUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    parent_branch_id: Optional[str] = Field(None, alias="parentBranchId")
    branch_order: Optional[int] = Field(None, alias="branchOrder")
    description: Optional[str] = None
    status: Optional[str] = None
