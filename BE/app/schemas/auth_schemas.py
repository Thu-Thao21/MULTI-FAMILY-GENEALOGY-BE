from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, EmailStr


class RoleOut(BaseModel):
    id: str
    account_id: str
    role: str
    family_id: Optional[str] = None
    granted_at: datetime
    revoked_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AccountOut(BaseModel):
    id: str
    firebase_uid: Optional[str] = None
    username: Optional[str] = None
    email: str
    phone_e164: Optional[str] = None
    display_name: str
    email_verified: bool
    phone_verified: bool
    first_login_required: bool
    last_login_at: Optional[datetime] = None
    status: str
    roles: List[RoleOut] = []
    primary_role: str = "member"

    model_config = ConfigDict(from_attributes=True)
