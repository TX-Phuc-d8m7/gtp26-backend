# Backend API Endpoint Plan

Tài liệu này lập kế hoạch danh sách API cần thiết cho hệ thống gợi ý món ăn hiện tại. Mục tiêu là đủ dùng cho MVP đồ án: gợi ý món ăn theo sức khỏe/sở thích, có giải thích, có hồ sơ người dùng, lịch sử hội thoại, món yêu thích và admin quản lý dữ liệu.

Tài liệu này chỉ định nghĩa endpoint, priority, request/response chính và file/folder cần viết. Không chứa mã nguồn implementation.

## 1. Nguyên Tắc Phạm Vi MVP

Hệ thống không cần mở rộng thành nền tảng delivery đầy đủ. Ưu tiên giữ lõi:

1. Người dùng hỏi món ăn theo sức khỏe/sở thích.
2. Backend hiểu intent, lọc món nguy cơ, rerank kết quả.
3. Backend giải thích vì sao gợi ý hoặc cảnh báo.
4. User có thể lưu hồ sơ sức khỏe, lưu món yêu thích và xem lại hội thoại.
5. Admin có thể quản lý dữ liệu món ăn/tag/alias và trigger embedding.

Những phần như LangGraph đầy đủ, Corrective RAG đầy đủ, Excel import phức tạp, quản lý quán bán món ăn nên để P2 hoặc hướng mở rộng.

## 2. API Đã Có

| Method | Path | Trạng thái | Vai trò |
| --- | --- | --- | --- |
| `GET` | `/foods/search` | Đã có | Search/gợi ý món ăn theo query tự nhiên |
| `GET` | `/admin/ingredient-alias-overrides` | Đã có | List alias override nguyên liệu |
| `POST` | `/admin/ingredient-alias-overrides` | Đã có | Tạo alias override |
| `PATCH` | `/admin/ingredient-alias-overrides/{id}` | Đã có | Cập nhật alias override |
| `DELETE` | `/admin/ingredient-alias-overrides/{id}` | Đã có | Soft delete alias override bằng `enabled=false` |
| `POST` | `/admin/ingredient-alias-overrides/rebuild-food-keys` | Đã có | Sinh lại `core_ingredient_keys` cho toàn bộ món |

## 3. Ưu Tiên Triển Khai

| Priority | Nhóm API | Lý do |
| --- | --- | --- |
| P0 | Search response improvement | Cần `disclaimer`, `query_log_id`, explainability để câu trả lời đáng tin hơn |
| P0 | Query logs | Quan trọng để debug vì sao món được gợi ý/bị loại/cảnh báo |
| P0 | User health profile | Cá nhân hóa thật, không bắt user nhập bệnh lý mỗi lần |
| P0 | Favorites | Dễ làm, tăng trải nghiệm và demo được dữ liệu user |
| P0 | Chat history | Cần cho chatbot thực tế và lưu luồng tư vấn |
| P1 | Auth | Cần để gắn profile/favorite/history với user thật |
| P1 | Admin food CRUD | Cần để quản trị dữ liệu món ăn sau khi seed |
| P1 | Admin tag/rule CRUD | Cần quản lý bệnh lý, tag, rule lọc |
| P1 | Admin import + trigger embedding | Cần cho nạp dữ liệu mới và vector hóa |
| P2 | Food locations | Chỉ cần nếu muốn gợi ý quán/địa chỉ |
| P2 | Full LangGraph/Adaptive RAG/Corrective RAG | Hướng nâng cấp, không nên làm trước khi MVP ổn |
| P2 | Admin user CRUD nâng cao | Làm sau auth cơ bản |

## 4. Quy Ước Chung Cho API

### Auth

MVP có thể dùng JWT Bearer token đơn giản.

Route user cần auth:

- `/users/me/*`
- `/favorites`
- `/chat/*`

Route admin cần role guard:

- `/admin/*`

Trong giai đoạn đầu có thể scaffold route trước, sau đó gắn role guard khi auth hoàn thiện.

### Pagination

