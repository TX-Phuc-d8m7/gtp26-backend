# Food Recommendation Backend

Backend này là API gợi ý món ăn theo câu hỏi tự nhiên của người dùng. Hệ thống kết hợp FastAPI, PostgreSQL/pgvector, Gemini LLM, rule y tế và vector search để trả về danh sách món ăn phù hợp với sở thích, bệnh lý, dị ứng và ngữ cảnh ăn uống.

## Công nghệ chính

- FastAPI: xây dựng REST API.
- SQLAlchemy Async: truy cập PostgreSQL bất đồng bộ.
- PostgreSQL + pgvector: lưu món ăn, tag y tế và embedding vector.
- Gemini 2.5 Flash: phân tích ý định người dùng và sinh lời tư vấn.
- Gemini embedding: tạo vector cho món ăn và query tìm kiếm.
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
├── services/
│   ├── seed_service.py
│   └── food_service.py
├── scripts/
│   ├── relabel_soft_tags.py
│   ├── generate_disease_rules_langchain.py
│   └── build_ingredient_guardrail_pipeline.py
├── standard-data/
│   └── tags_data.json
├── llm/generated-rules/
│   └── tags_data.generated.json
├── foods_enriched.json
├── foods_enriched_v2.json
├── raw_foods_input.json
└── medical_advice_rules.json
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

## Luồng seed dữ liệu

File chính: `services/seed_service.py`.

Khi backend khởi động, `seed_data()` thực hiện:

1. Đọc `standard-data/tags_data.json`.
2. Đồng bộ rule y tế vào bảng `tags`.
3. Đọc `foods_enriched.json`.
4. Đồng bộ món ăn vào bảng `foods`.
5. Nếu món mới hoặc nội dung món thay đổi, reset `embedding = None`.
6. Với món chưa có embedding, gọi Gemini `gemini-embedding-001` để tạo vector.

Lưu ý hiện tại: production seed vẫn đọc `foods_enriched.json`, chưa tự động đọc `foods_enriched_v2.json` hoặc output relabel beta.

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

`search_food()` ghép câu hỏi gốc với các tín hiệu ưu tiên:

- tên món người dùng muốn.
- soft tag người dùng thích.
- soft tag y tế nên ưu tiên.
- nguyên liệu người dùng/y tế nên ưu tiên.

Sau đó gọi Gemini embedding với task type `RETRIEVAL_QUERY`.

### 4. Hard Filter

Hệ thống lọc món trước khi tính vector:

- Loại món có nguyên liệu thuộc `final_exclude_ings`.
- Loại món có tên nằm trong `exclude_dishes`.
- Lọc thêm bằng Python theo cơ chế không dấu để xử lý rule dạng `tom`, `ca hoi` khớp với `tôm`, `cá hồi`.

Hard Filter nên được xem là lớp an toàn chính.

### 5. Soft tag guardrail

Sau hard filter, hệ thống tiếp tục loại món nếu `soft_tags` của món giao với tag cấm.

Lưu ý: đây là lớp phụ. Không nên để soft tag quyết định toàn bộ an toàn y tế, vì soft tag có thể sai hoặc quá rộng.

### 6. Vector Search

Hệ thống tính cosine similarity giữa:

- vector của query người dùng.
- vector của từng món ăn còn lại.

Sau đó sort giảm dần và lấy top 5 món.

### 7. Dynamic Rule Injection

Sau khi đã có top 5 món an toàn, `post_processing_agent()` đọc `medical_advice_rules.json`.

Vai trò của file này:

- Không dùng để chặn món.
- Chỉ dùng để bơm lời khuyên cách ăn vào prompt.
- Ví dụ: nếu người dùng cao huyết áp và món top 5 có `Món nước`, hệ thống nhắc không nên húp nước lèo vì nhiều muối.

Đây là hướng đúng: món đã qua Hard Filter trước, lời khuyên chỉ bổ sung cách ăn an toàn hơn.

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

## Vấn đề hiện tại

### 1. Soft tag đang gánh quá nhiều vai trò

Hiện `soft_tags` chứa lẫn:

- vị giác: `Ngọt`, `Mặn`, `Chua`, `Cay`, `Đắng`, `Béo ngậy`
- dạng món: `Món nước`, `Món khô`, `Nước sền sệt`
- phương pháp: `Nướng`, `Xào`, `Chiên / Rán`
- bữa ăn: `Ăn sáng`, `Ăn trưa`, `Ăn tối`, `Ăn khuya`
- dịp ăn: `Ăn vặt`, `Mồi nhậu`, `Tráng miệng`
- dinh dưỡng: `Giàu đạm`, `Giàu tinh bột`, `Nội tạng`
- vùng miền/danh mục: `Đặc sản Đà Nẵng`, `Món Á`, `Món Âu`

Điều này làm soft tag bị loãng và dễ gây sai trong filter y tế.

### 2. LLM dễ dán nhãn theo keyword nguyên liệu

Một lỗi đã thấy trong dữ liệu cũ:

- Có `đường` thì bị gán `Ngọt`.
- Có `muối`, `nước mắm`, `hạt nêm` thì bị gán `Mặn`.
- Có `ớt`, `tiêu` thì bị gán `Cay`.
- Có `chanh`, `giấm` thì bị gán `Chua`.

Trong khi các nguyên liệu này nhiều khi chỉ là gia vị cân bằng, không phải vị chủ đạo.

### 3. Rule y tế không nên phụ thuộc quá nhiều vào soft tag

Với bệnh lý/dị ứng, soft tag chỉ là tín hiệu phụ.

