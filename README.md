# Food Recommendation Backend

Backend này là API gợi ý món ăn theo câu hỏi tự nhiên của người dùng. Hệ thống kết hợp FastAPI, PostgreSQL/pgvector, Gemini LLM, rule y tế và vector search để trả về danh sách món ăn phù hợp với sở thích, bệnh lý, dị ứng và ngữ cảnh ăn uống.

## Công nghệ chính

- FastAPI: xây dựng REST API.
- SQLAlchemy Async: truy cập PostgreSQL bất đồng bộ.
- PostgreSQL + pgvector: lưu món ăn, tag y tế và embedding vector.
- Gemini 2.5 Flash: phân tích ý định người dùng và sinh lời tư vấn.
- Gemini embedding: tạo vector cho món ăn và query tìm kiếm.
- Ingredient key alias system: chuẩn hóa nguyên liệu thành `base:*`, `canon:*`, `group:*` để filter chính xác hơn.
- Hybrid retrieval/rerank nội bộ: kết hợp SQL filter, ingredient priority, category context, cosine similarity và rule-based scoring.
- Python scripts: relabel món ăn, chuẩn hóa nguyên liệu, sinh rule gợi ý.

## Cách chạy backend

```bash
source venv/bin/activate
python -m uvicorn main:app --reload
```

API docs:

```text
http://127.0.0.1:8000/docs
```

Endpoint chính:

```text
GET /foods/search?q=<câu hỏi người dùng>
```

Endpoint admin hiện có:

```text
GET    /admin/ingredient-alias-overrides
POST   /admin/ingredient-alias-overrides
PATCH  /admin/ingredient-alias-overrides/{id}
DELETE /admin/ingredient-alias-overrides/{id}
POST   /admin/ingredient-alias-overrides/rebuild-food-keys
```

Ví dụ:

```text
/foods/search?q=Tôi bị đau dạ dày, muốn ăn món nước nhẹ bụng
```

## Cấu trúc chính

```text
backend/
├── main.py
├── database.py
├── models.py
├── schemas.py
├── routers/
│   └── admin_alias_overrides.py
├── services/
│   ├── food_service.py
│   ├── ingredient_key_service.py
│   └── seed_service.py
├── scripts/
│   ├── generate_ingredient_key_preview.py
│   ├── relabel_soft_tags.py
│   ├── split_food_categories.py
│   ├── generate_disease_rules_langchain.py
│   └── build_ingredient_guardrail_pipeline.py
├── standard-data/
│   ├── tags_data.json
│   ├── alias-rules/
│   ├── generated-rules/medical-advice-rules/
│   └── ingredients-data/food-clean-categorized/
└── docs/
    └── backend_api_todo.md
```

## Luồng khởi động

Khi chạy server, `main.py` tạo FastAPI app và chạy `lifespan`.

Trong `lifespan`, hệ thống:

1. Kết nối database.
2. Tạo extension `vector` nếu chưa có.
3. Tạo bảng từ SQLAlchemy models nếu chưa có.
4. Gọi `seed_data()` để đồng bộ dữ liệu.

## Dữ liệu database

### Bảng `foods`

Định nghĩa trong `models.py`.

Lưu thông tin món ăn:

- `name`: tên món.
- `description`: mô tả món.
- `img_url`: ảnh món, hiện optional.
- `core_ingredients`: nguyên liệu thực sự cấu thành món.
- `raw_ingredients`: nguyên liệu gốc có định lượng/ghi chú từ dữ liệu crawl.
- `raw_instructions`: hướng dẫn nấu gốc từ dữ liệu crawl.
- `core_ingredient_keys`: key nguyên liệu dạng `base:*`, `canon:*`, `group:*` dùng cho lọc SQL.
- `soft_tags`: nhãn mô tả món ăn.
- `taste_profile`: nhóm vị chủ đạo.
- `meal_context`: bữa/thời điểm ăn phù hợp.
- `occasion_context`: ngữ cảnh sử dụng món.
- `embedding`: vector 3072 chiều từ Gemini embedding.

### Bảng `tags`

Lưu rule y tế theo bệnh lý/dị ứng:

- `name`: tên bệnh lý hoặc dị ứng.
- `tag_type`: loại tag, ví dụ `ALLERGY`, `DISEASE`, `STATUS`.
- `exclude_soft_tag`: soft tag cần tránh.
- `prefer_soft_tag`: soft tag nên ưu tiên.
- `exclude_ingredient`: nguyên liệu cần tránh.
- `prefer_ingredient`: nguyên liệu nên ưu tiên.