Các endpoint list nên dùng query param:

| Param | Ý nghĩa | Default |
| --- | --- | --- |
| `limit` | Số item trả về | `20` |
| `offset` | Vị trí bắt đầu | `0` |
| `q` | Từ khóa tìm kiếm | optional |

### Error Shape

Nên thống nhất lỗi dạng:

```json
{
  "detail": "Mô tả lỗi ngắn gọn",
  "code": "OPTIONAL_ERROR_CODE"
}
```

## 5. API Search Và Explainability

### 5.1. Search món ăn

| Method | Path | Priority | Trạng thái |
| --- | --- | --- | --- |
| `GET` | `/foods/search` | P0 | Đã có, cần bổ sung response |

Query params:

| Param | Kiểu | Bắt buộc | Ý nghĩa |
| --- | --- | --- | --- |
| `q` | `string` | Có | Câu hỏi tự nhiên của user |
| `use_profile` | `bool` | Không | Có dùng hồ sơ sức khỏe đã lưu không |
| `thread_id` | `uuid` | Không | Gắn kết quả vào hội thoại |

Response cần bổ sung:

| Field | Ý nghĩa |
| --- | --- |
| `disclaimer` | Cảnh báo hệ thống không thay thế bác sĩ |
| `query_log_id` | ID log để debug/admin xem lại |
| `results[].reason` | Đã có, dùng cho card "Tại sao lại gợi ý?" |

Files liên quan:

- `schemas.py`: cập nhật `SearchResponse`.
- `services/food_service.py`: truyền `use_profile`, sinh `disclaimer`, tạo query log.
- `services/query_log_service.py`: lưu log.
- `models.py`: thêm `QueryLog`.

### 5.2. Xem query logs

| Method | Path | Priority | Vai trò |
| --- | --- | --- | --- |
| `GET` | `/admin/query-logs` | P0 | List log search gần đây |
| `GET` | `/admin/query-logs/{id}` | P0 | Xem chi tiết một log |
| `DELETE` | `/admin/query-logs/{id}` | P2 | Xóa/ẩn log nếu cần |

Thông tin nên lưu trong `QueryLog`:

- `user_id`
- `query`
- `ai_insight`
- `final_exclude_ings`
- `exclude_ingredient_keys`
- `user_include_tags`
- `user_exclude_tags`
- `candidate_count`
- `filtered_count`
- `excluded_summary`
- `top_results`
- `warning_message`
- `created_at`

Files cần viết:

- `routers/query_logs.py`
- `services/query_log_service.py`
- `models.py`
- `schemas.py`
- `main.py`

## 6. API User Health Profile

Mục tiêu: lưu bệnh lý, dị ứng, chế độ ăn, mục tiêu ăn uống để search tự dùng.

| Method | Path | Priority | Vai trò |
| --- | --- | --- | --- |
| `GET` | `/users/me/health-profile` | P0 | Lấy hồ sơ sức khỏe hiện tại |
| `PUT` | `/users/me/health-profile` | P0 | Tạo hoặc thay thế hồ sơ |
| `PATCH` | `/users/me/health-profile` | P0 | Cập nhật một phần |
| `DELETE` | `/users/me/health-profile` | P1 | Xóa hồ sơ |

Payload đề xuất:

```json
{
  "health_conditions": ["Cao huyết áp"],
  "allergies": ["Dị ứng tôm cua"],
  "diet_preferences": ["Ít muối", "Eat Clean"],
  "nutrition_goals": ["Kiểm soát huyết áp"],
  "disliked_ingredients": ["nội tạng"],
  "preferred_ingredients": ["ức gà", "rau xanh"],
  "notes": "Không ăn cay"
}
```

Files cần viết:

- `routers/user_profiles.py`
- `services/user_profile_service.py`
- `models.py`: `UserHealthProfile`
- `schemas.py`
- `services/food_service.py`: merge profile vào search context.
- `main.py`

## 7. API Favorite Foods

Mục tiêu: user lưu món yêu thích và dùng lại cho cá nhân hóa.

