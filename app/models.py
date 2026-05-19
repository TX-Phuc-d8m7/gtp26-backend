import uuid
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB
from pgvector.sqlalchemy import HALFVEC
from app.db.session import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, nullable=False, unique=True, index=True)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    # role: "user" | "admin"
    role = Column(String, nullable=False, default="user")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

class UserHealthProfile(Base):
    __tablename__ = "user_health_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Mỗi user chỉ có 1 profile — unique constraint
    user_id = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)

    # Bệnh lý / điều kiện sức khỏe: ["Cao huyết áp", "Tiểu đường"]
    health_conditions = Column(ARRAY(Text), nullable=False, default=[])
    # Dị ứng: ["Dị ứng tôm cua", "Dị ứng đậu phộng"]
    allergies = Column(ARRAY(Text), nullable=False, default=[])
    # Chế độ ăn / diet: ["Ít muối", "Eat Clean", "Ăn chay"]
    diet_preferences = Column(ARRAY(Text), nullable=False, default=[])
    # Mục tiêu dinh dưỡng: ["Giảm cân", "Tăng cơ"]
    nutrition_goals = Column(ARRAY(Text), nullable=False, default=[])
    # Nguyên liệu không muốn ăn: ["nội tạng", "mỡ động vật"]
    disliked_ingredients = Column(ARRAY(Text), nullable=False, default=[])
    # Nguyên liệu ưa thích: ["ức gà", "rau xanh"]
    preferred_ingredients = Column(ARRAY(Text), nullable=False, default=[])
    # Ghi chú tự do: "Không ăn cay, không ăn đồ sống"
    notes = Column(Text, nullable=False, default="")

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Food(Base):
    __tablename__ = "foods"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    img_url = Column(String, nullable=True)
    
    core_ingredients = Column(ARRAY(Text), nullable=False, default=[])
    raw_ingredients = Column(ARRAY(Text), nullable=False, default=[])
    raw_instructions = Column(Text, nullable=False, default="")
    core_ingredient_keys = Column(ARRAY(Text), nullable=False, default=[])
    soft_tags = Column(ARRAY(Text), nullable=False, default=[]) 
    taste_profile = Column(ARRAY(Text), nullable=False, default=[])
    meal_context = Column(ARRAY(Text), nullable=False, default=[])
    occasion_context = Column(ARRAY(Text), nullable=False, default=[])
    
    # gemini-embedding-001 need vector 3072 dimension
    embedding = Column(HALFVEC(3072), nullable=True)

class FavoriteFood(Base):
    __tablename__ = "favorite_foods"
    __table_args__ = (
        # Mỗi user chỉ lưu 1 lần cho mỗi món
        UniqueConstraint("user_id", "food_id", name="uq_favorite_user_food"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    food_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    notes = Column(Text, nullable=False, default="")
    # Đánh giá 1-5 sao (nullable = chưa đánh giá)
    rating = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Tag(Base):
    __tablename__ = "tags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, unique=True) 
    tag_type = Column(String, nullable=False)         
    
    # Rule Engine
    exclude_soft_tag = Column(ARRAY(String), nullable=False, default=[])
    prefer_soft_tag = Column(ARRAY(String), nullable=False, default=[])
    exclude_ingredient = Column(ARRAY(String), nullable=False, default=[])
    prefer_ingredient = Column(ARRAY(String), nullable=False, default=[])


class IngredientAliasOverride(Base):
    __tablename__ = "ingredient_alias_overrides"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alias = Column(String, nullable=False)
    alias_key = Column(String, nullable=False, unique=True, index=True)
    canonical_key = Column(String, nullable=False)
    group_keys = Column(ARRAY(Text), nullable=False, default=[])
    enabled = Column(Boolean, nullable=False, default=True)
    notes = Column(Text, nullable=False, default="")


class ChatThread(Base):
    __tablename__ = "chat_threads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    # Tiêu đề thread — auto-gen từ tin nhắn đầu tiên nếu user không đặt
    title = Column(Text, nullable=True)
    is_pinned = Column(Boolean, nullable=False, default=False)
    # Soft delete — không xóa khỏi DB, chỉ ẩn khỏi list
    is_deleted = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    # "user" | "assistant"
    role = Column(String, nullable=False)
    # Nội dung tin nhắn: câu hỏi user hoặc lời tư vấn AI
    content = Column(Text, nullable=False)
    # Liên kết tới QueryLog để tra cứu chi tiết kết quả tìm kiếm
    query_log_id = Column(UUID(as_uuid=True), nullable=True)
    # Danh sách món gợi ý (serialized FoodResult) — chỉ có ở assistant messages
    food_results = Column(JSONB, nullable=True)
    # Phản hồi của user với tin nhắn AI: "like" | "dislike" | None
    feedback = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class QueryLog(Base):
    __tablename__ = "query_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    thread_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    query = Column(Text, nullable=False)
    ai_insight = Column(JSONB, nullable=False, default=dict)
    final_exclude_ings = Column(ARRAY(Text), nullable=False, default=[])
    exclude_ingredient_keys = Column(ARRAY(Text), nullable=False, default=[])
    user_include_tags = Column(ARRAY(Text), nullable=False, default=[])
    user_exclude_tags = Column(ARRAY(Text), nullable=False, default=[])
    candidate_count = Column(Integer, nullable=False, default=0)
    filtered_count = Column(Integer, nullable=False, default=0)
    scored_count = Column(Integer, nullable=False, default=0)
    returned_count = Column(Integer, nullable=False, default=0)
    excluded_summary = Column(JSONB, nullable=False, default=dict)
    retrieval_notes = Column(ARRAY(Text), nullable=False, default=[])
    top_results = Column(JSONB, nullable=False, default=list)
    warning_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
