import os
import json
import asyncio
import numpy as np
from google import genai
from google.genai import types
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select, not_, text, cast, Text
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

valid_soft_tags = [
    "Đậm đà", "Thanh đạm", "Chua", "Cay", "Mặn", "Ngọt", "Đắng", "Béo ngậy",
    "Nóng hổi", "Thanh mát/Giải nhiệt", "Món nước", "Món khô", "Nước sền sệt", "Món lạnh", "Sống/Chín tái",
    "Giòn / Giòn rụm", "Dai / Sần sật", "Mềm", 
    "Chiên / Rán", "Nướng", "Hấp / Luộc", "Xào", "Gỏi / Nộm / Trộn", "Cuốn / Gói", "Hầm / Ninh", "Lẩu", "Kho/Rim", "Súp", "Cháo", "Rang",
    "Ăn no", "Ăn vặt", "Mồi nhậu", "Ăn sáng", "Ăn trưa", "Ăn chiều / xế", "Ăn tối", "Ăn khuya", "Tráng miệng", "Giải rượu", "Giải cảm", "Ấm bụng",
    "Đặc sản Đà Nẵng", "Ẩm thực đường phố", "Món Việt truyền thống", "Món Á", "Món Âu", "Thức ăn nhanh", "Món chay",
    "Giàu chất xơ", "Giàu đạm", "Giàu vitamin", "Giàu tinh bột", "Nội tạng", "Sữa / Phô mai", "Thực phẩm chế biến sẵn", "Bánh ngọt",
    "Dễ tiêu", "Khó tiêu / Nặng bụng"
]

DISH_TYPE_TAGS = {
    "Lẩu", "Nướng", "Cháo", "Súp", "Gỏi / Nộm / Trộn", 
    "Cuốn / Gói", "Kho/Rim", "Chiên / Rán", "Hấp / Luộc", "Xào", "Rang"
}