| Method | Path | Priority | Vai trò |
| --- | --- | --- | --- |
| `GET` | `/users/me/favorites` | P0 | List món yêu thích |
| `POST` | `/users/me/favorites` | P0 | Thêm món yêu thích |
| `DELETE` | `/users/me/favorites/{food_id}` | P0 | Xóa món yêu thích |

Payload `POST`:

```json
{
  "food_id": "uuid",
  "notes": "Ăn trưa hợp"
}
```

Files cần viết:

- `routers/favorites.py`
- `services/favorite_service.py`
- `models.py`: `FavoriteFood`
- `schemas.py`
- `main.py`

## 8. API Chat History

Mục tiêu: lưu hội thoại chatbot, message và kết quả gợi ý để user xem lại.

| Method | Path | Priority | Vai trò |
| --- | --- | --- | --- |
| `GET` | `/chat/threads` | P0 | List hội thoại của user |
| `POST` | `/chat/threads` | P0 | Tạo hội thoại mới |
| `GET` | `/chat/threads/{thread_id}` | P0 | Xem metadata thread |
| `PATCH` | `/chat/threads/{thread_id}` | P1 | Đổi tiêu đề/đánh dấu |
| `DELETE` | `/chat/threads/{thread_id}` | P1 | Soft delete thread |
| `GET` | `/chat/threads/{thread_id}/messages` | P0 | List messages |
| `POST` | `/chat/threads/{thread_id}/messages` | P0 | Lưu/gửi message mới |

Gợi ý thiết kế:

- `GET /foods/search` vẫn giữ cho Swagger test nhanh.
- UI chatbot có thể gọi `POST /chat/threads/{thread_id}/messages`; service bên trong gọi lại `search_food`.

Files cần viết:

- `routers/chat_history.py`
- `services/chat_history_service.py`
- `models.py`: `ChatThread`, `ChatMessage`
- `schemas.py`
- `services/food_service.py`: hỗ trợ lưu result vào thread nếu có `thread_id`.
- `main.py`

## 9. API Auth

Mục tiêu: có user thật để gắn profile, favorite và chat history.

| Method | Path | Priority | Vai trò |
| --- | --- | --- | --- |
| `POST` | `/auth/signup` | P1 | Tạo tài khoản |
| `POST` | `/auth/login` | P1 | Đăng nhập, trả JWT |
| `GET` | `/auth/me` | P1 | Lấy thông tin user hiện tại |
| `POST` | `/auth/logout` | P2 | Logout client-side hoặc token blacklist nếu cần |
| `POST` | `/auth/refresh` | P2 | Refresh token nếu dùng access/refresh token |

Payload `signup`:

```json
{
  "email": "user@example.com",
  "password": "password",
  "full_name": "Nguyen Van A"
}
```

Files cần viết:

- `routers/auth.py`
- `services/auth_service.py`
- `models.py`: `User`
- `schemas.py`
- `main.py`

## 10. API Admin Food Management

Mục tiêu: admin quản lý món ăn sau khi đã seed dữ liệu.

| Method | Path | Priority | Vai trò |
| --- | --- | --- | --- |
| `GET` | `/admin/foods` | P1 | List/search món |
| `GET` | `/admin/foods/{food_id}` | P1 | Xem chi tiết món |
| `POST` | `/admin/foods` | P1 | Tạo món mới |
| `PATCH` | `/admin/foods/{food_id}` | P1 | Cập nhật món |
| `DELETE` | `/admin/foods/{food_id}` | P1 | Xóa/soft delete món |
| `POST` | `/admin/foods/{food_id}/rebuild-keys` | P1 | Sinh lại `core_ingredient_keys` cho một món |
| `POST` | `/admin/foods/{food_id}/embedding` | P1 | Sinh lại embedding cho một món |

Các field admin cần quản lý:

- `name`
- `description`
- `img_url`
- `raw_ingredients`
- `raw_instructions`
- `core_ingredients`
- `soft_tags`
- `taste_profile`
- `meal_context`
- `occasion_context`

