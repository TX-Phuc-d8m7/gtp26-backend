import os
import json
import asyncio
from google import genai
from google.genai import types
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, not_, text, cast, Text
from sqlalchemy.dialects.postgresql import ARRAY
from models import Food, Tag
from schemas import SearchResponse, AIInsight, FoodResult

PROJECT_ID = os.getenv("PROJECT_ID")
client = genai.Client(vertexai=True, project=PROJECT_ID, location="us-central1")

# =================================
# 1. AGENT & LUỒNG XỬ LÝ XUNG ĐỘT 
# =================================

valid_health_tags = [
    "Vết thương hở/Mới phẫu thuật", "Đang cho con bú", "Phụ nữ mang thai",
    "Gan nhiễm mỡ/Men gan cao", "Béo phì", "Đầy bụng/Khó tiêu",
    "Nhiệt miệng/Loét miệng", "Tiêu chảy", "Gout",
    "Bệnh lý hô hấp trên (Ho/Viêm họng/Cảm/Amidan)", "Táo bón",
    "Tim mạch", "Trào ngược dạ dày thực quản (GERD)", "Viêm loét dạ dày",
    "Suy thận", "Cao huyết áp", "Tiểu đường",
    "Dị ứng mắm lên men", "Dị ứng bột ngọt (MSG)", "Dị ứng mè/vừng",
    "Dị ứng trái cây có múi", "Dị ứng trứng", "Dị ứng cà chua",
    "Dị ứng lúa mì", "Dị ứng đậu nành", "Bất dung nạp Lactose",
    "Dị ứng sữa bò", "Dị ứng hạt cây", "Dị ứng đậu phộng",
    "Dị ứng cá có vây", "Dị ứng động vật thân mềm", "Dị ứng động vật giáp xác"
]
def supervisor_agent(user_input: str):
    system_instruction = f"""
    Bạn là chuyên gia phân tích ý định người dùng trong ẩm thực.
    Nhiệm vụ: Trích xuất thông tin sức khỏe và sở thích ăn uống.

    [DANH SÁCH TAG SỨC KHỎE HỢP LỆ]
    {valid_health_tags}

    [QUY TẮC PHÂN LOẠI]
    1. health_constraints: Chỉ chọn từ danh sách trên. Map các từ đồng nghĩa (VD: đau dạ dày -> Viêm loét dạ dày).
    2. exclude_ingredients: Danh sách các nguyên liệu người dùng KHÔNG MUỐN.
    3. include_ingredients: Danh sách các nguyên liệu người dùng CẢM THẤY THÍCH.
    """

    response_schema = {
        "type": "OBJECT",
        "properties": {
            "health_constraints": {
                "type": "ARRAY",
                "items": {"type": "STRING", "enum": valid_health_tags}
            },
            "exclude_ingredients": {"type": "ARRAY", "items": {"type": "STRING"}},
            "include_ingredients": {"type": "ARRAY", "items": {"type": "STRING"}},
            "analysis_note": {"type": "STRING"}
        },
        "required": ["health_constraints", "exclude_ingredients", "include_ingredients"]
    }

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=response_schema
            ),
            contents=user_input
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"Lỗi Gemini: {e}")
        return {"error": str(e)}

async def resolve_food_conflicts(user_input: str, db: AsyncSession):
    extracted_data = await asyncio.to_thread(supervisor_agent, user_input)
    if "error" in extracted_data:
        return None

    symptoms = extracted_data.get("health_constraints", [])
    user_likes_ings = set(extracted_data.get("include_ingredients", []))
    user_dislikes_ings = set(extracted_data.get("exclude_ingredients", []))

    medical_exclude_tags = set()
    medical_prefer_tags = set()
    medical_exclude_ings = set()
    medical_prefer_ings = set()

    if symptoms:
        stmt = select(Tag).where(Tag.name.in_(symptoms))
        result = await db.execute(stmt)
        tags_db = result.scalars().all()

        for tag in tags_db:
            medical_exclude_tags.update(tag.exclude_soft_tag)
            medical_prefer_tags.update(tag.prefer_soft_tag)
            medical_exclude_ings.update(tag.exclude_ingredient)
            medical_prefer_ings.update(tag.prefer_ingredient)

    user_likes_lower = {ing.lower() for ing in user_likes_ings}
    medical_exclude_lower = {ing.lower() for ing in medical_exclude_ings}
    
    conflicting_ings = user_likes_lower.intersection(medical_exclude_lower)
    warning_message = None
    
    if conflicting_ings:
        user_likes_lower.difference_update(medical_exclude_lower)
        warning_message = f"Hệ thống phát hiện bạn muốn ăn {', '.join(conflicting_ings)}, nhưng với tình trạng ({', '.join(symptoms)}), bạn cần kiêng chúng để đảm bảo an toàn."

    return {
        "symptoms": symptoms,
        "final_exclude_ings": list(user_dislikes_ings.union(medical_exclude_ings)),
        "final_include_ings": list(user_likes_lower),
        "medical_exclude_tags": list(medical_exclude_tags),
        "medical_prefer_tags": list(medical_prefer_tags),
        "warning_message": warning_message
    }

