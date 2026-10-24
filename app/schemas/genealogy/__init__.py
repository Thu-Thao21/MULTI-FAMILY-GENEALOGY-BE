"""Schemas for Genealogy module (C03)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PersonResponse(BaseModel):
    id: uuid.UUID | str
    family_id: uuid.UUID | str = Field(alias="familyId")
    branch_id: Optional[uuid.UUID | str] = Field(None, alias="branchId")
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

    @model_validator(mode="after")
    def validate_dates(self):
        today = date.today()
        if self.birth_date and self.birth_date > today:
            raise ValueError("Ngày sinh không thể ở trong tương lai (birth date cannot be in the future)")
        if self.birth_date and self.death_date and self.death_date < self.birth_date:
            raise ValueError("Ngày mất phải sau hoặc cùng ngày sinh (death date must be on or after birth date)")
        return self


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

    @model_validator(mode="after")
    def validate_dates(self):
        today = date.today()
        if self.birth_date and self.birth_date > today:
            raise ValueError("Ngày sinh không thể ở trong tương lai (birth date cannot be in the future)")
        if self.birth_date and self.death_date and self.death_date < self.birth_date:
            raise ValueError("Ngày mất phải sau hoặc cùng ngày sinh (death date must be on or after birth date)")
        return self


class AncestorDescendantResponse(BaseModel):
    person: PersonResponse
    depth: int


class RelationshipCreate(BaseModel):
    from_member_id: str = Field(alias="fromMemberId")
    to_member_id: str = Field(alias="toMemberId")
    relationship_type: str = Field(alias="relationshipType")
    notes: Optional[str] = None


class RelationshipResponse(BaseModel):
    id: uuid.UUID | str
    from_member_id: uuid.UUID | str = Field(alias="fromMemberId")
    to_member_id: uuid.UUID | str = Field(alias="toMemberId")
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
    is_alive: bool = Field(True, alias="isLiving")
    status: str

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class TreeDataResponse(BaseModel):
    nodes: List[TreeNode]
    edges: List[RelationshipResponse]


class FocusViewNode(BaseModel):
    id: str
    full_name: str = Field(alias="fullName")
    gender: str
    generation: int
    branch_id: Optional[str] = Field(None, alias="branchId")
    avatar_url: Optional[str] = Field(None, alias="avatarUrl")
    depth: int
    is_ego: bool = Field(False, alias="isEgo")
    role: Optional[str] = None
    status: str

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class FocusViewResponse(BaseModel):
    ego: PersonResponse
    nodes: List[FocusViewNode]
    edges: List[RelationshipResponse]
    max_depth: int = Field(alias="maxDepth")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class RelationshipPath(BaseModel):
    from_person_id: str = Field(alias="fromPersonId")
    to_person_id: str = Field(alias="toPersonId")
    path: List[RelationshipResponse]


class RelationshipCalculationResponse(BaseModel):
    found: bool
    from_person: Optional[PersonResponse] = Field(None, alias="fromPerson")
    to_person: Optional[PersonResponse] = Field(None, alias="toPerson")
    path: List[PersonResponse] = []
    edges: List[RelationshipResponse] = []
    kinship_name: str = Field(alias="kinshipName")
    address_title: str = Field(alias="addressTitle")
    reciprocal_kinship: Optional[str] = Field(None, alias="reciprocalKinship")
    reciprocal_address: Optional[str] = Field(None, alias="reciprocalAddress")
    generation_diff: int = Field(0, alias="generationDiff")
    description: str = ""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class PublicClanSummary(BaseModel):
    id: str
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    status: str = "ACTIVE"

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


__all__ = [
    "PersonResponse",
    "PersonCreate",
    "PersonUpdate",
    "AncestorDescendantResponse",
    "RelationshipCreate",
    "RelationshipResponse",
    "TreeNode",
    "TreeDataResponse",
    "FocusViewNode",
    "FocusViewResponse",
    "RelationshipPath",
    "RelationshipCalculationResponse",
    "PublicClanSummary",
]
