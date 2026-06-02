# Cấu trúc mã nguồn Backend

## Tổng quan kiến trúc

Backend được xây dựng bằng **FastAPI (Python)**, kết nối **PostgreSQL + pgvector** để lưu trữ và tìm kiếm vector, sử dụng **Google Vertex AI (Gemini)** cho embedding và sinh ngôn ngữ tự nhiên.

```
Client (Mobile/Web)
        │
        ▼
   FastAPI App (Cloud Run)
        │
        ├── Search Engine (Vector Search + LLM)
        ├── Chat System (Multi-turn Conversation)
        ├── Auth / User Management
        └── Admin Panel
              │
              ▼
        PostgreSQL + pgvector (Cloud SQL)
        Google Cloud Storage (ảnh món ăn)
        Google Vertex AI (Gemini Embedding + Text)
```

---

## Cây thư mục

```
backend/
├── app/                        # Mã nguồn chính của ứng dụng
│   ├── main.py                 # Điểm khởi động FastAPI
│   ├── core/                   # Cấu hình và bảo mật
│   ├── db/                     # Kết nối và khởi tạo database
│   ├── shared/                 # Tiện ích dùng chung
│   ├── integrations/           # Tích hợp dịch vụ bên ngoài
│   ├── api/                    # Định tuyến API
│   └── modules/                # Các module nghiệp vụ
│       ├── auth/               # Xác thực người dùng
│       ├── users/              # Quản lý người dùng & hồ sơ sức khoẻ
│       ├── foods/              # Thư viện món ăn
│       ├── search/             # Engine gợi ý món ăn (core)
│       ├── chat/               # Hệ thống chat đa lượt
│       ├── favorites/          # Món ăn yêu thích
│       ├── places/             # Tìm kiếm nhà hàng
│       ├── ingredients/        # Xử lý nguyên liệu
│       ├── query_logs/         # Nhật ký truy vấn
│       └── admin/              # Quản trị hệ thống
│           ├── foods/
│           ├── tags/
│           ├── users/
│           ├── alias_overrides/
│           └── analytics/
├── scripts/                    # Script xử lý dữ liệu offline
├── standard-data/              # Dữ liệu chuẩn (tags, luật y tế, món ăn)
├── docs/                       # Tài liệu dự án
├── Dockerfile                  # Cấu hình Docker
├── deploy.sh                   # Script deploy lên Google Cloud
└── requirements.txt            # Danh sách thư viện Python
```

---

## Chi tiết từng thành phần

---

### `app/main.py` — Điểm khởi động

Tạo ứng dụng FastAPI, đăng ký toàn bộ router, thêm CORS middleware. Khi app khởi động, gọi `init_db()` để khởi tạo database (tạo bảng, extension, index). Khi app tắt, đóng kết nối database.

---

### `app/core/` — Cấu hình và bảo mật

| File | Chức năng |
|------|-----------|
| `config.py` | Đọc toàn bộ cấu hình từ biến môi trường (DB, JWT, Gemini, GCS, feature flags). Xây dựng database URL, hỗ trợ cả TCP lẫn Unix socket (Cloud SQL) |
| `security.py` | Băm mật khẩu (bcrypt), tạo và xác thực JWT token |
| `exceptions.py` | Định nghĩa các exception tùy chỉnh |
| `constants.py` | Hằng số toàn cục |

---

### `app/db/` — Lớp Database

| File | Chức năng |
|------|-----------|
| `session.py` | Tạo async engine SQLAlchemy, `AsyncSessionLocal`, dependency `get_db()` inject vào router |
| `base.py` | Declarative base ORM — import tất cả models để SQLAlchemy nhận diện schema |
| `init_db.py` | Khởi tạo database khi startup: tạo extension `vector`, tạo/alter bảng, tạo GIN index. Gọi seed nếu flag bật |
| `seed.py` | Đồng bộ dữ liệu từ file JSON vào database: sync tags, sync foods, sinh embedding |

---

### `app/shared/` — Tiện ích dùng chung

| File | Chức năng |
|------|-----------|
| `paths.py` | Định nghĩa `PROJECT_ROOT` và `STANDARD_DATA_DIR` — đường dẫn đến thư mục `standard-data/` |

---

### `app/integrations/` — Tích hợp bên ngoài