async def extract_intent(query: str):
    """
    Sử dụng LLM để bóc tách Tường minh (Explicit) yêu cầu của User
    """
    prompt = f"""
      ### ROLE
      Bạn là một Chuyên gia phân tích ẩm thực và y khoa AI. Nhiệm vụ của bạn là bóc tách câu nói của người dùng thành các trường dữ liệu cụ thể.

      ### USER QUERY
      "{query}"

      ### YÊU CẦU TRÍCH XUẤT (JSON FORMAT)
      - symptoms: Các bệnh lý, triệu chứng sức khỏe user đề cập (VD: Đau dạ dày, tiểu đường, nhiệt miệng). Không có thì để rỗng.
      - prefer_soft_tags: Các tính chất, hương vị món ăn user MONG MUỐN (VD: Chua, Cay, Thanh mát, Món nước).
      - prefer_ingredients: Các nguyên liệu hoặc món ăn cụ thể user MONG MUỐN (VD: lẩu thái, thịt bò, nấm).
      - exclude_ingredients: Các nguyên liệu user KHÔNG THÍCH hoặc DỊ ỨNG (VD: thịt gà, hành, tiêu).
      - exclude_soft_tags: Các tính chất user KHÔNG THÍCH (VD: Mặn, Dầu mỡ).
    """

    response_schema = {
        "type": "OBJECT",
        "properties": {
            "symptoms": {"type": "ARRAY", "items": {"type": "STRING"}},
            "prefer_soft_tags": {"type": "ARRAY", "items": {"type": "STRING"}},
            "prefer_ingredients": {"type": "ARRAY", "items": {"type": "STRING"}},
            "exclude_ingredients": {"type": "ARRAY", "items": {"type": "STRING"}},
            "exclude_soft_tags": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
        "required": ["symptoms", "prefer_soft_tags", "prefer_ingredients", "exclude_ingredients", "exclude_soft_tags"]
    }

    # Bọc trong to_thread để không làm đơ Event Loop của FastAPI
    def call_gemini():
        return client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=response_schema,
                temperature=0.1,
            )
        )

    response = await asyncio.to_thread(call_gemini)

    try:
        return json.loads(response.text)
    except Exception as e:
        print(f"❌ Lỗi parse JSON LLM: {e}")
        return {"symptoms": [], "prefer_soft_tags": [], "prefer_ingredients": [], "exclude_ingredients": [], "exclude_soft_tags": []}

# =====================================================================
# 2. HÀM TÌM KIẾM CHÍNH (Được gọi từ API)
# =====================================================================

async def search_food(query: str, db: AsyncSession) -> SearchResponse:
    # Bước 1: Chạy luồng bảo vệ và xử lý xung đột
    payload = await resolve_food_conflicts(query, db)
    
    if not payload:
        # Xử lý fallback nếu LLM tịt ngòi
        return SearchResponse(query=query, ai_insight=AIInsight(exclude=[], include=[], prefer=[]), results=[])

    symptoms = payload["symptoms"]
    final_e_ings = payload["final_exclude_ings"]
    final_p_ings = payload["final_include_ings"]
    medical_e_tags = payload["medical_exclude_tags"]
    medical_p_tags = payload["medical_prefer_tags"]
    warning_message = payload["warning_message"]

    # Bước 2: Tối ưu Embedding Payload (Query Expansion)
    query_parts = ["Tìm món ăn"]
    if medical_p_tags: query_parts.append(f"có tính chất {', '.join(medical_p_tags)}")
    if final_p_ings: query_parts.append(f"có chứa {', '.join(final_p_ings)}")
    query_parts.append(f"Yêu cầu gốc: {query}")

    expanded_query = ". ".join(query_parts)
    print(f"🔎 EXPANDED QUERY: {expanded_query}")

    # 3. Nhúng Vector (Embedding)
    def get_embedding():
        return client.models.embed_content(
            model='gemini-embedding-001',
            contents=expanded_query
        )
    
    embedding_response = await asyncio.to_thread(get_embedding)
    query_vector = embedding_response.embeddings[0].values

    # 6. SQL Dynamic Builder với Toán tử OVERLAP
    stmt = select(Food, Food.embedding.cosine_distance(query_vector).label("distance"))
    
    # Bộ lọc Cứng: KHÔNG CHỨA (NOT overlap) các tính chất bị cấm
    if medical_e_tags:
        stmt = stmt.where(not_(Food.soft_tags.overlap(cast(medical_e_tags, ARRAY(Text)))))

    # Bộ lọc Cứng: KHÔNG CHỨA (NOT overlap) các nguyên liệu bị cấm
    if final_e_ings:
        stmt = stmt.where(not_(Food.core_ingredients.overlap(cast(final_e_ings, ARRAY(Text)))))

    # Lấy top 5 khớp nhất
    stmt = stmt.order_by("distance").limit(5)
    
    db_result = await db.execute(stmt)
    rows = db_result.all()

    # 7. Map dữ liệu về Pydantic Schemas mới
    results_list = []
    for row in rows:
        food = row.Food
        distance = row.distance
        match_score = float((1 - float(distance)) * 100)
        
        results_list.append(FoodResult(
            id=food.id,
            name=food.name,
            description=food.description,
            img_url=food.img_url,  # Đã map chuẩn ERD
            core_ingredients=food.core_ingredients,
            soft_tags=food.soft_tags,
            matchScore=match_score
        ))

    return SearchResponse(
        query=query,
        ai_insight=AIInsight(
            exclude=medical_e_tags + final_e_ings,
            include=symptoms, # Trả về list bệnh lý để UI dễ hiển thị Warning
            prefer=medical_p_tags + final_p_ings,
            warning_message=warning_message
        ),
        results=results_list
    )