# Backend API Roadmap

Tài liệu này liệt kê các API/công việc backend còn thiếu, mức độ ưu tiên, và định nghĩa mã nguồn nên được viết ở folder/file nào. Tài liệu chỉ mô tả phạm vi triển khai, không chứa mã nguồn implementation.

## 1. Hiện Trạng Backend

Backend hiện đã có các API chính:

- `GET /foods/search`: tìm kiếm và gợi ý món ăn theo câu hỏi người dùng.
- `/admin/ingredient-alias-overrides`: quản lý alias nguyên liệu bổ sung, rebuild `core_ingredient_keys`.

Các phần đã có trong mã nguồn:

- `models.py`: `Food`, `Tag`, `IngredientAliasOverride`.
- `schemas.py`: schema search response và alias override.
- `services/food_service.py`: luồng search, filter, rerank, post-processing.
- `services/seed_service.py`: seed dữ liệu món ăn/tag và embedding.
- `services/ingredient_key_service.py`: sinh `core_ingredient_keys` từ alias rules.
- `routers/admin_alias_overrides.py`: API admin tối thiểu cho alias override.

Mục tiêu còn lại là hoàn thiện backend theo hướng MVP: gợi ý món ăn theo sức khỏe/sở thích, có giải thích rõ ràng, có user profile, chat history, favorites, và admin quản lý dữ liệu đủ dùng.

## 2. Bảng Ưu Tiên Công Việc

| Mức ưu tiên | Nhóm công việc | Mục tiêu | Ghi chú |
| --- | --- | --- | --- |
| P0 | Disclaimer | UI luôn hiển thị hệ thống không thay thế bác sĩ | Nên bổ sung trực tiếp vào `SearchResponse` |
| P0 | Query log / explainability | Lưu lý do vì sao món được gợi ý, cảnh báo, insight bóc tách | Quan trọng để demo AI có khả năng giải thích |
| P0 | User health profile | Lưu hồ sơ sức khỏe để không cần nhập lại bệnh lý mỗi lần hỏi | Lõi cá nhân hóa |
| P0 | Chat history | Lưu hội thoại chatbot và kết quả search | Cần cho trải nghiệm chatbot thật |
| P0 | Favorite foods | Lưu món yêu thích của user | Dễ làm, hữu ích cho demo |
| P1 | Login / Signup | Tạo user thật để gắn profile, favorites, history | Có thể làm JWT đơn giản |
| P1 | Admin food CRUD | Admin xem/sửa/xóa/thêm món ăn | Cần cho quản trị dữ liệu |
| P1 | Admin tag management | Quản lý tag/rule cơ bản | Không cần làm UI rule engine quá phức tạp |
| P1 | Trigger embedding | Tạo lại embedding cho món hoặc toàn bộ món | Quan trọng cho nạp dữ liệu mới |
| P1 | Upload JSON | Admin upload file món ăn đã clean | Ưu tiên JSON trước Excel |
| P2 | Food locations | Địa chỉ quán bán món ăn | Làm sau nếu đồ án cần gợi ý địa điểm |
| P2 | Excel upload | Upload món ăn bằng Excel | Tốn validation, để sau JSON |
| P2 | LangGraph đầy đủ | Chuyển toàn bộ flow sang node/edge/tool | Có thể làm bản tối giản trước |
| P2 | Adaptive/Corrective RAG đầy đủ | Đánh giá retrieval rồi chuyển tool/fallback | Đưa vào hướng mở rộng nếu thiếu thời gian |
| P2 | Admin user CRUD | Quản lý tài khoản từ admin | Làm sau auth/user profile |

## 3. Định Nghĩa File/Folder Cần Viết

### 3.1. Database Models

File chính: `models.py`

Các model nên bổ sung:

| Model | Mục đích | Ghi chú |
| --- | --- | --- |
| `User` | Lưu tài khoản user/admin | Dùng cho login/signup và phân quyền |
| `UserHealthProfile` | Lưu hồ sơ sức khỏe, dị ứng, mục tiêu ăn uống | Gắn với `User` |
| `FavoriteFood` | Lưu món ăn yêu thích của user | Gắn `User` và `Food` |
| `ChatThread` | Lưu phiên hội thoại | Gắn với `User` |
| `ChatMessage` | Lưu từng message, role, nội dung, kết quả AI | Gắn với `ChatThread` |
| `QueryLog` | Lưu insight bóc tách, filter, top results, warning | Phục vụ debug/admin explainability |
| `FoodLocation` | Lưu quán/địa chỉ bán món ăn | Gắn với `Food` |