def supervisor_agent(user_input: str):
    system_instruction = f"""
    Bạn là chuyên gia phân tích ý định người dùng trong ẩm thực.
    Nhiệm vụ: Trích xuất thông tin sức khỏe và sở thích ăn uống.

    [DANH SÁCH TAG SỨC KHỎE HỢP LỆ]
    {valid_health_tags}

    [DANH SÁCH TÍNH CHẤT (SOFT TAGS) HỢP LỆ]
    {valid_soft_tags}

    [QUY TẮC PHÂN LOẠI]
    1. health_constraints: Chỉ chọn từ danh sách trên. Map các từ đồng nghĩa (VD: đau dạ dày -> Viêm loét dạ dày).
    2. include_dishes: Tên các món ăn hoàn chỉnh người dùng muốn (VD: phở bò, lẩu thái, pizza).
    3. exclude_dishes: Tên các món ăn hoàn chỉnh KHÔNG muốn ăn.
    4. exclude_ingredients: Danh sách các nguyên liệu người dùng KHÔNG MUỐN.
    5. include_ingredients: Danh sách các nguyên liệu người dùng CẢM THẤY THÍCH.
    6. include_soft_tags: Tính chất, hương vị người dùng MUỐN. BẮT BUỘC map vào danh sách hợp lệ (VD: "đồ nước" -> "Món nước", "thanh mát" -> "Thanh mát/Giải nhiệt").
    7. exclude_soft_tags: Tính chất, hương vị KHÔNG MUỐN (VD: "không dầu mỡ" -> "Chiên / Rán" hoặc "Béo ngậy"). BẮT BUỘC map vào danh sách.
    """

    response_schema = {
        "type": "OBJECT",
        "properties": {
            "health_constraints": {
                "type": "ARRAY",
                "items": {"type": "STRING", "enum": valid_health_tags}
            },
            "include_dishes": {"type": "ARRAY", "items": {"type": "STRING"}},
            "exclude_dishes": {"type": "ARRAY", "items": {"type": "STRING"}},
            "include_ingredients": {"type": "ARRAY", "items": {"type": "STRING"}},
            "exclude_ingredients": {"type": "ARRAY", "items": {"type": "STRING"}},
            "include_soft_tags": {
                "type": "ARRAY",
                "items": {"type": "STRING", "enum": valid_soft_tags}
            },
            "exclude_soft_tags": {
                "type": "ARRAY",
                "items": {"type": "STRING", "enum": valid_soft_tags}
            },
            "analysis_note": {"type": "STRING"}
        },
        "required": [
            "health_constraints", "include_dishes", "exclude_dishes", 
            "include_ingredients", "exclude_ingredients", 
            "include_soft_tags", "exclude_soft_tags"
        ]
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

    user_include_dishes = extracted_data.get("include_dishes", [])
    user_exclude_dishes = extracted_data.get("exclude_dishes", [])

    user_likes_ings = set(extracted_data.get("include_ingredients", []))
    user_dislikes_ings = set(extracted_data.get("exclude_ingredients", []))

    user_include_tags = set(extracted_data.get("include_soft_tags", []))
    user_exclude_tags = set(extracted_data.get("exclude_soft_tags", []))

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

    # Logic check warning message for ingredients
    user_likes_lower = {ing.lower() for ing in user_likes_ings}
    medical_exclude_lower = {ing.lower() for ing in medical_exclude_ings}
    conflicting_ings = user_likes_lower.intersection(medical_exclude_lower)

    # Logic check warning message for soft tags
    user_tags_lower = {tag.lower() for tag in user_include_tags}
    medical_exclude_tags_lower = {tag.lower() for tag in medical_exclude_tags}
    conflicting_tags = user_tags_lower.intersection(medical_exclude_tags_lower)
    warning_message = None
    
    all_conflicts = list(conflicting_ings) + list(conflicting_tags)
    warning_message = None
    if all_conflicts:
        warning_message = f"Hệ thống phát hiện bạn muốn ăn đồ có ({', '.join(all_conflicts)}), nhưng với tình trạng ({', '.join(symptoms)}), bạn cần kiêng chúng để đảm bảo an toàn."

    return {
        "symptoms": symptoms,
        "final_exclude_ings": list(user_dislikes_ings.union(medical_exclude_ings)),
        "final_include_ings": list(user_likes_lower),
        "medical_exclude_tags": list(medical_exclude_tags),
        "medical_prefer_tags": list(medical_prefer_tags),
        "medical_prefer_ings": list(medical_prefer_ings),
        "user_include_tags": list(user_include_tags),
        "user_exclude_tags": list(user_exclude_tags),
        "user_include_dishes": user_include_dishes,
        "user_exclude_dishes": user_exclude_dishes,
        "warning_message": warning_message
    }

# =====================================================================
# 3. POST-PROCESSING AGENT (Tư vấn ẩm thực tự nhiên với Dynamic Rule Injection)
# =====================================================================

# Load file luật một lần khi khởi động server (tránh đọc file lặp lại mỗi request)
_ADVICE_RULES_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "medical_advice_rules.json")
with open(_ADVICE_RULES_PATH, "r", encoding="utf-8") as _f:
    MEDICAL_ADVICE_RULES: dict = json.load(_f)

