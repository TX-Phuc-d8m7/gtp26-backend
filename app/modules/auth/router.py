"""Auth router: signup, login, refresh, logout, change-password, forgot/reset-password."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.modules.users.models import User
from app.modules.auth.schemas import (
    AuthLoginRequest,
    AuthLogoutRequest,
    AuthLogoutResponse,
    AuthSignupRequest,
    AuthTokenResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    RefreshTokenRequest,
    ResetPasswordRequest,
    ResetPasswordResponse,
)
from app.modules.users.schemas import UserResult
from app.modules.auth.service import (
    create_access_token,
    create_password_reset_token,
    create_refresh_token,
    get_current_user,
    hash_password,
    revoke_refresh_token,
    verify_and_rotate_refresh_token,
    verify_password,
    verify_password_reset_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)

router = APIRouter(prefix="/auth", tags=["Auth"])


async def _build_token_response(user: User, db: AsyncSession) -> AuthTokenResponse:
    """Tạo access token + refresh token mới, trả về AuthTokenResponse."""
    access_token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        role=user.role,
    )
    refresh_token = await create_refresh_token(user.id, db)
    return AuthTokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
    )


# ---------------------------------------------------------------------------
# Signup / Login
# ---------------------------------------------------------------------------

@router.post(
    "/signup",
    response_model=AuthTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Đăng ký tài khoản mới",
)
async def signup(
    payload: AuthSignupRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Tạo tài khoản người dùng mới.

    - **email**: địa chỉ email (dùng để đăng nhập, phải duy nhất).
    - **password**: mật khẩu tối thiểu 6 ký tự.
    - **full_name**: tên hiển thị (không bắt buộc).

    Trả về JWT access token + refresh token.
    """
    result = await db.execute(select(User).where(User.email == payload.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email này đã được đăng ký.",
        )

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role="user",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return await _build_token_response(user, db)


@router.post(
    "/login",
    response_model=AuthTokenResponse,
    summary="Đăng nhập",
)
async def login(
    payload: AuthLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Đăng nhập bằng email và mật khẩu.

    Trả về JWT access token (ngắn hạn) + refresh token (30 ngày).
    Dùng refresh token để lấy access token mới khi hết hạn.
    """
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    invalid_credentials = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Email hoặc mật khẩu không đúng.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not user:
        raise invalid_credentials
    if not verify_password(payload.password, user.hashed_password):
        raise invalid_credentials
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản đã bị vô hiệu hóa. Vui lòng liên hệ admin.",
        )

    return await _build_token_response(user, db)


# ---------------------------------------------------------------------------
# Refresh token
# ---------------------------------------------------------------------------

@router.post(
    "/refresh",
    response_model=AuthTokenResponse,
    summary="Làm mới access token bằng refresh token",
)
async def refresh_token(
    payload: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Cấp access token mới từ refresh token hợp lệ.

    - Refresh token cũ bị **revoke ngay** sau khi dùng (rotation).
    - Response trả về refresh token **mới** — client phải lưu lại token mới này.
    - Refresh token hết hạn sau 30 ngày hoặc khi logout.

    ```json
    { "refresh_token": "<token_nhận_được_khi_login>" }
    ```
    """
    user = await verify_and_rotate_refresh_token(payload.refresh_token, db)
    return await _build_token_response(user, db)


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

@router.post(
    "/logout",
    response_model=AuthLogoutResponse,
    summary="Đăng xuất",
)
async def logout(
    payload: AuthLogoutRequest,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Đăng xuất và revoke refresh token.

    Truyền `refresh_token` trong body để backend vô hiệu hoá token — ngăn dùng lại.
    Nếu không truyền, chỉ logout stateless (frontend xoá token, backend không lưu gì).

    ```json
    { "refresh_token": "<token_hiện_tại>" }
    ```
    """
    if payload.refresh_token:
        await revoke_refresh_token(payload.refresh_token, db)

    return AuthLogoutResponse(
        success=True,
        message="Đăng xuất thành công.",
    )


# ---------------------------------------------------------------------------
# Me
# ---------------------------------------------------------------------------

@router.get(
    "/me",
    response_model=UserResult,
    summary="Lấy thông tin người dùng hiện tại",
)
async def get_me(
    current_user: User = Depends(get_current_user),
):
    """
    Trả về thông tin tài khoản của người dùng đang đăng nhập.

    Yêu cầu JWT Bearer token trong header `Authorization`.
    """
    return current_user


# ---------------------------------------------------------------------------
# Change password
# ---------------------------------------------------------------------------

@router.post(
    "/change-password",
    response_model=ChangePasswordResponse,
    summary="Đổi mật khẩu",
)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Đổi mật khẩu cho tài khoản đang đăng nhập.

    Yêu cầu Bearer token hợp lệ trong header `Authorization`.

    ```json
    {
      "current_password": "mật_khẩu_hiện_tại",
      "new_password": "mật_khẩu_mới_ít_nhất_6_ký_tự"
    }
    ```
    """
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mật khẩu hiện tại không đúng.",
        )

    if payload.current_password == payload.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mật khẩu mới phải khác mật khẩu hiện tại.",
        )

    current_user.hashed_password = hash_password(payload.new_password)
    await db.commit()

    return ChangePasswordResponse(message="Đổi mật khẩu thành công.")


# ---------------------------------------------------------------------------
# Forgot / Reset password
# ---------------------------------------------------------------------------

@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponse,
    summary="Yêu cầu reset mật khẩu",
)
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Tạo token reset mật khẩu (hết hạn sau 30 phút).

    **Production:** token sẽ được gửi qua email — không hiện trong response.
    **Demo/Dev:** `reset_token` được trả về trực tiếp để tiện test.

    Luôn trả về HTTP 200 dù email không tồn tại (tránh lộ danh sách tài khoản).
    """
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    # Trả về cùng message dù email tồn tại hay không (security best practice)
    if not user or not user.is_active:
        return ForgotPasswordResponse(
            message="Nếu email tồn tại, bạn sẽ nhận được hướng dẫn reset mật khẩu.",
        )

    raw_token = await create_password_reset_token(user.id, db)

    # TODO production: gửi raw_token qua email thay vì trả về response
    return ForgotPasswordResponse(
        message="Nếu email tồn tại, bạn sẽ nhận được hướng dẫn reset mật khẩu.",
        reset_token=raw_token,  # DEMO ONLY — xóa khi production
    )


@router.post(
    "/reset-password",
    response_model=ResetPasswordResponse,
    summary="Đặt lại mật khẩu bằng reset token",
)
async def reset_password(
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Đặt lại mật khẩu mới bằng token từ `/auth/forgot-password`.

    Token chỉ dùng được **một lần** và hết hạn sau **30 phút**.

    ```json
    {
      "token": "<token_từ_forgot_password>",
      "new_password": "mật_khẩu_mới_ít_nhất_6_ký_tự"
    }
    ```
    """
    user = await verify_password_reset_token(payload.token, db)
    user.hashed_password = hash_password(payload.new_password)
    await db.commit()

    return ResetPasswordResponse(message="Đặt lại mật khẩu thành công. Vui lòng đăng nhập lại.")
