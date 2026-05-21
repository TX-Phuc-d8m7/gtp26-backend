"""Chat History router — quản lý threads và messages của chatbot."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.users.models import User
from app.modules.chat.schemas import (
    ChatMessageListResponse,
    ChatMessageResult,
    ChatSendMessageRequest,
    ChatSendMessageResponse,
    ChatThreadCreate,
    ChatThreadListResponse,
    ChatThreadResult,
    ChatThreadUpdate,
    MessageEditRequest,
    MessageFeedbackRequest,
)
from app.modules.auth.service import get_current_user
from app.modules.chat.service import (
    create_thread,
    delete_thread,
    edit_and_resend,
    get_thread,
    list_messages,
    list_threads,
    regenerate_message,
    send_message,
    set_message_feedback,
    update_thread,
)

router = APIRouter(prefix="/chat", tags=["Chat History"])

# ⚠️ Route tĩnh (/threads) đặt trước route có path param (/{thread_id})


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------

@router.get(
    "/threads",
    response_model=ChatThreadListResponse,
    summary="Danh sách hội thoại của user",
)
async def get_my_threads(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    q: Optional[str] = Query(default=None, description="Tìm theo tiêu đề thread"),
    pinned_first: bool = Query(default=True, description="Ghim trên cùng (mặc định: true)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Trả danh sách threads của user hiện tại, không bao gồm đã xoá.

    Mặc định sắp xếp: **ghim trên cùng → mới nhất trước**.

    Mỗi item có `message_count` và `last_message_at` để hiển thị preview.
    """
    total, items = await list_threads(
        current_user.id, db,
        limit=limit,
        offset=offset,
        q=q,
        pinned_first=pinned_first,
    )
    return ChatThreadListResponse(total=total, limit=limit, offset=offset, items=items)


@router.post(
    "/threads",
    response_model=ChatThreadResult,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo hội thoại mới",
)
async def create_new_thread(
    payload: ChatThreadCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Tạo thread mới.

    - `title`: tuỳ chọn. Nếu bỏ trống, tiêu đề sẽ được tự động tạo từ tin nhắn đầu tiên.

    ```json
    { "title": "Hỏi về chế độ ăn cho người cao huyết áp" }
    ```
    """
    return await create_thread(current_user.id, payload, db)


@router.get(
    "/threads/{thread_id}",
    response_model=ChatThreadResult,
    summary="Chi tiết metadata một hội thoại",
)
async def get_thread_detail(
    thread_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trả metadata thread (title, is_pinned, message_count, ...). `404` nếu không tìm thấy."""
    result = await get_thread(thread_id, current_user.id, db)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy hội thoại.",
        )
    return result


@router.patch(
    "/threads/{thread_id}",
    response_model=ChatThreadResult,
    summary="Cập nhật tiêu đề hoặc trạng thái ghim",
)
async def update_thread_detail(
    thread_id: uuid.UUID,
    payload: ChatThreadUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Cập nhật `title` và/hoặc `is_pinned`. Chỉ gửi field cần thay đổi.

    ```json
    { "title": "Ăn gì khi bị gout?", "is_pinned": true }
    ```
    """
    result = await update_thread(thread_id, current_user.id, payload, db)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy hội thoại.",
        )
    return result


@router.delete(
    "/threads/{thread_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Xoá hội thoại (soft delete)",
)
async def delete_thread_endpoint(
    thread_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft delete thread — dữ liệu vẫn lưu trong DB nhưng không hiển thị. `404` nếu không tìm thấy."""
    deleted = await delete_thread(thread_id, current_user.id, db)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy hội thoại.",
        )


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