Nếu vẫn dùng pattern hiện tại, các cột/index mới sẽ được bổ sung trong `main.py` qua startup `ALTER TABLE` hoặc `Base.metadata.create_all`.

### 3.2. API Schemas / DTO

File chính: `schemas.py`

Các nhóm schema nên bổ sung:

| Nhóm schema | Mục đích |
| --- | --- |
| `AuthSignupRequest`, `AuthLoginRequest`, `AuthTokenResponse` | Login/signup |
| `UserProfileCreate`, `UserProfileUpdate`, `UserProfileResult` | Hồ sơ sức khỏe |
| `FavoriteFoodCreate`, `FavoriteFoodResult` | Món yêu thích |
| `ChatThreadCreate`, `ChatThreadResult`, `ChatMessageResult` | Lịch sử hội thoại |
| `QueryLogResult` | Xem log query/explainability |
| `AdminFoodCreate`, `AdminFoodUpdate`, `AdminFoodResult` | Quản lý món ăn |
| `AdminTagCreate`, `AdminTagUpdate`, `AdminTagResult` | Quản lý tag/rule |
| `FoodLocationCreate`, `FoodLocationUpdate`, `FoodLocationResult` | Địa chỉ/quán bán món |
| `ImportFoodsResponse`, `TriggerEmbeddingResponse` | Upload JSON và trigger embedding |

Schema `SearchResponse` nên bổ sung:

- `disclaimer`: câu cảnh báo hệ thống không thay thế bác sĩ.
- Có thể bổ sung `query_log_id` để frontend/admin tra cứu log về sau.

### 3.3. Routers

Folder chính: `routers/`

Các file router nên tạo:

| File | Prefix đề xuất | Trách nhiệm |
| --- | --- | --- |
| `routers/auth.py` | `/auth` | Signup, login, refresh/me nếu cần |
| `routers/user_profiles.py` | `/user/health-profile` | CRUD hồ sơ sức khỏe |
| `routers/favorites.py` | `/user/favorites` | Thêm/xóa/list món yêu thích |
| `routers/chat_history.py` | `/chat` | Tạo thread, list thread, list messages, lưu message |
| `routers/query_logs.py` | `/admin/query-logs` | Xem log bóc tách AI insight và kết quả lọc |
| `routers/admin_foods.py` | `/admin/foods` | CRUD món ăn, xem chi tiết món |
| `routers/admin_tags.py` | `/admin/tags` | CRUD tag/rule cơ bản |
| `routers/admin_imports.py` | `/admin/imports` | Upload JSON, trigger embedding, rebuild key |
| `routers/food_locations.py` | `/food-locations` hoặc `/admin/food-locations` | Quản lý địa chỉ/quán bán món |

Router hiện có cần giữ:

- `routers/admin_alias_overrides.py`: tiếp tục dùng cho alias override và rebuild food keys.

### 3.4. Services

Folder chính: `services/`

Các file service nên tạo:

| File | Trách nhiệm |
| --- | --- |
| `services/auth_service.py` | Hash password, verify password, tạo JWT/token |
| `services/user_profile_service.py` | CRUD profile, merge profile vào search query |
| `services/favorite_service.py` | Logic thêm/xóa/list món yêu thích |
| `services/chat_history_service.py` | Lưu thread/message, serialize results |
| `services/query_log_service.py` | Lưu `ai_insight`, excluded reasons, top results, warnings |
| `services/admin_food_service.py` | CRUD món, validate category/tag/ingredient |
| `services/tag_service.py` | CRUD tags/rules, validate tag type |
| `services/import_service.py` | Đọc JSON upload, validate dữ liệu, gọi seed/update |
| `services/embedding_service.py` | Sinh embedding cho một món hoặc batch |
| `services/food_location_service.py` | CRUD địa chỉ/quán bán món |

Service hiện có cần giữ:

- `services/food_service.py`: search/rerank/post-processing.
- `services/seed_service.py`: seed dữ liệu nền.
- `services/ingredient_key_service.py`: sinh `core_ingredient_keys`.

### 3.5. App Entrypoint

