"""User Health Profile router: GET / PUT / PATCH / DELETE /users/me/health-profile."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models import User
from app.schemas import UserHealthProfileCreate, UserHealthProfileResult, UserHealthProfileUpdate
from app.modules.auth.service import get_current_user
from app.modules.users.service import (
    delete_profile,
    get_profile,
    patch_profile,
    upsert_profile,
)

router = APIRouter(prefix="/users/me/health-profile", tags=["User Health Profile"])


@router.get(
    "",
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
    "",
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
      "allergies": ["Dị ứng tôm cua"],
      "diet_preferences": ["Ít muối", "Eat Clean"],
      "nutrition_goals": ["Kiểm soát đường huyết"],
      "disliked_ingredients": ["nội tạng"],
      "preferred_ingredients": ["ức gà", "rau xanh"],
      "notes": "Không ăn cay"
    }
    ```
    """
    profile = await upsert_profile(current_user.id, payload, db)
    return profile


@router.patch(
    "",
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
    "",
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
