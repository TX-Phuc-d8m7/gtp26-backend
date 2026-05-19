"""Google Cloud Storage service — upload và quản lý ảnh món ăn."""

from __future__ import annotations

import os
import uuid
from typing import Optional

from google.cloud import storage

# ---------------------------------------------------------------------------
# Cấu hình
# ---------------------------------------------------------------------------

BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "food-ai-media-dev")
FOOD_IMAGE_PREFIX = os.getenv("GCS_FOOD_IMAGE_PREFIX", "foods/")

# Các định dạng ảnh được phép upload
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

# Giới hạn kích thước file: 5MB
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024

# URL công khai của GCS
GCS_PUBLIC_URL = "https://storage.googleapis.com"

# ---------------------------------------------------------------------------
# GCS Client — lazy init để tránh lỗi khi chạy unit test không có credentials
# ---------------------------------------------------------------------------

_client: Optional[storage.Client] = None


def _get_client() -> storage.Client:
    """Trả GCS client, khởi tạo lần đầu khi cần (Application Default Credentials)."""
    global _client
    if _client is None:
        _client = storage.Client()
    return _client


def _get_bucket() -> storage.Bucket:
    return _get_client().bucket(BUCKET_NAME)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_public_url(blob_name: str) -> str:
    """Tạo URL công khai từ tên blob."""
    return f"{GCS_PUBLIC_URL}/{BUCKET_NAME}/{blob_name}"


def upload_food_image(
    file_content: bytes,
    original_filename: str,
    content_type: str,
    food_id: Optional[str] = None,
) -> str:
    """
    Upload ảnh món ăn lên GCS và trả về public URL.

    - Tên file được đặt lại thành UUID để tránh trùng lặp và path traversal.
    - Đặt trong thư mục `foods/` (hoặc theo GCS_FOOD_IMAGE_PREFIX).

    Args:
        file_content:      Nội dung file dưới dạng bytes.
        original_filename: Tên file gốc (dùng để lấy extension).
        content_type:      MIME type (image/jpeg, image/png, image/webp).
        food_id:           Nếu truyền vào, dùng làm tên file thay vì random UUID.
                           Hữu ích khi muốn overwrite ảnh cũ của cùng món.

    Returns:
        Public URL của ảnh đã upload.

    Raises:
        ValueError: Nếu định dạng file hoặc kích thước không hợp lệ.
    """
    # Validate content type
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValueError(
            f"Định dạng ảnh không được hỗ trợ: {content_type}. "
            f"Chỉ chấp nhận: {', '.join(ALLOWED_CONTENT_TYPES)}"
        )

    # Validate kích thước
    if len(file_content) > MAX_FILE_SIZE_BYTES:
        raise ValueError(
            f"File quá lớn ({len(file_content) / 1024 / 1024:.1f}MB). "
            f"Tối đa {MAX_FILE_SIZE_BYTES / 1024 / 1024:.0f}MB."
        )

    # Lấy extension từ tên file gốc
    ext = _get_extension(original_filename, content_type)

    # Đặt tên blob
    blob_name_stem = food_id if food_id else str(uuid.uuid4())
    blob_name = f"{FOOD_IMAGE_PREFIX}{blob_name_stem}{ext}"

    # Upload lên GCS
    bucket = _get_bucket()
    blob = bucket.blob(blob_name)
    blob.upload_from_string(file_content, content_type=content_type)

    return build_public_url(blob_name)


def delete_food_image(img_url: str) -> bool:
    """
    Xóa ảnh khỏi GCS dựa vào URL.
    Trả False nếu URL không thuộc bucket này hoặc blob không tồn tại.
    """
    blob_name = _extract_blob_name(img_url)
    if blob_name is None:
        return False

    bucket = _get_bucket()
    blob = bucket.blob(blob_name)
    if not blob.exists():
        return False

    blob.delete()
    return True


# ---------------------------------------------------------------------------
# Helpers nội bộ
# ---------------------------------------------------------------------------

def _get_extension(filename: str, content_type: str) -> str:
    """Lấy extension từ filename, fallback về content_type nếu không có."""
    if filename:
        _, ext = os.path.splitext(filename.lower())
        if ext in ALLOWED_EXTENSIONS:
            return ext

    # Fallback từ content_type
    _ct_to_ext = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    return _ct_to_ext.get(content_type, ".jpg")


def _extract_blob_name(img_url: str) -> Optional[str]:
    """
    Trích xuất blob name từ GCS public URL.
    Ví dụ: https://storage.googleapis.com/food-ai-media-1d1e4159/foods/abc.jpg
             → foods/abc.jpg
    """
    prefix = f"{GCS_PUBLIC_URL}/{BUCKET_NAME}/"
    if not img_url.startswith(prefix):
        return None
    return img_url[len(prefix):]