def post_processing_agent(
    user_query: str,
    user_symptoms: list[str],
    top5_foods: list  # List[FoodResult] - Pydantic objects
) -> str:
    """
    Dynamic Rule Injection Agent:
    1. Thu thập tất cả soft_tags + core_ingredients của Top 5 món
    2. Đối chiếu với medical_advice_rules.json theo từng bệnh lý của user
    3. Tổng hợp các cảnh báo phù hợp -> Bơm vào prompt -> Gọi LLM
    """

    # --- Bước 1: Thu thập tags & ingredients từ Top 5 ---
    all_tags: set[str] = set()
    all_ingredients: set[str] = set()
    foods_summary = []

    for food in top5_foods:
        all_tags.update(food.soft_tags)
        all_ingredients.update(food.core_ingredients)
        foods_summary.append({
            "name": food.name,
            "tags": food.soft_tags,
            "score": round(food.matchScore, 1)
        })

    print(f"\n[POST-PROCESSING] All tags from top5: {all_tags}")

    # --- Bước 2 & 3: Đối chiếu luật & Tổng hợp cảnh báo ---
    collected_warnings: list[str] = []
    general_advices: list[str] = []

    for symptom in user_symptoms:
        rule = MEDICAL_ADVICE_RULES.get(symptom)
        if not rule:
            print(f"  [POST-PROCESSING] Không có luật cho bệnh: {symptom}")
            continue

        general_advices.append(f"({symptom}) {rule['general_advice']}")

        for cond in rule.get("conditional_warnings", []):
            trigger_type = cond["trigger_type"]
            trigger_val  = cond["trigger_value"]

            matched = False
            if trigger_type == "soft_tag" and trigger_val in all_tags:
                matched = True
            elif trigger_type == "ingredient" and trigger_val in all_ingredients:
                matched = True

            if matched:
                collected_warnings.append(cond["warning_text"])
                print(f"  ✅ Trigger khớp [{symptom}]: '{trigger_val}' -> Bơm cảnh báo")

    # --- Bước 4: Tổng hợp medical_warnings ---
    medical_warnings = "\n".join(
        [f"- {w}" for w in collected_warnings]
    ) if collected_warnings else "(Không có cảnh báo đặc biệt nào cho các món được gợi ý.)"

    foods_text = json.dumps(foods_summary, ensure_ascii=False, indent=2)
    symptoms_text = ", ".join(user_symptoms) if user_symptoms else "Không có bệnh lý đặc biệt"

    # --- Bước 4: Bơm luật vào Prompt (Dynamic Rule Injection) ---
    system_prompt = f"""\
Bạn là chuyên gia tư vấn dinh dưỡng và ẩm thực tận tâm tại Đà Nẵng.
Nhiệm vụ: Dựa vào dữ liệu có sẵn, hãy tư vấn người dùng một cách gần gũi, ấm áp.

[Tình trạng sức khỏe của người dùng]
{symptoms_text}

[Top món ăn an toàn được đề xuất]
{foods_text}

[Hướng dẫn cách ăn bắt buộc phải áp dụng]
{medical_warnings}

[QUY TẮc VIẾT]
- Viết trong khoảng 150-200 chữ. Không dài hơn.
- Thể hiện sự thấu hiểu tình trạng sức khỏe của người dùng.
- Giới thiệu 1-2 món nổi bật và giải thích ngắn gọn lợi ích.
- BẮt buộc đưa vào lời khuyn cách ăn từ [Hướng dẫn cách ăn bắt buộc phải áp dụng] nếu có.
- Giọng điệu tư vấn gần gũi, không liệt kê robot, không dùng bullet point, viết thành đoạn văn liền mạch.
"""

    # --- Bước 5: Gọi LLM ---
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.5,
            ),
            contents=f"Câu hỏi gốc của người dùng: {user_query}"
        )
        return response.text.strip()
    except Exception as e:
        print(f"[POST-PROCESSING] Lỗi LLM: {e}")
        return ""

# =====================================================================
# 2. HÀM TÌM KIẾM CHÍNH (Được gọi từ API)
# =====================================================================