| File | Chức năng |
|------|-----------|
| `vertex_ai.py` | Kết nối Google Vertex AI. Tạo embedding văn bản (Gemini Embedding, 3072 chiều), sinh văn bản (Gemini Flash). Hàm `build_food_embed_text()` tổng hợp thuộc tính món ăn thành văn bản để nhúng vector |
| `google_storage.py` | Upload/xóa ảnh món ăn lên Google Cloud Storage |

---

### `app/api/` — Định tuyến API

| File | Chức năng |
|------|-----------|
| `router.py` | Router gốc, gắn tiền tố `/api` |
| `v1/router.py` | Router v1, tập hợp tất cả sub-router của các module |

---

### `app/modules/` — Nghiệp vụ chính

---

#### `auth/` — Xác thực

**Endpoints:** `POST /auth/signup`, `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/change-password`, `/auth/forgot-password`, `/auth/reset-password`

Xử lý đăng ký, đăng nhập, làm mới token, đặt lại mật khẩu. Dùng JWT (access token ngắn hạn + refresh token dài hạn lưu DB).

---

#### `users/` — Người dùng & Hồ sơ sức khoẻ

**Models:**
- `User` — email, mật khẩu băm, vai trò (user/admin), trạng thái
- `UserHealthProfile` — danh sách bệnh lý, dị ứng, sở thích ăn uống, khẩu vị
- `RefreshToken` — token làm mới (lưu hash, thời hạn, trạng thái thu hồi)
- `PasswordResetToken` — token dùng một lần để đặt lại mật khẩu

**Endpoints:** `GET/PUT /users/me`, `GET/PUT /users/me/health-profile`

Hồ sơ sức khoẻ (`UserHealthProfile`) được search engine đọc để cá nhân hóa kết quả gợi ý.

---

#### `foods/` — Thư viện món ăn

**Models:**
- `Food` — tên, mô tả, ảnh, nguyên liệu, nhãn phân loại (`soft_tags`, `taste_profile`, `meal_context`, `occasion_context`), vector embedding (`HALFVEC(3072)`), dining context
- `Tag` — nhãn y tế/dinh dưỡng kèm luật (ưu tiên/loại trừ soft tags và nguyên liệu)

**Endpoints:** `GET /foods`, `GET /foods/{id}`, `GET /foods/categories`, `GET /foods/filter-options`

---

#### `search/` — Engine gợi ý món ăn *(module cốt lõi)*

Đây là module phức tạp nhất, thực hiện toàn bộ pipeline gợi ý. Hàm chính: `search_food()` trong `service.py`.

**Pipeline 7 bước:**

```
[1] Phân tích intent (intent.py)
     LLM (Gemini) phân tích câu hỏi người dùng:
     → Bệnh lý, dị ứng cần loại trừ
     → Nguyên liệu/món ăn muốn bao gồm hoặc loại trừ
     → Nhãn khẩu vị, bữa ăn, dịp ăn
     → Fallback: rule-based nếu LLM timeout

[2] Kiểm tra an toàn (safety.py)
     → Phát hiện dị ứng từ text
     → Áp dụng luật y tế cứng (hard filter)
     → Đọc luật từ medical_advice_rules.json và tags_data.json

[3] Lọc ứng viên (filtering.py)
     → Loại trừ theo context (hard rules)
     → Bao gồm theo preference (soft rules)
     → Lọc theo nguyên liệu

[4] Truy xuất ứng viên (retrieval.py)
     → Vector search: sinh embedding cho câu hỏi, tìm K món gần nhất
     → Fallback lexical: khớp từ khóa nếu embedding thất bại

[5] Chấm điểm & Xếp hạng (ranking.py)
     → Tính điểm similarity hiệu chỉnh theo nhãn sức khoẻ
     → Thưởng/phạt theo bệnh lý người dùng
     → Suy luận vai trò món ăn (món chính, phụ, tráng miệng...)
     → Xếp hạng lại và loại trùng

[6] Giải thích (explanation.py)
     → Gemini sinh câu giải thích tự nhiên cho kết quả
     → Đọc luật y tế từ medical_advice_rules.json
     → Có timeout, bỏ qua nếu quá chậm

[7] Trả về SearchResponse
     → Danh sách món gợi ý kèm điểm và lý do
     → Câu trả lời AI tự nhiên
     → ID nhật ký truy vấn
```

**Các file trong search/:**

