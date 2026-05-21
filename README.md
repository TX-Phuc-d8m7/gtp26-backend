# Food Recommendation Backend

Backend FastAPI cho hệ thống gợi ý món ăn theo câu hỏi tự nhiên, có xét bệnh lý, dị ứng, sở thích, nguyên liệu, ngữ cảnh bữa ăn và vị trí địa phương như Đà Nẵng. Hệ thống kết hợp rule y tế, SQL filter, ingredient alias keys, vector search, Gemini LLM và post-processing để trả về món ăn kèm giải thích.

## Công Nghệ Chính

- FastAPI + SQLAlchemy Async.
- PostgreSQL + pgvector (`HALFVEC(3072)`).
- Gemini 2.5 Flash cho intent extraction và diễn giải kết quả.
- Gemini embedding cho query/food retrieval.
- Ingredient key system: `base:*`, `canon:*`, `group:*`.
- Rule y tế từ `standard-data/tags_data.json`.
- Advice rule injection từ `standard-data/generated-rules/medical-advice-rules/medical_advice_rules.json`.
- Admin APIs cho food, tag, user, alias override và query log.

## Chạy Backend

```bash
source venv/bin/activate
python -m uvicorn app.main:app --reload
```

Entrypoint cũ vẫn còn để tương thích:

```bash
python -m uvicorn main:app --reload
```

API docs:

```text
http://127.0.0.1:8000/docs
```

Endpoint search chính:

```text
GET /foods/search?q=<câu hỏi người dùng>
```

Ví dụ:

```text
/foods/search?q=Tôi bị tim mạch, nghe nói ăn cá tốt cho tim, ở Đà Nẵng có món cá nào phù hợp?
```

## Cấu Trúc Chính

```text
backend/
├── app/
│   ├── main.py
│   ├── api/
│   │   └── v1/router.py
│   ├── core/
│   │   └── config.py
│   ├── db/
│   │   ├── init_db.py
│   │   ├── seed.py
│   │   └── session.py
│   ├── integrations/
│   │   ├── google_storage.py
│   │   └── vertex_ai.py
│   └── modules/
│       ├── auth/
│       ├── users/
│       ├── foods/
│       ├── search/
│       ├── favorites/
│       ├── chat/
│       ├── query_logs/
│       └── admin/
├── scripts/
├── standard-data/
│   ├── tags_data.json
│   ├── alias-rules/
│   ├── generated-rules/medical-advice-rules/
│   └── ingredients-data/food-clean-categorized/
└── docs/
```

Các file gốc `main.py`, `models.py`, `schemas.py`, `database.py` ở root chủ yếu là compatibility layer sau refactor. Code mới nên import từ `app.modules.<domain>`.

## Biến Môi Trường Quan Trọng

```env
RUN_SEED_ON_STARTUP=true
SYNC_TAGS_ON_STARTUP=true
SYNC_FOODS_ON_STARTUP=true
SYNC_FOODS_DELETE_STALE_ON_STARTUP=true
RUN_EMBEDDING_ON_STARTUP=true
EMBEDDING_BACKFILL_LIMIT=0
EMBEDDING_BACKFILL_SLEEP_SECONDS=3
```

Ý nghĩa:

- `RUN_SEED_ON_STARTUP`: bật/tắt toàn bộ seed khi backend khởi động.
- `SYNC_TAGS_ON_STARTUP`: đồng bộ `tags_data.json` vào bảng `tags`.
- `SYNC_FOODS_ON_STARTUP`: đồng bộ food JSON vào bảng `foods`.
- `SYNC_FOODS_DELETE_STALE_ON_STARTUP`: nếu bật, món có trong DB nhưng không còn trong food JSON sẽ bị xoá khỏi DB.
- `RUN_EMBEDDING_ON_STARTUP`: tạo embedding cho món có `embedding IS NULL`.

Chạy sync thủ công:

```bash
python3 -m app.db.seed --foods --delete-stale-foods
python3 -m app.db.seed --all --delete-stale-foods
```

## API Hiện Có

### Auth

```text
POST /auth/signup
POST /auth/login
POST /auth/refresh
POST /auth/logout
GET  /auth/me
```

Lưu ý: `/auth/refresh` hiện là MVP stateless. Hệ thống chưa có bảng `refresh_tokens` và chưa có refresh token dài hạn/revoke store.

### User Health Profile

```text
GET    /users/me/health-profile
PUT    /users/me/health-profile
PATCH  /users/me/health-profile
DELETE /users/me/health-profile
```

Profile hiện lưu:

- `health_conditions`
- `allergies`
- `diet_preferences`
- `nutrition_goals`
- `disliked_ingredients`
- `preferred_ingredients`
- `notes`

Chưa có bảng/API `user_disliked_foods` theo `food_id`.

### Food Search Và Food Library

```text
GET /foods/search
GET /foods/filter-options
GET /foods
GET /foods/{food_id}
```

### Favorites

```text
GET    /users/me/favorites
POST   /users/me/favorites
GET    /users/me/favorites/recommendations
GET    /users/me/favorites/shopping-list
PATCH  /users/me/favorites/{food_id}
DELETE /users/me/favorites/{food_id}
GET    /users/me/favorites/{food_id}/check
```

`favorite_foods` có `notes` và `rating`, nhưng đây không phải bảng `food_feedback` riêng.

### Chat

```text
GET    /chat/threads
POST   /chat/threads
GET    /chat/threads/{thread_id}
PATCH  /chat/threads/{thread_id}
DELETE /chat/threads/{thread_id}
GET    /chat/threads/{thread_id}/messages
POST   /chat/threads/{thread_id}/messages
POST   /chat/threads/{thread_id}/messages/{message_id}/regenerate
PATCH  /chat/threads/{thread_id}/messages/{message_id}/feedback
POST   /chat/threads/{thread_id}/messages/{message_id}/edit-and-resend
```