@router.get(
    "/threads/{thread_id}/messages",
    response_model=ChatMessageListResponse,
    summary="Lấy danh sách tin nhắn trong hội thoại",
)
async def get_thread_messages(
    thread_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Trả danh sách messages theo thứ tự **cũ nhất trước** (timeline chat).

    Mỗi assistant message có:
    - `content`: lời tư vấn tự nhiên từ AI
    - `food_results`: danh sách món được gợi ý (với matchScore, reason)
    - `query_log_id`: ID log để admin tra cứu

    `404` nếu thread không tồn tại hoặc không thuộc user.
    """
    result = await list_messages(thread_id, current_user.id, db, limit=limit, offset=offset)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy hội thoại.",
        )
    total, items = result
    return ChatMessageListResponse(total=total, limit=limit, offset=offset, items=items)


@router.post(
    "/threads/{thread_id}/messages",
    response_model=ChatSendMessageResponse,
    summary="Gửi tin nhắn và nhận gợi ý món ăn từ AI",
)
async def send_message_endpoint(
    thread_id: uuid.UUID,
    payload: ChatSendMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    **Endpoint chính của chatbot** — gửi câu hỏi và nhận gợi ý món ăn.

    Luồng xử lý:
    1. Lưu tin nhắn của user vào thread.
    2. Gọi AI search (có áp dụng health profile nếu có).
    3. Lưu phản hồi của AI vào thread.
    4. Tự động đặt tiêu đề thread từ câu hỏi đầu tiên (nếu chưa có).

    **Response** gồm:
    - `user_message`: tin nhắn vừa gửi
    - `assistant_message`: phản hồi AI (lời tư vấn + danh sách món)
    - `search_result`: toàn bộ kết quả search gốc (để frontend render card món ăn)

    **Lưu ý**: Hồ sơ sức khỏe tự động được áp dụng nếu user đã tạo.
    Truyền `skip_profile=true` để bỏ qua cho lần tìm kiếm này.

    `404` nếu thread không tồn tại hoặc không thuộc user.
    """
    result = await send_message(
        thread_id=thread_id,
        user_id=current_user.id,
        query=payload.query,
        skip_profile=payload.skip_profile,
        lat=payload.lat,
        lng=payload.lng,
        db=db,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy hội thoại.",
        )
    return result


# ---------------------------------------------------------------------------
# Regenerate — thử lại câu trả lời AI
# ---------------------------------------------------------------------------

@router.post(
    "/threads/{thread_id}/messages/{message_id}/regenerate",
    response_model=ChatSendMessageResponse,
    summary="Thử lại câu trả lời AI",
)
async def regenerate_message_endpoint(
    thread_id: uuid.UUID,
    message_id: uuid.UUID,
    skip_profile: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Xoá assistant message cũ và tạo lại response từ cùng câu hỏi.

    - `message_id`: ID của **assistant message** cần regenerate.
    - Conversation context và health profile vẫn được áp dụng như bình thường.
    - `404` nếu không tìm thấy thread hoặc message.
    """
    result = await regenerate_message(
        thread_id=thread_id,
        message_id=message_id,
        user_id=current_user.id,
        skip_profile=skip_profile,
        db=db,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy hội thoại hoặc tin nhắn.",
        )
    return result


# ---------------------------------------------------------------------------
# Message Feedback — 👍 / 👎
# ---------------------------------------------------------------------------

@router.patch(
    "/threads/{thread_id}/messages/{message_id}/feedback",
    response_model=ChatMessageResult,
    summary="Đánh giá câu trả lời AI (👍 / 👎)",
)
async def message_feedback_endpoint(
    thread_id: uuid.UUID,
    message_id: uuid.UUID,
    payload: MessageFeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Đặt hoặc xoá feedback cho một **assistant message**.

    ```json
    { "feedback": "like" }    // 👍 hữu ích
    { "feedback": "dislike" } // 👎 không hữu ích
    { "feedback": null }      // xoá feedback đã đặt
    ```

    - `404` nếu không tìm thấy hoặc message không phải assistant.
    """
    result = await set_message_feedback(
        thread_id=thread_id,
        message_id=message_id,
        user_id=current_user.id,
        feedback=payload.feedback,
        db=db,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy tin nhắn hoặc tin nhắn không phải từ AI.",
        )
    return result


# ---------------------------------------------------------------------------
# Edit & Resend — chỉnh sửa câu hỏi và chạy lại
# ---------------------------------------------------------------------------

@router.post(
    "/threads/{thread_id}/messages/{message_id}/edit",
    response_model=ChatSendMessageResponse,
    summary="Chỉnh sửa câu hỏi cũ và gửi lại",
)
async def edit_and_resend_endpoint(
    thread_id: uuid.UUID,
    message_id: uuid.UUID,
    payload: MessageEditRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Chỉnh sửa nội dung một **user message** và chạy lại toàn bộ từ điểm đó.

    **Lưu ý quan trọng:** Tất cả messages sau message được edit sẽ bị **xoá vĩnh viễn**
    (assistant response cũ và các lượt hội thoại tiếp theo).

    ```json
    {
      "query": "Tôi bị cao huyết áp, gợi ý món ăn sáng ít muối",
      "skip_profile": false
    }
    ```

    - `message_id`: ID của **user message** cần chỉnh sửa.
    - `404` nếu không tìm thấy hoặc message không phải từ user.
    """
    result = await edit_and_resend(
        thread_id=thread_id,
        message_id=message_id,
        user_id=current_user.id,
        data=payload,
        db=db,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy hội thoại hoặc tin nhắn.",
        )
    return result