async def search_food(query: str, db: AsyncSession) -> SearchResponse:
    # Bước 1: Chạy luồng bảo vệ và xử lý xung đột
    payload = await resolve_food_conflicts(query, db)

    # ---------------------------------------------------------
    if payload:
        print("\n" + "="*50)
        print("🎯 KẾT QUẢ TỪ AGENT & XỬ LÝ XUNG ĐỘT:")
        print(json.dumps(payload, ensure_ascii=False, indent=4))
        print("="*50 + "\n")
    else:
        print("❌ Payload trả về rỗng (Có lỗi từ LLM)")
    # ---------------------------------------------------------
    
    if not payload:
        # Xử lý fallback nếu LLM tịt ngòi
        return SearchResponse(query=query, ai_insight=AIInsight(exclude=[], include=[], prefer=[]), results=[])
    
    user_exclude_dishes = payload["user_exclude_dishes"]

    symptoms = payload["symptoms"]
    final_e_ings = payload["final_exclude_ings"]
    final_p_ings = payload["final_include_ings"]
    medical_e_tags = payload["medical_exclude_tags"]
    medical_p_tags = payload["medical_prefer_tags"]
    medical_p_ings = payload.get("medical_prefer_ings", [])

    user_include_tags = payload["user_include_tags"]
    user_include_dishes = payload["user_include_dishes"]
    warning_message = payload["warning_message"]

    # Bước 2: Xây dựng Enriched Query
    # Bắt đầu từ câu hỏi GỐC của user, bổ sung prefer context từ y khoa
    # Không dùng template nhân tạo vì embedding cần hiểu ngữ cảnh tự nhiên
    enriched_parts = [query]

    # Ưu tiên tên món nếu user yêu cầu cụ thể
    if user_include_dishes:
        enriched_parts.append(f"Tên món: {', '.join(user_include_dishes)}")

    # Bổ sung tính chất ưa thích (gộp user + y khoa)
    combined_prefer_tags = list(set(user_include_tags + medical_p_tags))
    if combined_prefer_tags:
        enriched_parts.append(f"Ưu tiên các món có tính chất: {', '.join(combined_prefer_tags)}")

    # Bổ sung nguyên liệu ưa thích (gộp user + y khoa)
    all_prefer_ings = list(set(final_p_ings + medical_p_ings))
    if all_prefer_ings:
        enriched_parts.append(f"Ưu tiên nguyên liệu: {', '.join(all_prefer_ings)}")

    expanded_query = ". ".join(enriched_parts)
    print(f"🔎 ENRICHED QUERY: {expanded_query}")

    # 3. Nhúng Vector (Embedding)
    def get_embedding():
        return client.models.embed_content(
            model='gemini-embedding-001',
            contents=expanded_query,
            config=types.EmbedContentConfig(
                output_dimensionality=3072,
                task_type="RETRIEVAL_QUERY"  # Đây là câu hỏi tìm kiếm, khớp với RETRIEVAL_DOCUMENT của món ăn
            )
        )
    
    embedding_response = await asyncio.to_thread(get_embedding)
    query_vector = embedding_response.embeddings[0].values

    # Bước 3: SQL — Chỉ lọc tập món ăn hợp lệ (loại exclude_ingredients + exclude_dishes)
    # Không dùng cosine_distance trong SQL — vector search sẽ thực hiện in-memory ở bước sau
    stmt = select(Food)

    if final_e_ings:
        for bad_ing in final_e_ings:
            # Ép mảng core_ingredients thành chuỗi rồi dùng ILIKE để lọc từ khóa con
            # VD: bad_ing = "ớt" -> chặn "ớt khô", "tương ớt", "muối ớt xanh"
            ing_string = func.array_to_string(Food.core_ingredients, ',')
            stmt = stmt.where(not_(ing_string.ilike(f"%{bad_ing}%")))

    if user_exclude_dishes:
        for dish in user_exclude_dishes:
            stmt = stmt.where(not_(Food.name.ilike(f"%{dish}%")))

    db_result = await db.execute(stmt)
    # Đây là tập món ăn sạch sau khi lọc — vector search sẽ chạy trên tập này
    filtered_foods = db_result.scalars().all()

    print(f"\n{'='*60}")
    print(f"📦 [BƯỚC 3 - SQL FILTER] Còn lại {len(filtered_foods)} món sau khi loại exclude_ingredients:")
    for i, food in enumerate(filtered_foods, 1):
        print(f"  {i:>3}. {food.name}")
    print(f"{'='*60}\n")

    # Bước 4: In-memory Vector Search trên tập đã lọc
    query_arr = np.array(query_vector, dtype=np.float32)
    query_norm = np.linalg.norm(query_arr)

    # 🛡️ CHUẨN HÓA DANH SÁCH CẤM (Viết thường, xóa toàn bộ khoảng trắng)
    # Gộp cả tag cấm của y tế (medical_e_tags) và tag user không thích (user_exclude_tags)
    all_banned_tags = medical_e_tags + payload.get("user_exclude_tags", [])
    banned_tags_normalized = {t.lower().replace(" ", "") for t in all_banned_tags}

    print(f"🔢 [BƯỚC 4 - COSINE SIMILARITY] Tính điểm từng món:")
    scored = []
    for food in filtered_foods:
        if not food.embedding:
            print(f"  ⚠️  {food.name}: BỎ QUA (không có embedding)")
            continue

        # 🛡️ LƯỚI LỌC PHÒNG NGỰ: Chuẩn hóa soft_tags của món ăn hiện tại
        f_tags_normalized = {t.lower().replace(" ", "") for t in food.soft_tags}

        # 🛡️ KIỂM TRA VI PHẠM: Nếu giao nhau với danh sách cấm -> Loại bỏ lập tức
        conflict_tags = f_tags_normalized.intersection(banned_tags_normalized)
        if conflict_tags:
            print(f"  ❌ {food.name}: BỊ CHẶN BỞI PYTHON (Vi phạm tag: {conflict_tags})")
            continue # Đá văng, không tính điểm vector nữa

        # Nếu an toàn, bắt đầu tính toán Cosine Similarity
        food_arr = np.array(food.embedding.to_list(), dtype=np.float32)
        food_norm = np.linalg.norm(food_arr)
        if food_norm == 0 or query_norm == 0:
            print(f"  ⚠️  {food.name}: BỎ QUA (vector = 0)")
            continue
        
        # Cosine similarity = dot / (||a|| * ||b||)
        similarity = float(np.dot(query_arr, food_arr) / (query_norm * food_norm))
        scored.append((food, similarity))
        print(f"  📊 {food.name}: {similarity:.4f} ({similarity*100:.2f}%)")

    # Sắp xếp giảm dần theo similarity, lấy top 5
    scored.sort(key=lambda x: x[1], reverse=True)
    top5 = scored[:5]

    print(f"\n{'='*60}")
    print(f"🏆 [BƯỚC 5 - KẾT QUẢ CUỐI] Top {len(top5)} món phù hợp nhất:")
    for rank, (food, similarity) in enumerate(top5, 1):
        print(f"  #{rank} [{similarity*100:.2f}%] {food.name}")
        print(f"       Tags: {food.soft_tags}")
    print(f"{'='*60}\n")

    # Bước 6: Map kết quả về Pydantic Schemas
    results_list = []
    for food, similarity in top5:
        match_score = similarity * 100
        results_list.append(FoodResult(
            id=food.id,
            name=food.name,
            description=food.description,
            img_url=food.img_url,
            core_ingredients=food.core_ingredients,
            soft_tags=food.soft_tags,
            matchScore=match_score
        ))

    # Bước 7: Post-processing Agent (Dynamic Rule Injection)
    # Nhận top5 đã map sang Pydantic, chạy agent tư vấn tự nhiên
    ai_response_text = await asyncio.to_thread(
        post_processing_agent,
        query,          # Câu hỏi gốc
        symptoms,       # Danh sách bệnh lý
        results_list    # Top 5 FoodResult objects
    )

    return SearchResponse(
        query=query,
        ai_insight=AIInsight(
            exclude=medical_e_tags + final_e_ings,
            include=symptoms, # Trả về list bệnh lý để UI dễ hiển thị Warning
            prefer=medical_p_tags + final_p_ings,
            warning_message=warning_message
        ),
        results=results_list,
        ai_response=ai_response_text or None
    )