### Bảng `ingredient_alias_overrides`

Lưu alias nguyên liệu do Admin bổ sung:

- `alias`: tên nguyên liệu admin nhập, ví dụ `thịt bò Úc`.
- `alias_key`: key không dấu để chống trùng.
- `canonical_key`: canon đích, ví dụ `canon:thit_bo`.
- `group_keys`: nhóm rộng hơn, ví dụ `group:thit_bo`, `group:thit_do`.
- `enabled`: bật/tắt override.
- `notes`: ghi chú review.

Các override này được dùng cùng baseline alias rules để sinh lại `core_ingredient_keys`.

## Luồng seed dữ liệu

File chính: `services/seed_service.py`.

Khi backend khởi động, `seed_data()` thực hiện:

1. Đọc `standard-data/tags_data.json`.
2. Đồng bộ rule y tế vào bảng `tags`.
3. Đọc file clean categorized:
   `standard-data/ingredients-data/food-clean-categorized/raw_foods_enriched_labeled(final_488).categorized.clean.json`.
4. Đồng bộ món ăn vào bảng `foods`.
5. Sinh `core_ingredient_keys` bằng `services/ingredient_key_service.py`.
6. Nếu field dùng cho embedding thay đổi, reset `embedding = None`.
7. Với món chưa có embedding, gọi Gemini `gemini-embedding-001` để tạo vector.

Lưu ý: `raw_ingredients`, `raw_instructions`, và `core_ingredient_keys` là field lưu trữ/filter; thay đổi các field này không cần reset embedding nếu phần text dùng để embedding không đổi.

## Luồng tìm kiếm món ăn

File chính: `services/food_service.py`.

Khi gọi `/foods/search`, hệ thống chạy qua các bước:

### 1. Phân tích câu hỏi người dùng

`supervisor_agent()` gọi Gemini để trích xuất:

- bệnh lý/dị ứng: `health_constraints`
- món muốn ăn: `include_dishes`
- món không muốn ăn: `exclude_dishes`
- nguyên liệu thích: `include_ingredients`
- nguyên liệu không thích: `exclude_ingredients`
- soft tag muốn có: `include_soft_tags`
- soft tag không muốn có: `exclude_soft_tags`

Ví dụ câu:

```text
Tôi bị gout, muốn ăn món nước nhưng không ăn hải sản
```

có thể được phân tích thành:

```json
{
  "health_constraints": ["Gout"],
  "include_soft_tags": ["Món nước"],
  "exclude_soft_tags": ["Hải sản"]
}
```

### 2. Xử lý xung đột y tế

`resolve_food_conflicts()` lấy bệnh lý đã trích xuất, tra bảng `tags`, rồi tổng hợp:

- nguyên liệu cần chặn từ bệnh lý/dị ứng.
- soft tag cần tránh.
- nguyên liệu nên ưu tiên.
- soft tag nên ưu tiên.
- cảnh báo nếu sở thích người dùng xung đột với bệnh lý.

Logic hiện tại đã tách dị ứng khỏi soft tag:

- Với `ALLERGY`, hệ thống ưu tiên chặn bằng `exclude_ingredient`.
- Không dùng `exclude_soft_tag` rộng như `Hải sản` để chặn dị ứng, vì dễ loại nhầm món cá khi người dùng chỉ dị ứng giáp xác.

### 3. Tạo enriched query

`search_food()` ghép câu hỏi gốc với các tín hiệu ưu tiên theo cùng cấu trúc embedding của món ăn:

- tên món người dùng muốn.
- nguyên liệu người dùng/y tế nên ưu tiên.
- soft tag người dùng/y tế nên ưu tiên.
- `taste_profile`.
- `meal_context`.
- `occasion_context`.

Sau đó gọi Gemini embedding với task type `RETRIEVAL_QUERY`.

### 4. Hard Filter

Hệ thống lọc món trước khi tính vector:

- Convert `final_exclude_ings` sang `exclude_ingredient_keys`.
- Loại món bằng SQL array overlap trên `Food.core_ingredient_keys`.
- Loại món có tên nằm trong `exclude_dishes`.
- Lọc thêm bằng Python bằng cùng logic `core_ingredient_keys` để bảo vệ dữ liệu cũ/chưa rebuild đủ key.

