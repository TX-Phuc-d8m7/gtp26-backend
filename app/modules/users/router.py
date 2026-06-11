"""User Health Profile router: CRUD /users/me + /users/me/health-profile."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.users.models import User
from app.modules.users.schemas import (
    ALLERGY_OPTIONS,
    DISH_TYPE_OPTIONS,
    HEALTH_CONDITION_OPTIONS,
    PREFERRED_INGREDIENT_OPTIONS,
    TASTE_PROFILE_OPTIONS,
    OnboardingOptionsResponse,
    UserAccountUpdate,
    UserDeactivateResponse,
    UserHealthProfileCreate,
    UserHealthProfileResult,
    UserHealthProfileUpdate,
    UserResult,
)
from app.modules.auth.service import get_current_user
from app.modules.users.service import (
    deactivate_account,
    delete_profile,
    get_profile,
    patch_profile,
    update_account,
    upsert_profile,
)

router = APIRouter(prefix="/users/me", tags=["User Account"])


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------

@router.patch(
    "",
    response_model=UserResult,
    summary="Cập nhật thông tin cá nhân",
)
async def update_my_account(
    payload: UserAccountUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Cập nhật email hoặc tên hiển thị của user hiện tại.

    - `email`: phải duy nhất trong hệ thống.
    - `full_name`: gửi chuỗi rỗng để xoá tên hiển thị.
    """
    if payload.email is not None and str(payload.email) != current_user.email:
        existing = await db.execute(select(User).where(User.email == str(payload.email)))
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email này đã được sử dụng bởi tài khoản khác.",
            )

    return await update_account(current_user, payload, db)


@router.delete(
    "",
    response_model=UserDeactivateResponse,
    summary="Vô hiệu hóa tài khoản của chính mình",
)
async def deactivate_my_account(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Vô hiệu hóa tài khoản hiện tại bằng cách đặt `is_active=false`.

    Dữ liệu lịch sử vẫn được giữ lại. Sau request này token hiện tại
    sẽ không còn dùng được ở các endpoint yêu cầu active user.
    """
    if current_user.role == "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin không thể tự vô hiệu hóa tài khoản của chính mình để tránh khóa quyền quản trị.",
        )

    await deactivate_account(current_user, db)
    return UserDeactivateResponse(
        success=True,
        message="Tài khoản đã được vô hiệu hóa.",
    )


# ---------------------------------------------------------------------------
# Onboarding options
# ---------------------------------------------------------------------------

@router.get(
    "/onboarding-options",
    response_model=OnboardingOptionsResponse,
    summary="Lấy danh sách lựa chọn cho màn hình onboarding",
)
async def get_onboarding_options():
    """
    Trả về toàn bộ options hợp lệ để hiển thị trong màn hình onboarding.

    Không yêu cầu authentication — frontend có thể gọi trước khi user đăng nhập.

    **Các nhóm options:**
    - `health_conditions`: bệnh lý & triệu chứng (9 options)
    - `allergies`: dị ứng thực phẩm (6 options)
    - `preferred_ingredients`: nguyên liệu ưa thích (8 options)
    - `taste_profile`: khẩu vị yêu thích (8 options)
    - `dish_preferences`: cách nấu yêu thích (15 options)
    """
    return OnboardingOptionsResponse(
        health_conditions=HEALTH_CONDITION_OPTIONS,
        allergies=ALLERGY_OPTIONS,
        preferred_ingredients=PREFERRED_INGREDIENT_OPTIONS,
        taste_profile=TASTE_PROFILE_OPTIONS,
        dish_preferences=DISH_TYPE_OPTIONS,
    )


# ---------------------------------------------------------------------------
# Health profile CRUD
# ---------------------------------------------------------------------------

@router.get(
    "/health-profile",
    response_model=UserHealthProfileResult,
    summary="Lấy hồ sơ sức khỏe hiện tại",
)
async def get_my_health_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Trả về hồ sơ sức khỏe của người dùng đang đăng nhập.

    - Trả `404` nếu chưa tạo profile.
    - Yêu cầu JWT Bearer token.
    """
    profile = await get_profile(current_user.id, db)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hồ sơ sức khỏe chưa được tạo. Dùng PUT để tạo mới.",
        )
    return profile


@router.put(
    "/health-profile",
    response_model=UserHealthProfileResult,
    summary="Tạo hoặc thay thế toàn bộ hồ sơ sức khỏe",
)
async def upsert_my_health_profile(
    payload: UserHealthProfileCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Tạo mới hoặc thay thế hoàn toàn hồ sơ sức khỏe.

    Nếu chưa có profile sẽ tạo mới. Nếu đã có sẽ ghi đè toàn bộ.

    **Ví dụ payload:**
    ```json
    {
      "health_conditions": ["Cao huyết áp", "Tiểu đường"],
      "allergies": ["Dị ứng động vật giáp xác"],
      "preferred_ingredients": ["Gà", "Nấm", "Rau"],
      "taste_profile": ["Đậm đà", "Cay"],
      "dish_preferences": ["Nướng", "Xào", "Hấp / Luộc"]
    }
    ```
    """
    return await upsert_profile(current_user.id, payload, db)


@router.patch(
    "/health-profile",
    response_model=UserHealthProfileResult,
    summary="Cập nhật một phần hồ sơ sức khỏe",
)
async def patch_my_health_profile(
    payload: UserHealthProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Cập nhật một số field trong hồ sơ sức khỏe (không cần gửi toàn bộ).

    Chỉ các field được gửi lên mới được cập nhật, các field còn lại giữ nguyên.

    Trả `404` nếu profile chưa tồn tại — dùng `PUT` để tạo trước.
    """
    profile = await patch_profile(current_user.id, payload, db)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hồ sơ sức khỏe chưa được tạo. Dùng PUT để tạo mới.",
        )
    return profile


@router.delete(
    "/health-profile",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Xóa hồ sơ sức khỏe",
)
async def delete_my_health_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Xóa toàn bộ hồ sơ sức khỏe của người dùng hiện tại.

    Trả `204 No Content` nếu xóa thành công.
    Trả `404` nếu profile không tồn tại.
    """
    deleted = await delete_profile(current_user.id, db)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hồ sơ sức khỏe không tồn tại.",
        )
