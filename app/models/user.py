from typing import Optional
from datetime import datetime
from pydantic import BaseModel, EmailStr

class User(BaseModel):
    id: Optional[str] = None
    email: EmailStr
    username: str
    full_name: str
    password_hash: str
    phone: Optional[str] = None
    member_id: Optional[str] = None
    role: str = "member"  # "admin", "member"
    status: str = "active"
    reset_token: Optional[str] = None
    reset_token_expires_at: Optional[datetime] = None
    otp_code: Optional[str] = None
    otp_expires_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
