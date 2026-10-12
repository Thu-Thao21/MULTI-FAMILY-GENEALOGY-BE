from __future__ import annotations

from datetime import date
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

class PersonResponse(BaseModel):
    id: str
    family_id: str = Field(alias="familyId")
    branch_id: Optional[str] = Field(None, alias="branchId")
    full_name: str = Field(alias="fullName")
    gender: str
    birth_date: Optional[date] = Field(None, alias="birthDate")
    death_date: Optional[date] = Field(None, alias="deathDate")
    generation: int
    avatar_url: Optional[str] = Field(None, alias="avatarUrl")
    is_alive: bool = Field(alias="isLiving")
    status: str

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class PersonCreate(BaseModel):
    full_name: str = Field(alias="fullName", min_length=1)
    branch_id: Optional[str] = Field(None, alias="branchId")
    gender: str = "unknown"
    birth_date: Optional[date] = Field(None, alias="birthDate")
    death_date: Optional[date] = Field(None, alias="deathDate")
    avatar_url: Optional[str] = Field(None, alias="avatarUrl")
    is_alive: bool = Field(True, alias="isLiving")
    status: str = "active"

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class PersonUpdate(BaseModel):
    full_name: Optional[str] = Field(None, alias="fullName", min_length=1)
    branch_id: Optional[str] = Field(None, alias="branchId")
    gender: Optional[str] = None
    birth_date: Optional[date] = Field(None, alias="birthDate")
    death_date: Optional[date] = Field(None, alias="deathDate")
    avatar_url: Optional[str] = Field(None, alias="avatarUrl")
    is_alive: Optional[bool] = Field(None, alias="isLiving")
    status: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

class AncestorDescendantResponse(BaseModel):
    person: PersonResponse
    depth: int

class RelationshipCreate(BaseModel):
    from_member_id: str = Field(alias="fromMemberId")
    to_member_id: str = Field(alias="toMemberId")
    relationship_type: str = Field(alias="relationshipType")
    notes: Optional[str] = None

class RelationshipResponse(BaseModel):
    id: str
    from_member_id: str = Field(alias="fromMemberId")
    to_member_id: str = Field(alias="toMemberId")
    relationship_type: str = Field(alias="relationshipType")
    notes: Optional[str] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

class TreeNode(BaseModel):
    id: str
    full_name: str = Field(alias="fullName")
    gender: str
    generation: int
    branch_id: Optional[str] = Field(None, alias="branchId")
    avatar_url: Optional[str] = Field(None, alias="avatarUrl")
    status: str

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

class TreeDataResponse(BaseModel):
    nodes: List[TreeNode]
    edges: List[RelationshipResponse]

class RelationshipPath(BaseModel):
    from_person_id: str = Field(alias="fromPersonId")
    to_person_id: str = Field(alias="toPersonId")
    path: List[RelationshipResponse]