File chính: `main.py`

Các việc cần bổ sung:

- Include các router mới.
- Bổ sung startup schema/index nếu vẫn chưa dùng Alembic.
- Không nên để startup seed/embedding quá nặng về lâu dài; nên chuyển trigger embedding sang admin API khi ổn định.
- Bổ sung dependency auth/role guard cho các route `/admin/*` sau khi có auth.

### 3.6. Standard Data

Folder chính: `standard-data/`

Các phần dữ liệu liên quan:

| Path | Mục đích |
| --- | --- |
| `standard-data/tags_data.json` | Nguồn seed tag/rule sức khỏe hiện tại |
| `standard-data/ingredients-data/` | Nguồn seed món ăn |
| `standard-data/alias-rules/` | Preview/review alias rule và ingredient key |
| `standard-data/generated-rules/medical-advice-rules/` | Rule lời khuyên sức khỏe cho post-processing |
| `standard-data/imports/` | Có thể tạo thêm để lưu file JSON upload tạm hoặc lịch sử import |

Cần bổ sung dữ liệu sau:

- Chế độ ăn uống: ăn chay, ít muối, low-carb, high-protein, eat clean.
- Mục tiêu ăn uống: giảm cân, tăng cơ, kiểm soát đường huyết, hồi phục sau bệnh, ăn nhẹ.
- Ảnh món ăn: `img_url` hoặc mapping ảnh theo món.

### 3.7. Scripts Offline

Folder chính: `scripts/`

Các script nên bổ sung hoặc chuẩn hóa:

| File | Mục đích |
| --- | --- |
| `scripts/rebuild_food_embeddings.py` | Rebuild embedding hàng loạt |
| `scripts/import_foods_json.py` | Import JSON offline để test trước khi đưa vào admin API |
| `scripts/audit_food_search_rules.py` | Audit rule/filter theo bệnh lý và nguyên liệu |
| `scripts/audit_query_cases.py` | Chạy bộ query mẫu và ghi report |

Các script hiện có vẫn giữ:

- `scripts/generate_ingredient_key_preview.py`
- `scripts/relabel_soft_tags.py`
- `scripts/split_food_categories.py`
- `scripts/review_food_categories.py`
- `scripts/review_unmapped_ingredient_keys_llm.py`
- `scripts/audit_soft_tag_output.py`

## 4. Chi Tiết Theo Nhóm API

### 4.1. Search Explainability / Disclaimer

Ưu tiên: P0

Files cần sửa:

- `schemas.py`: thêm `disclaimer`, có thể thêm `query_log_id`.
- `services/food_service.py`: sinh disclaimer cố định, gửi thông tin log sang `query_log_service`.
- `services/query_log_service.py`: tạo mới để lưu insight, filter keys, excluded summary, results.
- `routers/query_logs.py`: tạo mới để admin xem log.
- `models.py`: thêm `QueryLog`.
- `main.py`: include router và tạo bảng/index.

Không cần file frontend trong tài liệu backend này, nhưng UI sẽ đọc `disclaimer`, `food.reason`, `ai_insight.warning_message`.

### 4.2. User Health Profile

Ưu tiên: P0

Files cần viết/sửa:

- `models.py`: thêm `UserHealthProfile`.
- `schemas.py`: thêm schema create/update/result.
- `routers/user_profiles.py`: CRUD profile.
- `services/user_profile_service.py`: logic profile.
- `services/food_service.py`: nhận thêm profile context hoặc route search lấy profile để merge vào query.
- `main.py`: include router.

Mục tiêu:

- User lưu bệnh lý, dị ứng, chế độ ăn, mục tiêu ăn uống.
- Search tự dùng profile nếu user đã đăng nhập.

### 4.3. Favorite Foods

Ưu tiên: P0

Files cần viết/sửa:

- `models.py`: thêm `FavoriteFood`.
- `schemas.py`: thêm schema favorite.
- `routers/favorites.py`: list/add/remove.
- `services/favorite_service.py`: logic favorite.
- `main.py`: include router.

Mục tiêu:

- User lưu món yêu thích.
- Có thể dùng favorite làm tín hiệu cá nhân hóa sau này.

### 4.4. Chat History

Ưu tiên: P0

Files cần viết/sửa:

