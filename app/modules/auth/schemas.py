from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field


class AuthSignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, description="Mật khẩu tối thiểu 6 ký tự")
    full_name: Optional[str] = None


class AuthLoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    # Thời gian access token còn hiệu lực (giây) — frontend dùng để schedule refresh
    expires_in: int
    user_id: uuid.UUID
    email: str
    full_name: Optional[str] = None
    role: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class AuthLogoutRequest(BaseModel):
    # Optional: revoke refresh token khi logout; nếu không có thì chỉ logout stateless
    refresh_token: Optional[str] = None


class AuthLogoutResponse(BaseModel):
    success: bool
    message: str


# ---------------------------------------------------------------------------
# Change password
# ---------------------------------------------------------------------------

class ChangePasswordRequest(BaseModel):
    current_password: str = Field(description="Mật khẩu hiện tại")
    new_password: str = Field(min_length=6, description="Mật khẩu mới tối thiểu 6 ký tự")


class ChangePasswordResponse(BaseModel):
    message: str


# ---------------------------------------------------------------------------
# Forgot / Reset password
# ---------------------------------------------------------------------------

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    message: str
    # DEMO ONLY — trong production sẽ gửi qua email, không trả về trực tiếp.
    # Xóa trường này trước khi lên production thật.
    reset_token: Optional[str] = None


class ResetPasswordRequest(BaseModel):
    token: str = Field(description="Token nhận được từ /auth/forgot-password")
    new_password: str = Field(min_length=6, description="Mật khẩu mới tối thiểu 6 ký tự")


class ResetPasswordResponse(BaseModel):
    message: str