Hard Filter nên dựa nhiều hơn vào:

- `core_ingredients`
- `exclude_ingredient`
- matching không dấu
- nhóm dị ứng cụ thể

Ví dụ:

- Dị ứng giáp xác nên chặn `tôm`, `cua`, `ghẹ`, `bề bề`.
- Không nên chặn toàn bộ tag `Hải sản`, vì sẽ loại nhầm cá.

### 4. `tags_data.generated.json` chưa được đưa vào production

File `llm/generated-rules/tags_data.generated.json` đã sinh rule từ danh sách nguyên liệu thật, nhưng backend seed hiện vẫn đọc `standard-data/tags_data.json`.

Cần có bước review/merge có kiểm soát trước khi dùng generated rules làm nguồn chính.

### 5. Dữ liệu production còn chưa thống nhất

Hiện có nhiều file dữ liệu:

- `foods_enriched.json`
- `foods_enriched_v2.json`
- `standard-data/ingredients-data/raw_foods_enriched(beta_v2).json`
- `raw_foods_input.json`

Cần thống nhất file nào là nguồn chính cho seed production.

### 6. Category chưa được tách khỏi soft tag

Một số tag nên được tách thành field riêng để phục vụ tìm kiếm tốt hơn:

- `taste_profile`: `Đậm đà`, `Thanh đạm`, `Chua`, `Cay`, `Mặn`, `Ngọt`, `Đắng`, `Béo ngậy`
- `meal_context`: `Ăn sáng`, `Ăn trưa`, `Ăn tối`, `Ăn chiều / xế`, `Ăn khuya`
- `occasion_context`: `Ăn no`, `Ăn vặt`, `Mồi nhậu`, `Tráng miệng`, `Giải rượu`, `Giải cảm`, `Ấm bụng`

## Hướng thiết kế đề xuất

Tách dữ liệu món ăn thành nhiều nhóm rõ vai trò:

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

- `core_ingredients`: dùng cho Hard Filter y tế.
- `soft_tags`: mô tả bản chất món ăn tương đối ổn định.
- `taste_profile`: phục vụ tìm theo khẩu vị.
- `meal_context`: phục vụ tìm theo thời điểm ăn.
- `occasion_context`: phục vụ tìm theo ngữ cảnh ăn.
- `medical_advice_rules`: chỉ tư vấn cách ăn sau khi món đã qua lọc.

## Công việc cần làm tiếp theo

### Bước 1: Relabel lại toàn bộ món ăn

Chạy lại relabel bằng logic mới:

```bash
source venv/bin/activate
python scripts/relabel_soft_tags.py --delay 3
```

Mục tiêu:

- Làm sạch các tag sai như `Ngọt`, `Mặn`, `Cay`, `Chua`, `Béo ngậy`.
- Giảm số lượng tag quá nhiều trên một món.
- Chuẩn hóa `core_ingredients` để Hard Filter chính xác hơn.

### Bước 2: Review dữ liệu sau relabel

Cần kiểm các nhóm dễ sai:

- món bị gắn `Ngọt`
- món bị gắn `Mặn`
- món bị gắn `Cay`
- món bị gắn `Chua`
- món bị gắn `Béo ngậy`
- món bị gắn `Ăn khuya`
- món bị gắn `Mồi nhậu`
- món bị gắn `Tráng miệng`
- món có nhiều hơn 8 tag
- món thiếu dạng món hoặc phương pháp chế biến

### Bước 3: Thêm category vào output relabel

Sau khi `soft_tags` ổn, mở rộng output script thành:

```json
{
  "soft_tags": [],
  "taste_profile": [],
  "meal_context": [],
  "occasion_context": []
}
```

Ở giai đoạn này chưa cần migrate DB ngay. Chỉ cần sinh file dữ liệu mới để review.

### Bước 4: Review category

Kiểm tra riêng:

- `taste_profile` có phản ánh vị chủ đạo không.
- `meal_context` có phù hợp thời điểm ăn không.
- `occasion_context` có đúng ngữ cảnh không.
- Có tag nào đang bị duplicate giữa `soft_tags` và category không.

### Bước 5: Merge rule y tế generated

So sánh:

- `standard-data/tags_data.json`
- `llm/generated-rules/tags_data.generated.json`

Sau đó merge có kiểm soát:

- Với `ALLERGY`: ưu tiên `exclude_ingredient`, hạn chế `exclude_soft_tag`.
- Với `DISEASE`: dùng cả `exclude_ingredient` và một số `exclude_soft_tag` có ý nghĩa rộng.
- Tránh chặn quá rộng làm mất món phù hợp.

### Bước 6: Migrate backend dùng category

Cập nhật:

- `models.py`
- `schemas.py`
- `seed_service.py`
- `food_service.py`
- API response

Sau migrate, search nên dùng:

- Hard Filter: `core_ingredients` + `exclude_ingredient`.
- Ranking: vector similarity + `taste_profile` + `meal_context` + `occasion_context`.
- Advice: `medical_advice_rules.json`.

### Bước 7: Xây bộ test truy vấn

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
- Search hiện dùng LLM intent extraction, hard filter, vector search và post-processing advice.
- Logic relabel đã được siết lại để giảm lỗi gán nhãn theo keyword nguyên liệu.
- Hard Filter đã bổ sung matching nguyên liệu không dấu.
- Tên bệnh trong `food_service.py` đã được chuẩn hóa để khớp `standard-data/tags_data.json`.
- Chưa migrate DB sang category mới.
- Chưa merge `tags_data.generated.json` vào nguồn rule production.
- Chưa có bộ test regression cho chất lượng gợi ý.
