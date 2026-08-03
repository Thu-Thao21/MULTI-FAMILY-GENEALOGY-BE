from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─── Member List Item ───────────────────────────────────────────────
class MemberOut(BaseModel):
    id: str
    family_id: str = Field(alias="familyId")
    full_name: str = Field(alias="fullName")
    other_name: Optional[str] = Field(None, alias="otherName")
    gender: str
    birth_date: Optional[date] = Field(None, alias="birthDate")
    death_date: Optional[date] = Field(None, alias="deathDate")
    is_alive: bool = Field(alias="isAlive")
    branch: Optional[str] = None
    sub_branch: Optional[str] = Field(None, alias="subBranch")
    generation: int = 1
    occupation: Optional[str] = None
    education: Optional[str] = None
    avatar_url: Optional[str] = Field(None, alias="avatarUrl")
    status: str = "alive"

    class Config:
        from_attributes = True
        populate_by_name = True


# ─── Contact ────────────────────────────────────────────────────────
class ContactOut(BaseModel):
    id: str
    contact_type: str = Field(alias="contactType")
    contact_value: str = Field(alias="contactValue")
    is_primary: bool = Field(alias="isPrimary")
    is_public: bool = Field(alias="isPublic")
    notes: Optional[str] = None

    class Config:
        from_attributes = True
        populate_by_name = True


# ─── Life Event ─────────────────────────────────────────────────────
class LifeEventOut(BaseModel):
    id: str
    event_type: str = Field(alias="eventType")
    title: str
    event_date: Optional[date] = Field(None, alias="eventDate")
    description: Optional[str] = None
    location: Optional[str] = None

    class Config:
        from_attributes = True
        populate_by_name = True


# ─── Media ──────────────────────────────────────────────────────────
class MediaOut(BaseModel):
    id: str
    media_type: str = Field(alias="mediaType")
    media_url: str = Field(alias="mediaUrl")
    caption: Optional[str] = None
    sort_order: int = Field(0, alias="sortOrder")

    class Config:
        from_attributes = True
        populate_by_name = True


# ─── Skill ──────────────────────────────────────────────────────────
class SkillOut(BaseModel):
    id: str
    skill_name: str = Field(alias="skillName")
    category: Optional[str] = None
    proficiency_level: str = Field("basic", alias="proficiencyLevel")

    class Config:
        from_attributes = True
        populate_by_name = True


# ─── Member Detail (full profile) ──────────────────────────────────
class MemberDetailOut(BaseModel):
    id: str
    family_id: str = Field(alias="familyId")
    family_name: Optional[str] = Field(None, alias="familyName")
    user_id: Optional[str] = Field(None, alias="userId")
    full_name: str = Field(alias="fullName")
    other_name: Optional[str] = Field(None, alias="otherName")
    gender: str
    birth_date: Optional[date] = Field(None, alias="birthDate")
    death_date: Optional[date] = Field(None, alias="deathDate")
    lunar_death_date: Optional[str] = Field(None, alias="lunarDeathDate")
    is_alive: bool = Field(alias="isAlive")
    burial_place: Optional[str] = Field(None, alias="burialPlace")
    burial_coordinates: Optional[dict] = Field(None, alias="burialCoordinates")
    father_id: Optional[str] = Field(None, alias="fatherId")
    mother_id: Optional[str] = Field(None, alias="motherId")
    branch: Optional[str] = None
    sub_branch: Optional[str] = Field(None, alias="subBranch")
    display_order: int = Field(0, alias="displayOrder")
    status: str = "alive"
    occupation: Optional[str] = None
    education: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = Field(None, alias="avatarUrl")
    gallery_photos: list[dict] = Field(default_factory=list, alias="galleryPhotos")
    career_history: list[dict] = Field(default_factory=list, alias="careerHistory")
    contact: Optional[dict] = None
    privacy_settings: Optional[dict] = Field(None, alias="privacySettings")
    contribution: Optional[dict] = None
    generation: int = 1
    is_primary: bool = Field(False, alias="isPrimary")
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    updated_at: Optional[datetime] = Field(None, alias="updatedAt")

    # Joined data
    contacts: list[ContactOut] = Field(default_factory=list)
    life_events: list[LifeEventOut] = Field(default_factory=list, alias="lifeEvents")
    media: list[MediaOut] = Field(default_factory=list)
    skills: list[SkillOut] = Field(default_factory=list)

    class Config:
        from_attributes = True
        populate_by_name = True


# ─── Paginated list ────────────────────────────────────────────────
class MemberListOut(BaseModel):
    items: list[MemberOut]
    total: int
    page: int
    limit: int
    total_pages: int = Field(alias="totalPages")

    class Config:
        populate_by_name = True


# ─── Family ─────────────────────────────────────────────────────────
class FamilyOut(BaseModel):
    id: str
    name: str
    founder_name: Optional[str] = Field(None, alias="founderName")
    origin_place: Optional[str] = Field(None, alias="originPlace")
    status: str = "active"
    member_count: int = Field(0, alias="memberCount")

    class Config:
        from_attributes = True
        populate_by_name = True


# ─── Create / Update ───────────────────────────────────────────────
class MemberCreateIn(BaseModel):
    family_id: str
    full_name: str
    other_name: Optional[str] = None
    gender: str = "male"
    birth_date: Optional[date] = None
    is_alive: bool = True
    branch: Optional[str] = None
    occupation: Optional[str] = None
    education: Optional[str] = None
    bio: Optional[str] = None
    generation: int = 1


class MemberUpdateIn(BaseModel):
    full_name: Optional[str] = None
    other_name: Optional[str] = None
    gender: Optional[str] = None
    birth_date: Optional[date] = None
    death_date: Optional[date] = None
    is_alive: Optional[bool] = None
    branch: Optional[str] = None
    occupation: Optional[str] = None
    education: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    generation: Optional[int] = None
