from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, EmailStr


class RoleOut(BaseModel):
    id: str
    account_id: str
    role: str
    family_id: Optional[str] = None
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AccountOut(BaseModel):
    id: str
    firebase_uid: str
    username: Optional[str] = None
    email: Optional[str] = None
    phone_e164: Optional[str] = None
    display_name: Optional[str] = None
    email_verified: bool
    phone_verified: bool
    status: str
    roles: List[RoleOut] = []
    primary_role: str = "member"

    model_config = ConfigDict(from_attributes=True)


class RoleRequestCreate(BaseModel):
    requested_role: str = "family_head"
    family_id: Optional[str] = None
    reason: Optional[str] = None


class RoleRequestReview(BaseModel):
    status: str  # "approved" or "rejected"
    reviewer_notes: Optional[str] = None


class RoleRequestOut(BaseModel):
    id: str
    account_id: str
    requested_role: str
    family_id: Optional[str] = None
    reason: Optional[str] = None
    status: str
    reviewer_id: Optional[str] = None
    reviewer_notes: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