Không nên cho admin nhập trực tiếp `core_ingredient_keys` ở MVP. Field này nên sinh tự động từ `core_ingredients` và alias rules.

Files cần viết:

- `routers/admin_foods.py`
- `services/admin_food_service.py`
- `services/ingredient_key_service.py`: dùng lại.
- `services/embedding_service.py`
- `models.py`
- `schemas.py`
- `main.py`

## 11. API Admin Tag / Medical Rule Management

Mục tiêu: quản lý dữ liệu bảng `tags` và rule y tế cơ bản.

| Method | Path | Priority | Vai trò |
| --- | --- | --- | --- |
| `GET` | `/admin/tags` | P1 | List tags/rules |
| `GET` | `/admin/tags/{tag_id}` | P1 | Chi tiết tag |
| `POST` | `/admin/tags` | P1 | Tạo tag/rule |
| `PATCH` | `/admin/tags/{tag_id}` | P1 | Cập nhật tag/rule |
| `DELETE` | `/admin/tags/{tag_id}` | P1 | Xóa/disable tag |
| `GET` | `/admin/tags/options` | P1 | Trả danh sách soft tags/category/canon/group để UI chọn |

Ghi chú:

- MVP chỉ cần CRUD rule dạng array: `exclude_ingredient`, `prefer_ingredient`, `exclude_soft_tag`, `prefer_soft_tag`.
- Không cần làm rule engine phức tạp trong tháng cuối.

Files cần viết:

- `routers/admin_tags.py`
- `services/tag_service.py`
- `models.py`: dùng `Tag`, có thể thêm `enabled`.
- `schemas.py`
- `main.py`

## 12. API Admin Import Và Embedding

Mục tiêu: admin upload dữ liệu món ăn mới, trigger rebuild keys/embedding.

| Method | Path | Priority | Vai trò |
| --- | --- | --- | --- |
| `POST` | `/admin/imports/foods-json` | P1 | Upload JSON món ăn |
| `GET` | `/admin/imports/{import_id}` | P1 | Xem trạng thái import |
| `POST` | `/admin/imports/{import_id}/apply` | P1 | Áp dụng import vào DB |
| `POST` | `/admin/embeddings/rebuild` | P1 | Rebuild embedding batch |
| `POST` | `/admin/food-keys/rebuild` | P1 | Rebuild key batch |

Giai đoạn MVP:

- Chỉ hỗ trợ JSON.
- Excel upload để P2.
- Import nên có dry-run trước khi apply.

Files cần viết:

- `routers/admin_imports.py`
- `services/import_service.py`
- `services/embedding_service.py`
- `services/ingredient_key_service.py`
- `models.py`: có thể thêm `ImportJob` nếu muốn lưu trạng thái.
- `schemas.py`
- `main.py`

## 13. API Food Locations

Mục tiêu: gợi ý nơi bán món ăn. Đây là P2 vì trọng tâm hiện tại là gợi ý món theo sức khỏe, chưa phải delivery/location.

| Method | Path | Priority | Vai trò |
| --- | --- | --- | --- |
| `GET` | `/foods/{food_id}/locations` | P2 | List quán/địa chỉ bán món |
| `GET` | `/admin/food-locations` | P2 | Admin list địa điểm |
| `POST` | `/admin/food-locations` | P2 | Tạo địa điểm |
| `PATCH` | `/admin/food-locations/{id}` | P2 | Cập nhật địa điểm |
| `DELETE` | `/admin/food-locations/{id}` | P2 | Xóa địa điểm |

Files cần viết:

- `routers/food_locations.py`
- `services/food_location_service.py`
- `models.py`: `FoodLocation`
- `schemas.py`
- `main.py`

## 14. API Admin User Management

Mục tiêu: admin xem/khóa/mở tài khoản. Để P2 vì auth/user profile quan trọng hơn.