- `models.py`: thêm `ChatThread`, `ChatMessage`.
- `schemas.py`: thêm schema thread/message.
- `routers/chat_history.py`: tạo thread, list thread, list messages, delete/rename nếu cần.
- `services/chat_history_service.py`: lưu message và kết quả search.
- `services/food_service.py`: không nhất thiết sửa nhiều; route chat có thể gọi search rồi lưu kết quả.
- `main.py`: include router.

Mục tiêu:

- Lưu lịch sử hội thoại để user xem lại.
- Là nền cho persistent memory tối giản.

### 4.5. Auth Login / Signup

Ưu tiên: P1

Files cần viết/sửa:

- `models.py`: thêm `User`.
- `schemas.py`: thêm auth request/response.
- `routers/auth.py`: signup/login/me.
- `services/auth_service.py`: hash password, verify, token.
- `main.py`: include router.

Mục tiêu:

- Phân biệt user để gắn profile, favorites, chat history.
- Admin guard có thể làm sau khi auth ổn định.

### 4.6. Admin Food CRUD

Ưu tiên: P1

Files cần viết/sửa:

- `schemas.py`: thêm admin food create/update/result.
- `routers/admin_foods.py`: list/detail/create/update/delete.
- `services/admin_food_service.py`: validate và update món.
- `services/ingredient_key_service.py`: dùng lại để rebuild key cho món vừa sửa.
- `services/embedding_service.py`: gọi regenerate embedding khi các field embed thay đổi.
- `main.py`: include router.

Mục tiêu:

- Admin chỉnh món, nguyên liệu, tag/category, ảnh.
- Nếu đổi field ảnh hưởng embedding thì reset/regenerate embedding.

### 4.7. Admin Tag Management

Ưu tiên: P1

Files cần viết/sửa:

- `schemas.py`: thêm tag create/update/result.
- `routers/admin_tags.py`: list/detail/create/update/delete.
- `services/tag_service.py`: validate `tag_type`, soft tags, ingredient keys.
- `main.py`: include router.

Mục tiêu:

- Admin quản lý `VALID_HARD`, `VALID_DIET`, `VALID_SOFT` hoặc tag/rule tương đương.
- Cập nhật `exclude_ingredient`, `prefer_ingredient`, `exclude_soft_tag`, `prefer_soft_tag`.

### 4.8. Upload JSON Và Trigger Embedding

Ưu tiên: P1

Files cần viết/sửa:

- `schemas.py`: thêm import/embedding response.
- `routers/admin_imports.py`: upload JSON, dry-run validate, commit import, trigger embedding.
- `services/import_service.py`: đọc file, validate, upsert món.
- `services/embedding_service.py`: sinh embedding batch.
- `services/ingredient_key_service.py`: sinh key khi import.
- `scripts/import_foods_json.py`: script offline tương ứng để test.
- `scripts/rebuild_food_embeddings.py`: script rebuild hàng loạt.
- `main.py`: include router.

Mục tiêu:

- Admin upload dữ liệu món ăn mới.
- Có nút trigger embedding để cập nhật vector trong Postgres.

### 4.9. Food Locations

Ưu tiên: P2

Files cần viết/sửa:

- `models.py`: thêm `FoodLocation`.
- `schemas.py`: thêm location schema.
- `routers/food_locations.py`: CRUD location.
- `services/food_location_service.py`: logic location.
- `main.py`: include router.

Mục tiêu:

- Gắn món ăn với quán/địa chỉ.
- Phục vụ UI tìm nơi bán món ăn.

### 4.10. LangGraph / Adaptive RAG / Corrective RAG

Ưu tiên: P2

Files nên tạo nếu làm bản tối giản:

- `services/graph_state.py`: định nghĩa state dùng chung.
- `services/graph_nodes.py`: node `AnalyzeQuery`, `RetrieveFoods`, `RankAndExplain`, `GenerateResponse`.
- `services/graph_service.py`: compile và invoke graph.
- `services/retrieval_quality_service.py`: đánh giá top result có đủ tốt không.
- `routers/search_graph.py`: route thử nghiệm cho flow graph nếu không muốn thay `/foods/search` ngay.

Mục tiêu MVP nếu còn thời gian:

- Không cần làm Agentic RAG đầy đủ.
- Chỉ cần bọc flow hiện tại thành các bước rõ ràng và log được.
- Corrective RAG bản đơn giản: nếu không có món khớp nguyên liệu hoặc top score thấp, trả fallback/cảnh báo.

