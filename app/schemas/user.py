from typing import Optional
from datetime import datetime
from pydantic import BaseModel, EmailStr

# --- SCHEMAS CHO ĐĂNG KÝ / ĐĂNG NHẬP ---
class UserRegister(BaseModel):
    username: str
    email_or_phone: str
    display_name: str
    password: str
    confirm_password: str

class UserLogin(BaseModel):
    email_or_phone: str
    password: str

# --- SCHEMAS CHO US-04: QUÊN / ĐẶT LẠI MẬT KHẨU ---
class ForgotPasswordRequest(BaseModel):
    email_or_phone: str

class VerifyOTPRequest(BaseModel):
    email_or_phone: str
    otp_code: str

class ResetPasswordRequest(BaseModel):
    token_or_otp: str
    new_password: str
    confirm_new_password: str

# --- SCHEMA OUTPUT ---
class UserOut(BaseModel):
    id: str
    username: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    full_name: str
    role: str
    status: str
    created_at: Optional[datetime] = None

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
