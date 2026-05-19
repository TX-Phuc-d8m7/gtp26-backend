from pydantic import BaseModel, EmailStr
from pydantic import Field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
import uuid

class AIInsight(BaseModel):
    exclude: List[str]
    include: List[str]
    prefer: List[str]
    warning_message: Optional[str] = None

class Filters(BaseModel):
    hard: List[str]
    dietary: List[str]
    soft: List[str]

class FoodResult(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    img_url: Optional[str] = None # Bổ sung thêm theo ERD
    core_ingredients: List[str]   # Đổi tên từ ingredients
    soft_tags: List[str]          # Gộp chung các filter lại theo ERD
    taste_profile: List[str] = Field(default_factory=list)
    meal_context: List[str] = Field(default_factory=list)
    occasion_context: List[str] = Field(default_factory=list)
    matchScore: float             # Nên để kiểu float cho số điểm Vector thay vì str
    reason: Optional[str] = None  # Giải thích ngắn vì sao món được gợi ý

class SearchResponse(BaseModel):
    query: str
    ai_insight: AIInsight
    results: List[FoodResult]
    disclaimer: str
    query_log_id: Optional[uuid.UUID] = None
    retrieval_note: Optional[str] = None
    retrieval_trace: Optional[Dict[str, Any]] = None
    ai_response: Optional[str] = None  # Lời tư vấn tự nhiên từ Post-processing Agent


class QueryLogResult(BaseModel):
    id: uuid.UUID
    user_id: Optional[uuid.UUID] = None
    thread_id: Optional[uuid.UUID] = None
    query: str
    ai_insight: Dict[str, Any] = Field(default_factory=dict)
    final_exclude_ings: List[str] = Field(default_factory=list)
    exclude_ingredient_keys: List[str] = Field(default_factory=list)
    user_include_tags: List[str] = Field(default_factory=list)
    user_exclude_tags: List[str] = Field(default_factory=list)
    candidate_count: int
    filtered_count: int
    scored_count: int
    returned_count: int
    excluded_summary: Dict[str, Any] = Field(default_factory=dict)
    retrieval_notes: List[str] = Field(default_factory=list)
    top_results: List[Dict[str, Any]] = Field(default_factory=list)
    warning_message: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class QueryLogListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[QueryLogResult]


class IngredientAliasOverrideCreate(BaseModel):
    alias: str
    canonical_key: str
    group_keys: List[str] = Field(default_factory=list)
    enabled: bool = True
    notes: str = ""


class IngredientAliasOverrideUpdate(BaseModel):
    alias: Optional[str] = None
    canonical_key: Optional[str] = None
    group_keys: Optional[List[str]] = None
    enabled: Optional[bool] = None
    notes: Optional[str] = None


class IngredientAliasOverrideResult(BaseModel):
    id: uuid.UUID
    alias: str
    alias_key: str
    canonical_key: str
    group_keys: List[str] = Field(default_factory=list)
    enabled: bool
    notes: str = ""

    model_config = {"from_attributes": True}


class RebuildFoodKeysResponse(BaseModel):
    foods_count: int
    updated_count: int


# ---------------------------------------------------------------------------
# Food Library schemas
# ---------------------------------------------------------------------------

class FoodListItem(BaseModel):
    """Card món ăn trong danh sách thư viện — không cần raw_instructions để nhẹ response."""
    id: uuid.UUID
    name: str
    description: str
    img_url: Optional[str] = None
    core_ingredients: List[str]
    soft_tags: List[str]
    taste_profile: List[str]
    meal_context: List[str]
    occasion_context: List[str]

    model_config = {"from_attributes": True}


class FoodListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[FoodListItem]


class FoodDetailResponse(BaseModel):
    """Chi tiết đầy đủ một món ăn, bao gồm nguyên liệu và hướng dẫn nấu."""
    id: uuid.UUID
    name: str
    description: str
    img_url: Optional[str] = None
    core_ingredients: List[str]
    raw_ingredients: List[str]
    raw_instructions: str
    soft_tags: List[str]
    taste_profile: List[str]
    meal_context: List[str]
    occasion_context: List[str]
    # Trạng thái yêu thích của user hiện tại (None nếu chưa đăng nhập)
    is_favorite: Optional[bool] = None
    user_rating: Optional[int] = None
    user_notes: Optional[str] = None

    model_config = {"from_attributes": True}


class FilterGroup(BaseModel):
    label: str
    key: str
    options: List[str]


class FilterOptionsResponse(BaseModel):
    """Tất cả giá trị khả dụng cho từng bộ lọc — dùng để render filter panel ở UI."""
    taste_profile: List[str]
    meal_context: List[str]
    occasion_context: List[str]
    dish_type: List[str]
    diet_style: List[str]
    nutrition: List[str]
    texture: List[str]


# ---------------------------------------------------------------------------
# Favorite Foods schemas
# ---------------------------------------------------------------------------

class FavoriteFoodCreate(BaseModel):
    food_id: uuid.UUID = Field(description="ID của món ăn muốn lưu yêu thích")
    notes: str = Field(default="", description="Ghi chú tuỳ chọn, ví dụ: 'Ăn trưa hợp'")
    rating: Optional[int] = Field(default=None, ge=1, le=5, description="Đánh giá 1–5 sao (để trống nếu chưa muốn đánh giá)")


class FavoriteFoodUpdate(BaseModel):
    notes: Optional[str] = Field(default=None, description="Cập nhật ghi chú")
    rating: Optional[int] = Field(default=None, ge=1, le=5, description="Cập nhật đánh giá 1–5 sao")


class FoodDetail(BaseModel):
    """Thông tin đầy đủ của một món ăn — dùng trong FavoriteFoodResult và các nơi cần embed food."""
    id: uuid.UUID
    name: str
    description: str
    img_url: Optional[str] = None
    core_ingredients: List[str]
    raw_ingredients: List[str]
    raw_instructions: str
    soft_tags: List[str]
    taste_profile: List[str]
    meal_context: List[str]
    occasion_context: List[str]

    model_config = {"from_attributes": True}


class FavoriteFoodResult(BaseModel):
    id: uuid.UUID
    food_id: uuid.UUID
    notes: str
    rating: Optional[int] = None
    created_at: datetime
    food: FoodDetail

    model_config = {"from_attributes": True}


class FavoriteListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[FavoriteFoodResult]


class ShoppingListResponse(BaseModel):
    food_count: int
    ingredient_count: int
    ingredients: List[str]


class FavoriteRecommendationResult(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    img_url: Optional[str] = None
    soft_tags: List[str]
    taste_profile: List[str]
    meal_context: List[str]
    similarity_score: float = Field(description="Độ tương đồng embedding với nhóm yêu thích (0–1)")


# ---------------------------------------------------------------------------
# Chat History schemas
# ---------------------------------------------------------------------------

class ChatThreadCreate(BaseModel):
    """Tạo thread mới — title tuỳ chọn, nếu bỏ trống sẽ auto-gen từ tin nhắn đầu."""
    title: Optional[str] = None


class ChatThreadUpdate(BaseModel):
    """Cập nhật tiêu đề hoặc trạng thái ghim."""
    title: Optional[str] = None
    is_pinned: Optional[bool] = None


class ChatThreadResult(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    title: Optional[str] = None
    is_pinned: bool
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    # Thống kê tổng hợp — tính khi query
    message_count: int = 0
    last_message_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ChatThreadListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[ChatThreadResult]


class ChatMessageResult(BaseModel):
    id: uuid.UUID
    thread_id: uuid.UUID
    role: str  # "user" | "assistant"
    content: str
    query_log_id: Optional[uuid.UUID] = None
    food_results: Optional[List[Dict[str, Any]]] = None
    feedback: Optional[str] = None  # "like" | "dislike" | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatMessageListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[ChatMessageResult]


class MessageFeedbackRequest(BaseModel):
    """👍 / 👎 — gửi null để xoá feedback đã đặt."""
    feedback: Optional[Literal["like", "dislike"]] = Field(
        default=None,
        description="'like' hoặc 'dislike'. Gửi null để xoá feedback.",
    )


class MessageEditRequest(BaseModel):
    """Chỉnh sửa câu hỏi cũ và gửi lại."""
    query: str = Field(min_length=1, description="Nội dung câu hỏi sau khi chỉnh sửa")
    skip_profile: bool = Field(
        default=False,
        description="Bỏ qua hồ sơ sức khỏe cho lần tìm kiếm này",
    )


class ChatSendMessageRequest(BaseModel):
    """Payload gửi tin nhắn mới — backend tự gọi search và lưu cả 2 chiều."""
    query: str = Field(min_length=1, description="Câu hỏi / yêu cầu của người dùng")
    skip_profile: bool = Field(
        default=False,
        description="Bỏ qua hồ sơ sức khỏe đã lưu cho lần tìm kiếm này",
    )


class ChatSendMessageResponse(BaseModel):
    """Response sau khi gửi tin nhắn: trả cả 2 message + kết quả search đầy đủ."""
    user_message: ChatMessageResult
    assistant_message: ChatMessageResult
    search_result: SearchResponse


# ---------------------------------------------------------------------------
# Admin — Food schemas
# ---------------------------------------------------------------------------

class AdminFoodCreate(BaseModel):
    """Payload tạo món ăn mới. Sau khi save, hệ thống tự sinh core_ingredient_keys và embedding."""
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    img_url: Optional[str] = None
    core_ingredients: List[str] = Field(default_factory=list, description="Nguyên liệu chính (không có định lượng)")
    raw_ingredients: List[str] = Field(default_factory=list, description="Nguyên liệu đầy đủ với định lượng")
    raw_instructions: str = Field(default="", description="Các bước hướng dẫn nấu")
    soft_tags: List[str] = Field(default_factory=list)
    taste_profile: List[str] = Field(default_factory=list)
    meal_context: List[str] = Field(default_factory=list)
    occasion_context: List[str] = Field(default_factory=list)


class AdminFoodUpdate(BaseModel):
    """Payload cập nhật món ăn (PATCH — chỉ gửi field cần thay đổi)."""
    name: Optional[str] = None
    description: Optional[str] = None
    img_url: Optional[str] = None
    core_ingredients: Optional[List[str]] = None
    raw_ingredients: Optional[List[str]] = None
    raw_instructions: Optional[str] = None
    soft_tags: Optional[List[str]] = None
    taste_profile: Optional[List[str]] = None
    meal_context: Optional[List[str]] = None
    occasion_context: Optional[List[str]] = None


class AdminFoodResult(BaseModel):
    """Chi tiết đầy đủ món ăn trong context admin (bao gồm core_ingredient_keys và trạng thái embedding)."""
    id: uuid.UUID
    name: str
    description: str
    img_url: Optional[str] = None
    core_ingredients: List[str]
    raw_ingredients: List[str]
    raw_instructions: str
    core_ingredient_keys: List[str]
    soft_tags: List[str]
    taste_profile: List[str]
    meal_context: List[str]
    occasion_context: List[str]
    has_embedding: bool = False  # True nếu vector embedding đã được sinh

    model_config = {"from_attributes": True}


class AdminFoodListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[AdminFoodResult]


class FoodImageUploadResponse(BaseModel):
    food_id: uuid.UUID
    img_url: str


class RebuildEmbeddingResponse(BaseModel):
    food_id: uuid.UUID
    success: bool
    message: str


class RebuildAllEmbeddingsResponse(BaseModel):
    total: int
    success: int
    failed: int
    failed_names: List[str]


# ---------------------------------------------------------------------------
# Admin — Tag / Medical Rule schemas
# ---------------------------------------------------------------------------

class AdminTagCreate(BaseModel):
    name: str = Field(min_length=1, description="Tên tag (ví dụ: Cao huyết áp, Dị ứng tôm cua)")
    tag_type: str = Field(description="Loại tag: 'health' | 'allergy' | 'diet' | 'soft'")
    exclude_soft_tag: List[str] = Field(default_factory=list, description="Tags món ăn cần tránh khi có bệnh này")
    prefer_soft_tag: List[str] = Field(default_factory=list, description="Tags món ăn nên ưu tiên")
    exclude_ingredient: List[str] = Field(default_factory=list, description="Nguyên liệu cần loại trừ")
    prefer_ingredient: List[str] = Field(default_factory=list, description="Nguyên liệu nên ưu tiên")


class AdminTagUpdate(BaseModel):
    name: Optional[str] = None
    tag_type: Optional[str] = None
    exclude_soft_tag: Optional[List[str]] = None
    prefer_soft_tag: Optional[List[str]] = None
    exclude_ingredient: Optional[List[str]] = None
    prefer_ingredient: Optional[List[str]] = None


class AdminTagResult(BaseModel):
    id: uuid.UUID
    name: str
    tag_type: str
    exclude_soft_tag: List[str]
    prefer_soft_tag: List[str]
    exclude_ingredient: List[str]
    prefer_ingredient: List[str]

    model_config = {"from_attributes": True}


class AdminTagListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[AdminTagResult]


# ---------------------------------------------------------------------------
# Admin — User Management schemas
# ---------------------------------------------------------------------------

class AdminUserUpdate(BaseModel):
    role: Optional[Literal["user", "admin"]] = Field(default=None, description="Cập nhật role")
    is_active: Optional[bool] = Field(default=None, description="Khoá / mở khoá tài khoản")
    full_name: Optional[str] = None


class AdminUserListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List["UserResult"]


# ---------------------------------------------------------------------------
# Admin — Import schemas
# ---------------------------------------------------------------------------

class FoodImportItem(BaseModel):
    """Schema một món ăn trong file JSON import."""
    name: str
    description: str
    img_url: Optional[str] = None
    core_ingredients: List[str] = Field(default_factory=list)
    raw_ingredients: List[str] = Field(default_factory=list)
    raw_instructions: str = ""
    soft_tags: List[str] = Field(default_factory=list)
    taste_profile: List[str] = Field(default_factory=list)
    meal_context: List[str] = Field(default_factory=list)
    occasion_context: List[str] = Field(default_factory=list)


class FoodImportPreviewResponse(BaseModel):
    """Kết quả dry-run import — chưa lưu vào DB."""
    total_in_file: int
    valid_count: int
    duplicate_names: List[str]  # Tên đã tồn tại trong DB
    invalid_items: List[Dict[str, Any]]  # Items lỗi validation
    preview_items: List[FoodImportItem]  # Items hợp lệ sẽ được import


class FoodImportApplyResponse(BaseModel):
    """Kết quả sau khi áp dụng import."""
    imported_count: int
    skipped_duplicates: int
    failed_count: int
    failed_names: List[str]


# ---------------------------------------------------------------------------
# Auth schemas
# ---------------------------------------------------------------------------

class AuthSignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, description="Mật khẩu tối thiểu 6 ký tự")
    full_name: Optional[str] = None


class AuthLoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: uuid.UUID
    email: str
    full_name: Optional[str] = None
    role: str


class AuthLogoutResponse(BaseModel):
    success: bool
    message: str


class UserResult(BaseModel):
    id: uuid.UUID
    email: str
    full_name: Optional[str] = None
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# User Health Profile schemas
# ---------------------------------------------------------------------------

class UserHealthProfileCreate(BaseModel):
    """Dùng cho PUT — thay thế toàn bộ profile."""
    health_conditions: List[str] = Field(
        default_factory=list,
        description="Danh sách bệnh lý / điều kiện sức khỏe, ví dụ: ['Cao huyết áp', 'Tiểu đường']",
    )
    allergies: List[str] = Field(
        default_factory=list,
        description="Danh sách dị ứng, ví dụ: ['Dị ứng tôm cua', 'Dị ứng đậu phộng']",
    )
    diet_preferences: List[str] = Field(
        default_factory=list,
        description="Chế độ ăn uống, ví dụ: ['Ít muối', 'Eat Clean', 'Ăn chay']",
    )
    nutrition_goals: List[str] = Field(
        default_factory=list,
        description="Mục tiêu dinh dưỡng, ví dụ: ['Giảm cân', 'Tăng cơ']",
    )
    disliked_ingredients: List[str] = Field(
        default_factory=list,
        description="Nguyên liệu không muốn ăn, ví dụ: ['nội tạng', 'mỡ động vật']",
    )
    preferred_ingredients: List[str] = Field(
        default_factory=list,
        description="Nguyên liệu ưa thích, ví dụ: ['ức gà', 'rau xanh']",
    )
    notes: str = Field(
        default="",
        description="Ghi chú tự do, ví dụ: 'Không ăn cay, không ăn đồ sống'",
    )


class UserHealthProfileUpdate(BaseModel):
    """Dùng cho PATCH — chỉ cập nhật các field được gửi lên."""
    health_conditions: Optional[List[str]] = None
    allergies: Optional[List[str]] = None
    diet_preferences: Optional[List[str]] = None
    nutrition_goals: Optional[List[str]] = None
    disliked_ingredients: Optional[List[str]] = None
    preferred_ingredients: Optional[List[str]] = None
    notes: Optional[str] = None


class UserHealthProfileResult(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    health_conditions: List[str]
    allergies: List[str]
    diet_preferences: List[str]
    nutrition_goals: List[str]
    disliked_ingredients: List[str]
    preferred_ingredients: List[str]
    notes: str
    updated_at: datetime

    model_config = {"from_attributes": True}