| File | Vai trò |
|------|---------|
| `service.py` | Orchestrator — gọi tuần tự các bước pipeline |
| `intent.py` | Gọi LLM phân tích câu hỏi, trích xuất ràng buộc |
| `safety.py` | Kiểm tra an toàn y tế, đọc `tags_data.json` |
| `filtering.py` | Lọc danh sách món theo điều kiện |
| `retrieval.py` | Tìm kiếm vector + fallback lexical |
| `ranking.py` | Chấm điểm và xếp hạng kết quả |
| `explanation.py` | Sinh giải thích AI, đọc `medical_advice_rules.json` |
| `validation.py` | Kiểm tra kết quả cuối trước khi trả về |
| `schemas.py` | Định nghĩa request/response schema |
| `common.py` | Hằng số, Gemini client, helper functions |
| `repository.py` | Truy vấn database |
| `tracing.py` | Ghi log debug chi tiết pipeline |

---

#### `chat/` — Hệ thống chat đa lượt

**Models:**
- `ChatThread` — luồng hội thoại (tiêu đề, ghim, xóa mềm)
- `ChatMessage` — tin nhắn (vai trò user/assistant, nội dung, kết quả món ăn dạng JSONB)
- `FoodRecommendationFeedback` — phản hồi người dùng về gợi ý

**Endpoints chính:** `POST /chat/threads/{id}/messages`, `POST /chat/guest/messages`

**Luồng xử lý chat:**

```
Tin nhắn người dùng
        │
        ▼
engine/dispatcher.py
  → Load lịch sử 6 tin nhắn gần nhất (context window)
  → Gọi intent_classifier.py để phân loại ý định
        │
        ├── new_search      → handlers/new_search.py     → gọi search_food()
        ├── follow_up       → handlers/follow_up.py      → trả lời theo ngữ cảnh
        ├── food_info       → handlers/food_info.py      → thông tin dinh dưỡng/công thức
        ├── food_safety_check → handlers/food_safety_check.py → kiểm tra an toàn dị ứng
        ├── location_search → handlers/location_search.py → tìm nhà hàng nearby
        ├── greeting        → trả lời chào hỏi
        └── off_topic       → từ chối lịch sự
        │
        ▼
Lưu assistant message vào DB
Trả về ChatSendMessageResponse
```

**Các file trong chat/engine/:**

| File | Vai trò |
|------|---------|
| `dispatcher.py` | Điều phối intent, gọi handler tương ứng |
| `intent_classifier.py` | Gọi Gemini phân loại intent, fallback rule-based |
| `context.py` | Load và cắt ngắn lịch sử hội thoại |
| `response_factory.py` | Định dạng response thống nhất |
| `handlers/new_search.py` | Xử lý tìm kiếm gợi ý mới |
| `handlers/follow_up.py` | Xử lý câu hỏi tiếp nối |
| `handlers/food_info.py` | Truy vấn thông tin món ăn |
| `handlers/food_safety_check.py` | Kiểm tra an toàn thực phẩm |
| `handlers/location_search.py` | Tìm kiếm địa điểm ăn uống |

---

#### `favorites/` — Món ăn yêu thích

Cho phép người dùng lưu, đánh giá, xem danh sách món ăn yêu thích. Hỗ trợ gợi ý từ danh sách yêu thích và tạo danh sách mua sắm.

---

#### `places/` — Tìm kiếm nhà hàng

**Endpoint:** `GET /places/search`

Tìm nhà hàng có bán món ăn cụ thể theo vị trí địa lý. Dùng SerpAPI (chính) hoặc Google Maps API (dự phòng). Có cache TTL để tránh gọi API thừa.

---

#### `ingredients/` — Xử lý nguyên liệu

Chuẩn hóa tên nguyên liệu thành `core_ingredient_keys` bằng bảng alias rules. File `generate_ingredient_key_preview.py` trong `scripts/` được import trực tiếp tại đây để dùng hàm chuẩn hóa.

---

#### `query_logs/` — Nhật ký truy vấn

Lưu lại mỗi lần người dùng tìm kiếm (câu hỏi, kết quả, intent). Admin dùng để phân tích hành vi người dùng và debug hệ thống.

---

#### `admin/` — Quản trị hệ thống

| Sub-module | Chức năng |
|------------|-----------|
| `foods/` | CRUD món ăn, upload ảnh GCS, import hàng loạt từ JSON, rebuild embedding |
| `tags/` | CRUD nhãn y tế/dinh dưỡng, quản lý luật lọc |
| `users/` | Xem danh sách, vô hiệu hóa tài khoản người dùng |
| `alias_overrides/` | Quản lý luật alias nguyên liệu, trigger rebuild ingredient keys |
| `analytics/` | Thống kê hệ thống (số người dùng, lượt tìm kiếm...) |

