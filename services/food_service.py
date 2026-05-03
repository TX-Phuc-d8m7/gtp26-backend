import os
import json
from google import genai
from google.genai import types
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from models import Food
from schemas import SearchResponse, AIInsight, FoodResult, Filters

PROJECT_ID = os.getenv("PROJECT_ID")
# Dùng vertexai=True theo yêu cầu của user
client = genai.Client(vertexai=True, project=PROJECT_ID, location="us-central1")

VALID_HARD = [
    "Động vật có vỏ", "Hải sản / Cá", "Đậu phộng / Các loại hạt", "Sữa / Lactose", 
    "Đậu nành", "Lúa mì / Gluten", "Trứng", "Cà chua", "Trái cây có múi", "Mè / Vừng", 
    "Đồ sống / Chín tái", "Tiểu đường", "Cao huyết áp", 
    "Bệnh Thận", "Dạ dày / Đại tràng", "Tim mạch / Mỡ máu", 
    "Viêm họng / Ho / Cảm", "Táo bón"
]

VALID_DIET = [
    "Thuần chay", "Chay Phật giáo", "Chay trứng sữa", "Hồi giáo (Halal)", 
    "Keto", "Eat Clean", "DASH / Địa Trung Hải"
]

VALID_SOFT = [
    "Đậm đà", "Thanh đạm", "Chua", "Cay", "Mặn", "Ngọt", "Đắng", "Béo ngậy",
    "Nóng hổi", "Thanh mát / Lạnh", "Món nước", "Món khô / Trộn",
    "Giòn / Giòn rụm", "Dai / Sần sật", "Mềm / Tan trong miệng", "Nước sền sệt",
    "Chiên / Rán", "Nướng", "Hấp / Luộc", "Xào", "Gỏi / Trộn sống",
    "Ăn no", "Ăn vặt", "Mồi nhậu", "Ăn sáng", "Ăn đêm", "Tráng miệng", "Giải rượu", "Giải cảm / Ấm bụng",
    "Đặc sản Đà Nẵng", "Ẩm thực đường phố", "Món Việt truyền thống", "Món Á", "Món Âu"
]

async def extract_intent(query: str):
    prompt = f"""
      ### ROLE
      Bạn là một Chuyên gia Thẩm định Dinh dưỡng và Y tế AI. Nhiệm vụ của bạn là bóc tách ý định người dùng thành các Tags hệ thống một cách an toàn tuyệt đối.

      ### SYSTEM TAXONOMY (Chỉ được chọn từ danh sách này)
      - Hard Tags (Rủi ro): [{', '.join(VALID_HARD)}]
      - Diet Tags (Chế độ ăn): [{', '.join(VALID_DIET)}]
      - Soft Tags (Hương vị/Bối cảnh): [{', '.join(VALID_SOFT)}]

      ### THUẬT TOÁN SUY LUẬN (LOGIC STEPS)
      1. **Medical Detection**: Phân tích mọi dấu hiệu về thực thể (Bà bầu, trẻ em, người bệnh) và triệu chứng (ho, đau bụng, sốt...).
      2. **Risk Mapping**: Sử dụng tri thức y khoa để xác định các Chống chỉ định (Contraindications). Ánh xạ chúng vào [exclude].
      3. **Preference Extraction**: Nhận diện món ăn/hương vị người dùng yêu cầu (Gỏi, cay, nóng...).
      4. **Safety Cross-Check (BẮT BUỘC)**: 
        - So sánh [prefer] với [exclude]. 
        - NẾU bất kỳ Tag nào trong [prefer] vi phạm hoặc thuộc nhóm bị cấm bởi [exclude] -> XÓA BỎ Tag đó khỏi [prefer] ngay lập tức.
        - KHÔNG ĐƯỢC "ba phải". An toàn là tuyệt đối, sở thích là thứ yếu.
      5. **Alternative Suggestion**: Nếu sở thích bị xóa, hãy tự chọn một Tag an toàn trong danh sách Soft Tags để thay thế (VD: Thay "Gỏi" bằng "Hấp / Luộc").

      ### NGUYÊN TẮC VÀNG
      - **Sức khỏe > Yêu cầu**: Một bà bầu đòi ăn gỏi sống thì [exclude] là "Đồ sống / Chín tái" và [prefer] KHÔNG ĐƯỢC chứa "Gỏi / Trộn sống".
      - **Phương ngữ**: Tự động chuyển đổi (Bao tử -> Dạ dày, Lạc -> Đậu phộng, Tào tháo đuổi -> Dạ dày/Đại tràng).

      ### USER QUERY
      "{query}"
    """

    response_schema = {
        "type": "OBJECT",
        "properties": {
            "exclude": {"type": "ARRAY", "items": {"type": "STRING"}},
            "include": {"type": "ARRAY", "items": {"type": "STRING"}},
            "prefer": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
        "required": ["exclude", "include", "prefer"]
    }

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=response_schema,
            temperature=0.1,
        )
    )

    try:
        parsed_data = json.loads(response.text)
        exclude_tags = [t for t in parsed_data.get("exclude", []) if t in VALID_HARD]
        include_tags = [t for t in parsed_data.get("include", []) if t in VALID_DIET]
        prefer_tags = [t for t in parsed_data.get("prefer", []) if t in VALID_SOFT]
        return exclude_tags, include_tags, prefer_tags
    except Exception as e:
        print(f"Lỗi parse JSON: {e}")
        return [], [], []