| Method | Path | Priority | Vai trò |
| --- | --- | --- | --- |
| `GET` | `/admin/users` | P2 | List user |
| `GET` | `/admin/users/{user_id}` | P2 | Chi tiết user |
| `PATCH` | `/admin/users/{user_id}` | P2 | Cập nhật role/status |
| `POST` | `/admin/users/{user_id}/lock` | P2 | Khóa tài khoản |
| `POST` | `/admin/users/{user_id}/unlock` | P2 | Mở khóa tài khoản |

Files cần viết:

- `routers/admin_users.py`
- `services/admin_user_service.py`
- `models.py`: `User`
- `schemas.py`
- `main.py`

## 15. Thứ Tự Triển Khai Khuyến Nghị

### Sprint 1: Hoàn thiện Search đáng tin hơn

Mục tiêu: API hiện tại trả lời tốt hơn và debug được.

1. Thêm `disclaimer` vào `SearchResponse`.
2. Thêm `QueryLog` model/service.
3. Lưu `query_log_id` khi gọi `/foods/search`.
4. Tạo `GET /admin/query-logs`.
5. Chuẩn hóa `excluded_summary` để biết món bị loại vì nguyên liệu/tag nào.

### Sprint 2: Cá nhân hóa người dùng

Mục tiêu: user có hồ sơ và dữ liệu riêng.

1. Làm Auth tối giản: signup/login/me.
2. Làm User Health Profile.
3. Làm Favorites.
4. Làm Chat History.
5. Search có thể dùng `use_profile=true`.

### Sprint 3: Admin quản lý dữ liệu lõi

Mục tiêu: admin sửa món/tag mà không sửa file JSON thủ công.

1. Admin Food CRUD.
2. Admin Tag CRUD.
3. Rebuild keys cho một món/toàn bộ món.
4. Rebuild embedding cho một món/toàn bộ món.
5. Kết nối lại alias override API đã có vào trang admin sau này.

### Sprint 4: Import dữ liệu

Mục tiêu: nạp dữ liệu sạch mới từ file.

1. Upload JSON dry-run.
2. Validate schema món ăn.
3. Apply import.
4. Trigger key rebuild.
5. Trigger embedding batch.

## 16. File/Folder Tổng Hợp Cần Tạo

Routers:

- `routers/auth.py`
- `routers/user_profiles.py`
- `routers/favorites.py`
- `routers/chat_history.py`
- `routers/query_logs.py`
- `routers/admin_foods.py`
- `routers/admin_tags.py`
- `routers/admin_imports.py`
- `routers/food_locations.py`
- `routers/admin_users.py`

Services:

- `services/auth_service.py`
- `services/user_profile_service.py`
- `services/favorite_service.py`
- `services/chat_history_service.py`
- `services/query_log_service.py`
- `services/admin_food_service.py`
- `services/tag_service.py`
- `services/import_service.py`
- `services/embedding_service.py`
- `services/food_location_service.py`
- `services/admin_user_service.py`

Models cần thêm trong `models.py`:

- `User`
- `UserHealthProfile`
- `FavoriteFood`
- `ChatThread`
- `ChatMessage`
- `QueryLog`
- `FoodLocation`
- `ImportJob` nếu cần lưu trạng thái import.

Schemas cần thêm trong `schemas.py`:

- Auth schemas.
- User profile schemas.
- Favorite schemas.
- Chat schemas.
- Query log schemas.
- Admin food schemas.
- Admin tag schemas.
- Import/embedding schemas.
- Food location schemas.
- Admin user schemas.

Entrypoint:

- `main.py`: include routers, startup schema/index, auth dependency sau khi có auth.

## 17. Những Việc Không Nên Làm Trước MVP

- Không làm Excel upload trước JSON upload.
- Không làm LangGraph đầy đủ trước khi search flow hiện tại có log và regression test.
- Không để LLM quyết định hard filter y tế cuối cùng.
- Không cho admin sửa trực tiếp `core_ingredient_keys`; nên sửa `core_ingredients` hoặc alias override rồi rebuild.
- Không làm admin user CRUD nâng cao trước khi có auth/profile/favorite/history.
- Không biến hệ thống thành app đặt món/quản lý nhà hàng trước khi lõi gợi ý sức khỏe ổn.