---

## Luồng xử lý ví dụ: Gợi ý món ăn theo sức khoẻ

**Câu hỏi người dùng:** *"Tôi bị cao huyết áp, gợi ý món ăn sáng ít muối"*

```
POST /chat/threads/{id}/messages
        │
        ▼
chat/service.py → send_message()
  1. Load UserHealthProfile (cao huyết áp đã lưu trong profile)
  2. Tạo ChatMessage (role=user) lưu vào DB
        │
        ▼
chat/engine/dispatcher.py
  3. Load 6 tin nhắn gần nhất làm context
  4. intent_classifier → intent = "new_search"
        │
        ▼
handlers/new_search.py → search_food()
        │
        ▼
search/service.py — PIPELINE:
  5.  [Intent] LLM phân tích: health_constraints=["cao_huyet_ap"], context=["bua_sang"]
  6.  [Safety] Áp hard filter: loại món nhiều muối, đồ chiên rán
  7.  [Retrieval] Embedding "món ăn sáng ít muối lành mạnh" → tìm 50 ứng viên
  8.  [Ranking] Thưởng điểm món phù hợp cao huyết áp, ưu tiên bữa sáng
  9.  [Explain] Gemini sinh câu giải thích: "Với cao huyết áp, nên ưu tiên..."
  10. Return top 5 món: Cháo trắng, Bánh mì nước, Phở gà ít nước...
        │
        ▼
chat/service.py
  11. Tạo ChatMessage (role=assistant) lưu kết quả JSONB
  12. Tự sinh tiêu đề thread từ tin nhắn đầu

        ▼
Response trả về client:
  - user_message
  - assistant_message { content, food_results, structured_result }
  - search_result { results[], ai_response, query_log_id }
```

---

## Dữ liệu chuẩn (`standard-data/`)

| File/Thư mục | Chức năng | Có trong Docker image |
|---|---|---|
| `tags_data.json` | Định nghĩa 34 nhãn y tế/dinh dưỡng và luật lọc | Có |
| `generated-rules/medical-advice-rules/medical_advice_rules.json` | Luật tư vấn y tế chi tiết cho từng bệnh lý | Có |
| `ingredients-data/` | Dữ liệu món ăn gốc (file JSON lớn, dùng để seed DB) | Không (chỉ dùng offline) |
| `generated-rules/individual/` | Luật bệnh lý từng cá nhân (dùng để sinh DB) | Không |
| `alias-rules/` | Bảng mapping alias nguyên liệu | Không |

---

## Scripts xử lý dữ liệu (`scripts/`)

Scripts không chạy trong production. Được dùng offline để xây dựng và cải thiện dữ liệu.

### Pipeline xây dựng dữ liệu (theo thứ tự):

**1. Chuẩn hóa dữ liệu món ăn:**
- `split_food_categories.py` — tách soft_tags thành meal_context / occasion_context
- `review_food_categories.py` — review và làm sạch categories
- `backfill_food_images.py` — tìm và upload ảnh món lên GCS

**2. Xây dựng hệ thống nguyên liệu:**
- `generate_ingredient_key_preview.py` — chuẩn hóa tên nguyên liệu, định nghĩa ALIAS_RULES *(được app import trực tiếp)*
- `build_ingredient_guardrail_pipeline.py` — phân tích nguyên liệu, sinh luật guardrail
- `backfill_missing_core_ingredient_keys.py` — bổ sung ingredient keys còn thiếu trong DB
- `review_unmapped_ingredient_keys_llm.py` — dùng LLM review keys chưa map được

**3. Gán nhãn dining context:**
- `propose_dining_context.py` — dùng Gemini đề xuất nhãn (home_cooked/restaurant/both)
- `apply_dining_context.py` — apply nhãn đã review vào database

**4. Kiểm tra chất lượng dữ liệu:**
- `audit_soft_tag_output.py` — audit soft_tags, phát hiện lỗi P0/P1/P2
- `relabel_soft_tags.py` — định nghĩa valid tags (dùng bởi audit script)
- `audit_allergen_filter_coverage.py` — kiểm tra độ phủ bộ lọc dị ứng

**5. Đánh giá hệ thống:**
- `run_pathology_tests.py` — chạy 35+ test case kiểm tra safety gợi ý theo bệnh lý
- `test_intent_classifier.py` — test 65 test case phân loại intent người dùng
- `benchmark_ai_models.py` — so sánh hiệu năng giữa các Gemini model