Chat message feedback hiện hỗ trợ `like`, `dislike`, hoặc `null`.

### Admin

```text
GET    /admin/foods
GET    /admin/foods/{food_id}
POST   /admin/foods
PATCH  /admin/foods/{food_id}
DELETE /admin/foods/{food_id}
POST   /admin/foods/{food_id}/image
POST   /admin/foods/{food_id}/rebuild-keys
POST   /admin/foods/{food_id}/embedding
POST   /admin/foods/rebuild-embeddings
POST   /admin/foods/import/preview
POST   /admin/foods/import/apply

GET    /admin/tags
GET    /admin/tags/{tag_id}
POST   /admin/tags
PATCH  /admin/tags/{tag_id}
DELETE /admin/tags/{tag_id}

GET    /admin/users
GET    /admin/users/{user_id}
PATCH  /admin/users/{user_id}
POST   /admin/users/{user_id}/lock
POST   /admin/users/{user_id}/unlock

GET    /admin/ingredient-alias-overrides
POST   /admin/ingredient-alias-overrides
PATCH  /admin/ingredient-alias-overrides/{override_id}
DELETE /admin/ingredient-alias-overrides/{override_id}
POST   /admin/ingredient-alias-overrides/rebuild-food-keys

GET    /admin/query-logs
GET    /admin/query-logs/{log_id}
DELETE /admin/query-logs/{log_id}
```

Chưa có bảng/API `admin_audit_logs`.

## Database Hiện Tại

Các model chính nằm trong `app/modules/*/models.py`, được import vào `app/db/base.py`.

### `foods`

- `id`
- `name`
- `description`
- `img_url`
- `core_ingredients`
- `raw_ingredients`
- `raw_instructions`
- `core_ingredient_keys`
- `soft_tags`
- `taste_profile`
- `meal_context`
- `occasion_context`
- `embedding`

### `tags`

- `name`
- `tag_type`
- `exclude_soft_tag`
- `prefer_soft_tag`
- `exclude_ingredient`
- `prefer_ingredient`

### Các bảng khác

- `users`
- `user_health_profiles`
- `favorite_foods`
- `chat_threads`
- `chat_messages`
- `query_logs`
- `ingredient_alias_overrides`

### Foreign Keys

Hệ thống hiện chủ động chưa dùng DB-level `ForeignKey`. Một số field như `favorite_foods.food_id`, `favorite_foods.user_id`, `user_health_profiles.user_id` là UUID thường kèm index/unique. Khi xoá stale food từ seed, code có dọn `favorite_foods` liên quan để tránh dữ liệu mồ côi.

## Dữ Liệu Runtime

Food seed source:

```text
standard-data/ingredients-data/food-clean-categorized/raw_foods_enriched_labeled(final_488).categorized.clean.json
```

Tag/rule seed source:

```text
standard-data/tags_data.json
```

Medical advice runtime source:

```text
standard-data/generated-rules/medical-advice-rules/medical_advice_rules.json
```

Alias preview/audit artifact:

```text
standard-data/alias-rules/ingredient_key_preview.v1.json
```

## Luồng Search Hiện Tại

1. `resolve_food_conflicts()` gọi supervisor LLM để trích xuất bệnh lý, dị ứng, món muốn/không muốn, nguyên liệu muốn/không muốn, tag/ngữ cảnh.
2. Rule từ bảng `tags` được merge với sở thích người dùng.
3. Nguyên liệu cần chặn được chuyển thành `exclude_ingredient_keys` bằng alias system.
4. SQL hard filter loại món có `Food.core_ingredient_keys.overlap(exclude_ingredient_keys)`.
5. Allergy text fallback bắt nguyên liệu ẩn nếu key chưa phủ đủ.
6. Disease `exclude_soft_tag` được dùng như hard filter y tế.
7. Context filter thích nghi xử lý `meal_context` và `occasion_context`.
8. Dish-name include filter ưu tiên nhóm món user muốn như bún, cơm, phở, mì quảng.
9. Ingredient include filter hiện có hard/adaptive path cho intent cá: `cá` có dấu -> `canon:ca`; không map `ca` trần để tránh nhầm `cà`.
10. Semantic scoring dùng Gemini embedding + cosine similarity.
11. Rerank cộng/trừ điểm theo user tag, medical tag, meal role, ingredient priority và caution ingredient keys.
12. Top results được deduplicate và sinh `reason`.
13. `post_processing_agent()` inject `medical_advice_rules.json` để viết lời tư vấn thận trọng, không bịa món ngoài top results.

## Các Điểm Chưa Có / MVP

| Mục | Trạng thái |
|---|---|
| `refresh_tokens` | Chưa có bảng/model/API riêng; `/auth/refresh` là MVP stateless bằng access token hiện tại. |
| DB-level FK constraints | Chủ động chưa dùng; đang xử lý quan hệ bằng UUID + service logic. |
| `food_feedback` | Chưa có bảng/API riêng; hiện chỉ có favorite `rating/notes` và chat message feedback. |
| `user_disliked_foods` | Chưa có bảng/API theo `food_id`; hiện có `user_health_profiles.disliked_ingredients`. |
| `admin_audit_logs` | Chưa có bảng/API. |

## Lệnh Hữu Ích

Compile nhanh:

```bash
python3 -m py_compile app/core/config.py app/db/init_db.py app/db/seed.py app/modules/search/service.py
```

Generate ingredient alias preview:

```bash
python3 scripts/generate_ingredient_key_preview.py --force
```

Run pathology test script:

```bash
python3 scripts/run_pathology_tests.py
```

Run backend:

```bash
python -m uvicorn app.main:app --reload
```
