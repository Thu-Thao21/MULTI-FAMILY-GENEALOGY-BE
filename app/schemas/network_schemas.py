from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class FamilyNetworkOut(BaseModel):
    id: str
    name: str
    founder_name: Optional[str] = Field(None, alias="founderName")
    origin_place: Optional[str] = Field(None, alias="originPlace")
    ancestral_house_address: Optional[str] = Field(None, alias="ancestralHouseAddress")
    history: Optional[str] = None
    description: Optional[str] = None
    branches: list[str] = Field(default_factory=list)
    status: str = "active"
    category: str = "noi"  # noi, ngoai, thong-gia
    member_count: int = Field(0, alias="memberCount")
    linked_since: Optional[str] = Field(None, alias="linkedSince")

    class Config:
        from_attributes = True
        populate_by_name = True


class InLawMarriageOut(BaseModel):
    id: str
    husband_name: str = Field(alias="husbandName")
    husband_family: str = Field(alias="husbandFamily")
    wife_name: str = Field(alias="wifeName")
    wife_family: str = Field(alias="wifeFamily")
    marriage_date: Optional[str] = Field(None, alias="marriageDate")
    status: str = "active"
    notes: Optional[str] = None

    class Config:
        populate_by_name = True


class FamilyLinkRequestOut(BaseModel):
    id: str
    source_family_id: str = Field(alias="sourceFamilyId")
    source_family_name: str = Field(alias="sourceFamilyName")
    target_family_id: str = Field(alias="targetFamilyId")
    target_family_name: str = Field(alias="targetFamilyName")
    request_type: str = Field("marriage", alias="requestType")
    status: str = "pending"
    message: Optional[str] = None
    created_at: Optional[datetime] = Field(None, alias="createdAt")

    class Config:
        populate_by_name = True


class FamilyLinkRequestCreateIn(BaseModel):
    target_family_id: str
    request_type: str = "marriage"
    message: Optional[str] = None


class FamilyLinkRequestReviewIn(BaseModel):
    status: str  # approved, rejected