Hard Filter nên được xem là lớp an toàn chính.

### 5. Context filter và ingredient priority

Sau hard filter:

- `meal_context` và `occasion_context` của user được lọc thích nghi.
- Nguyên liệu user thích được chuyển thành nhóm ưu tiên nếu không xung đột bệnh lý.
- Nếu có món an toàn khớp nguyên liệu user muốn, các món này được xếp trước.
- Nếu chưa đủ top 5, hệ thống bổ sung món thay thế an toàn hơn.

Soft/category tag không còn là hard filter rộng mặc định. Chúng chủ yếu dùng cho cộng/trừ điểm và giải thích.

### 6. Vector Search

Hệ thống tính cosine similarity giữa:

- vector của query người dùng.
- vector của từng món ăn còn lại.

Sau đó cộng/trừ điểm bằng tag/category:

- user preference bonus.
- medical prefer bonus.
- user/medical avoid penalty.

Kết quả top 5 trả kèm `reason` cho từng món để UI hiển thị "Tại sao lại gợi ý?".

### 7. Dynamic Rule Injection

Sau khi đã có top 5 món đã qua lọc và xếp hạng, `post_processing_agent()` đọc `medical_advice_rules.json`.

Vai trò của file này:

- Không dùng để chặn món.
- Chỉ dùng để bơm lời khuyên cách ăn vào prompt.
- Ví dụ: nếu người dùng cao huyết áp và món top 5 có `Món nước`, hệ thống nhắc không nên húp nước lèo vì nhiều muối.

Prompt post-processing hiện được siết để:

- Không gọi top 5 là an toàn tuyệt đối.
- Không nhắc món ngoài danh sách kết quả.
- Dùng ngôn ngữ thận trọng với món đúng sở thích nhưng có rủi ro.
- Chỉ dùng `medical_advice_rules.json` làm nguồn lời khuyên sức khỏe.

## Logic dán nhãn món ăn

File chính: `scripts/relabel_soft_tags.py`.

Script này dùng Gemini để tạo lại:

- `description`
- `core_ingredients`
- `preprocessing_ingredients`
- `soft_tags`

Sau khi LLM trả kết quả, Python post-processing kiểm tra và sửa nhãn.

Các rule quan trọng hiện tại:

- `Ngọt` chỉ giữ nếu món là bánh/chè/kem/tráng miệng/đồ ngọt thật sự.
- `Mặn` chỉ giữ nếu món có bản sắc mặn rõ như mắm, khô, muối, kho quẹt.
- `Chua` chỉ giữ nếu vị chua là linh hồn của món, không giữ chỉ vì có chanh/tắc ăn kèm.
- `Cay` chỉ giữ nếu cay là đặc trưng, không giữ chỉ vì có ớt/tiêu phụ.
- `Đắng` chỉ giữ khi có nguyên liệu đắng chủ đạo như khổ qua, mướp đắng, ngải cứu.
- `Béo ngậy` cần có tín hiệu rõ như bơ, phô mai, kem, nước cốt dừa, mỡ/da/ba chỉ, mayo, món chiên.
- `Đặc sản Đà Nẵng` được siết lại để tránh gắn quá rộng.
- Mỗi món phải có tối thiểu các nhóm mô tả chính: vị, dạng món, phương pháp chế biến.
- Output `soft_tags` được cắt còn tối đa 8 tag quan trọng nhất.

## Vấn đề đã xử lý trong phiên bản hiện tại

### 1. Tách category khỏi `soft_tags`

Trước đây `soft_tags` gánh quá nhiều vai trò: vị giác, dạng món, bữa ăn, dịp ăn, dinh dưỡng và vùng miền. Phiên bản hiện tại đã tách thành:

```json
{
  "name": "Phở bò nạm",
  "core_ingredients": ["thịt bò", "xương bò", "bánh phở", "gừng", "hành"],
  "soft_tags": ["Món nước", "Hầm / Ninh", "Món Việt truyền thống", "Giàu đạm"],
  "taste_profile": ["Đậm đà"],
  "meal_context": ["Ăn sáng", "Ăn trưa"],
  "occasion_context": ["Ăn no", "Ăn khuya"]
}
```

Vai trò từng field:

- `core_ingredients`: hiển thị và đưa vào embedding.
- `core_ingredient_keys`: dùng cho Hard Filter y tế.
- `soft_tags`: mô tả bản chất món ăn tương đối ổn định.
- `taste_profile`: phục vụ tìm theo khẩu vị.
- `meal_context`: phục vụ tìm theo thời điểm ăn.
- `occasion_context`: phục vụ tìm theo ngữ cảnh ăn.
- `medical_advice_rules`: chỉ tư vấn cách ăn sau khi món đã qua lọc.

### 2. Chuẩn hóa nguyên liệu bằng alias/key

Vấn đề cũ: matching nguyên liệu không dấu dễ miss biến thể hoặc dính false positive.

Hướng xử lý hiện tại:

- `services/ingredient_key_service.py` sinh `core_ingredient_keys`.
- `scripts/generate_ingredient_key_preview.py` giữ baseline alias rules đã review.
- `ingredient_alias_overrides` cho phép Admin bổ sung alias mới không cần deploy lại.
- Search filter dùng SQL overlap trên `Food.core_ingredient_keys`.

### 3. Explainability cho UI

Backend hiện trả thêm:

- `food.reason`: giải thích vì sao từng món được gợi ý.
- `ai_response`: lời tư vấn tổng quan có Dynamic Rule Injection.

Prompt post-processing đã được siết:

- Không gọi top 5 là an toàn tuyệt đối.
- Không bịa món ngoài danh sách.
- Dùng ngôn ngữ thận trọng với món đúng sở thích nhưng có rủi ro.

## Công việc cần làm tiếp theo

Roadmap chi tiết nằm ở:

- `docs/backend_api_todo.md`

Ưu tiên gần nhất:

1. Thêm `disclaimer` vào `SearchResponse`.
2. Thêm query log/excluded summary để debug vì sao món bị loại/cảnh báo.
3. Thêm User Health Profile để search dùng hồ sơ sức khỏe đã lưu.
4. Thêm Chat History và Favorite Foods.
5. Thêm Admin Food CRUD + Trigger Embedding.

## Bộ test truy vấn nên duy trì

Cần có một tập câu hỏi mẫu để regression test:

```text
Tôi bị tiểu đường, muốn ăn sáng nhẹ bụng
Tôi bị gout, không muốn ăn hải sản
Tôi bị cao huyết áp, muốn ăn món nước
Tôi bị đau dạ dày, muốn ăn món không cay
Tôi dị ứng tôm cua, muốn ăn hải sản cá
Tôi muốn ăn món chay thanh đạm
```

Mỗi query nên kiểm:

- món bị cấm có bị loại không.
- món phù hợp có xuất hiện không.
- lời tư vấn có đúng bệnh lý không.
- món bị loại có lý do rõ ràng không.

## Nguyên tắc thiết kế nên giữ

1. Không dùng LLM làm lớp an toàn cuối cùng.
2. Không dùng soft tag làm Hard Filter chính cho dị ứng.
3. Không xem `đường`, `muối`, `nước mắm`, `ớt`, `chanh` là bằng chứng đủ để gán vị chủ đạo.
4. Dynamic Rule Injection chỉ dùng để tư vấn cách ăn, không dùng để chặn món.
5. Dữ liệu món ăn phải được review theo batch trước khi seed vào production.

## Trạng thái hiện tại

- Backend FastAPI đã chạy được.
- Seed dữ liệu và embedding đang hoạt động.
- Search hiện dùng LLM intent extraction, key-based hard filter, context filter, ingredient priority, vector search, tag/category rerank và post-processing advice.
- Logic relabel đã được siết lại để giảm lỗi gán nhãn theo keyword nguyên liệu.
- Hard Filter đã chuyển từ matching nguyên liệu không dấu sang `core_ingredient_keys`.
- DB đã có `raw_ingredients`, `raw_instructions`, `taste_profile`, `meal_context`, `occasion_context`, `core_ingredient_keys`.
- Backend đã có Admin API tối thiểu cho `ingredient_alias_overrides`.
- API search đã trả `food.reason` cho UI giải thích từng món.
- Tên bệnh trong `food_service.py` đã được chuẩn hóa để khớp `standard-data/tags_data.json`.
- DB đã migrate sang category mới theo pattern startup hiện tại.
- Chưa merge `tags_data.generated.json` vào nguồn rule production.
- Chưa có bộ test regression tự động cho chất lượng gợi ý.
- Chưa có User Profile, Chat History, Favorites, Admin Food CRUD, Disclaimer và Query Log đầy đủ.