from sqlalchemy.dialects.postgresql import array

async def search_food(query: str, db: AsyncSession) -> SearchResponse:
    # 1. Trích xuất ý định người dùng bằng LLM
    exclude_tags, include_tags, prefer_tags = await extract_intent(query)
    print(f"Query: {query}")
    print(f"Exclude: {exclude_tags}")
    print(f"Include: {include_tags}")
    print(f"Prefer: {prefer_tags}")

    # 2. Lấy vector embedding cho query (Dùng Vertex AI model text-embedding-004)
    # google-genai client.models.embed_content calls Vertex AI seamlessly
    embedding_response = client.models.embed_content(
        model='text-embedding-004',
        contents=query
    )
    query_vector = embedding_response.embeddings[0].values
    
    # Ép kiểu query_vector về chuỗi để đưa vào SQL
    vector_str = f"[{','.join(map(str, query_vector))}]"

    # 3. Build query tìm kiếm vector
    # Chọn khoảng cách Cosine (<=>)
    stmt = select(Food, Food.embedding.cosine_distance(vector_str).label("distance"))
    
    if exclude_tags:
        # Loại trừ dị ứng: NOT (food.hard_filters ?| ARRAY[...])
        stmt = stmt.where(~Food.hard_filters.has_any(array(exclude_tags)))

    if include_tags:
        # Bắt buộc chế độ ăn: food.dietary_filters ?& ARRAY[...]
        stmt = stmt.where(Food.dietary_filters.has_all(array(include_tags)))

    stmt = stmt.order_by("distance").limit(5)
    
    result = await db.execute(stmt)
    rows = result.all()

    # 4. Format kết quả
    results_list = []
    for row in rows:
        food = row.Food
        distance = row.distance
        match_score = f"{((1 - float(distance)) * 100):.1f}%"
        
        results_list.append(FoodResult(
            id=food.id,
            name=food.name,
            category=food.category,
            description=food.description,
            ingredients=food.ingredients,
            filters=Filters(
                hard=food.hard_filters,
                dietary=food.dietary_filters,
                soft=food.soft_filters
            ),
            matchScore=match_score
        ))

    return SearchResponse(
        query=query,
        ai_insight=AIInsight(
            exclude=exclude_tags,
            include=include_tags,
            prefer=prefer_tags
        ),
        results=results_list
    )
