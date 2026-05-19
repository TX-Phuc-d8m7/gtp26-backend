"""Auth router: signup, login, refresh, logout, get current user."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models import User
from app.schemas import AuthLoginRequest, AuthLogoutResponse, AuthSignupRequest, AuthTokenResponse, UserResult
from app.modules.auth.service import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["Auth"])


def _build_token_response(user: User) -> AuthTokenResponse:
    token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        role=user.role,
    )
    return AuthTokenResponse(
        access_token=token,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
    )


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

    Trả về JWT access token có hiệu lực 24 giờ.
    """
    # Kiểm tra email đã tồn tại chưa
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

    return _build_token_response(user)


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

    Trả về JWT access token có hiệu lực 24 giờ.
    """
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    # Dùng cùng thông báo lỗi để tránh lộ thông tin tài khoản
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

    return _build_token_response(user)


@router.post(
    "/refresh",
    response_model=AuthTokenResponse,
    summary="Làm mới access token",
)
async def refresh_token(
    current_user: User = Depends(get_current_user),
):
    """
    Cấp lại JWT access token mới từ Bearer token hiện tại.

    MVP hiện dùng JWT stateless, chưa tách access/refresh token riêng. Khi cần refresh
    token dài hạn, có thể bổ sung refresh token table hoặc blacklist sau.
    """
    return _build_token_response(current_user)


@router.post(
    "/logout",
    response_model=AuthLogoutResponse,
    summary="Đăng xuất",
)
async def logout(
    _: User = Depends(get_current_user),
):
    """
    Xác nhận đăng xuất cho client.

    JWT hiện là stateless nên backend không lưu session để huỷ. Frontend chỉ cần xoá
    token đang lưu. Nếu sau này cần revoke token ngay lập tức, thêm blacklist/token store.
    """
    return AuthLogoutResponse(
        success=True,
        message="Đăng xuất thành công. Vui lòng xóa access token ở client.",
    )


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