## 5. Luồng Triển Khai Khuyến Nghị

### Sprint 1: Search Explainability

Mục tiêu:

- Thêm disclaimer.
- Hoàn thiện `food.reason`.
- Thêm query log/excluded summary.

Files chính:

- `schemas.py`
- `models.py`
- `services/food_service.py`
- `services/query_log_service.py`
- `routers/query_logs.py`
- `main.py`

### Sprint 2: User Flow Tối Thiểu

Mục tiêu:

- Login/signup đơn giản.
- User health profile.
- Favorite foods.
- Chat history.

Files chính:

- `models.py`
- `schemas.py`
- `routers/auth.py`
- `routers/user_profiles.py`
- `routers/favorites.py`
- `routers/chat_history.py`
- `services/auth_service.py`
- `services/user_profile_service.py`
- `services/favorite_service.py`
- `services/chat_history_service.py`
- `main.py`

### Sprint 3: Admin Data Management

Mục tiêu:

- Admin food CRUD.
- Admin tag CRUD.
- Trigger embedding.
- Rebuild ingredient keys.

Files chính:

- `routers/admin_foods.py`
- `routers/admin_tags.py`
- `routers/admin_imports.py`
- `services/admin_food_service.py`
- `services/tag_service.py`
- `services/import_service.py`
- `services/embedding_service.py`
- `services/ingredient_key_service.py`
- `main.py`

### Sprint 4: Import Và Workflow Hóa

Mục tiêu:

- Upload JSON.
- Script audit query cases.
- Graph/workflow tối giản nếu còn thời gian.

Files chính:

- `routers/admin_imports.py`
- `services/import_service.py`
- `services/embedding_service.py`
- `scripts/import_foods_json.py`
- `scripts/rebuild_food_embeddings.py`
- `scripts/audit_query_cases.py`
- `services/graph_state.py`
- `services/graph_nodes.py`
- `services/graph_service.py`

## 6. Không Ưu Tiên Trước MVP

Các phần nên để sau nếu thời gian không đủ:

- LangGraph đầy đủ với nhiều agent/tool phức tạp.
- Corrective RAG đầy đủ có self-grading nhiều bước.
- Adaptive RAG có nhiều retriever/tool thật sự.
- Excel upload.
- Admin CRUD tài khoản user đầy đủ.
- Food delivery/location ranking phức tạp.
- Recommendation dựa trên hành vi dài hạn.

## 7. Nguyên Tắc Triển Khai

- Không làm API mới nếu chưa có use case UI hoặc demo rõ ràng.
- Không gọi LLM nếu có thể sinh bằng rule/template ổn định.
- Search health-safety phải ưu tiên đúng hơn là trả lời đẹp.
- Các route `/admin/*` trước mắt có thể chưa gắn auth guard, nhưng phải thiết kế để gắn sau.
- Nếu đổi field ảnh hưởng embedding của món, phải regenerate embedding.
- Nếu đổi nguyên liệu, phải rebuild `core_ingredient_keys`.
- Nếu đổi tag/rule sức khỏe, phải kiểm thử lại các query bệnh lý mẫu.

## 8. Bộ Query Nên Dùng Để Test

Các query tối thiểu nên chạy sau mỗi thay đổi search/rule:

- `tôi bị cao huyết áp, tôi thích ăn thịt bò và đang tìm kiếm món ăn trưa`
- `tôi bị gout nên sáng mai muốn ăn đồ thanh đạm`
- `tôi bị đau dạ dày thì tối nay nên ăn món gì vừa no vừa an toàn`
- `tôi dị ứng hải sản, muốn ăn món nước ấm bụng`
- `tôi muốn ăn món nước có thịt bò, thanh đạm, ăn trưa nhưng không phải món phở`
- `mình mới mổ ruột thừa hôm qua nên ăn gì`

Mỗi query cần kiểm tra:

- `ai_insight` bóc tách đúng bệnh lý/sở thích.
- Món bị cấm theo nguyên liệu không lọt vào top.
- Món đúng sở thích được ưu tiên nhưng vẫn cảnh báo nếu có rủi ro.
- `food.reason` giải thích đúng từng món.
- `ai_response` không nói thay bác sĩ và không khẳng định quá mức an toàn.
