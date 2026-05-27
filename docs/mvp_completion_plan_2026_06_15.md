# Kế Hoạch Hoàn Thiện MVP Trước 15/06/2026

Ngày lập: 25/05/2026  
Deadline: 15/06/2026  
Mục tiêu: demo được hệ thống gợi ý món ăn cá nhân hóa theo sức khỏe, có chat intent, UI ổn định, dữ liệu/rule đủ tin cậy cho các kịch bản bảo vệ đồ án.

## 1. Định Nghĩa MVP Cần Chốt

MVP không cần là sản phẩm production hoàn chỉnh. MVP cần chứng minh được:

- Người dùng nhập nhu cầu ăn uống bằng ngôn ngữ tự nhiên.
- Hệ thống hiểu bệnh lý/dị ứng/triệu chứng trọng tâm.
- Hệ thống lọc món không phù hợp bằng rule + ingredient keys.
- Hệ thống xếp hạng món bằng embedding similarity + rerank theo tag/context.
- Chatbot xử lý được greeting, new_search, follow_up, food_info, food_safety_check, location_search, off_topic.
- Frontend hiển thị thống nhất nội dung từ backend: `ai_response` cho bubble, `results[].reason` cho card món.
- Có bộ test/demo cố định để chứng minh hệ thống hoạt động ổn định.

Phạm vi sức khỏe MVP:

- Dị ứng: động vật giáp xác, động vật thân mềm, cá có vây, đậu phộng, sữa bò, trứng.
- Bệnh lý: cao huyết áp, tiểu đường, gout, viêm loét dạ dày, béo phì, tim mạch.
- Triệu chứng/tình trạng: nhiệt miệng/loét miệng, đầy bụng/khó tiêu, bệnh lý hô hấp trên.

## 2. Trạng Thái Hiện Tại

Ước lượng tổng thể: 75% MVP.

- Backend search: 80-85%.
- Chat intent backend: 70-75%.
- Frontend chat/search/profile: 65-70%.
- Data/rules sức khỏe: 65-70%.
- Regression test: 45-55%.
- Tài liệu giải thích học thuật/demo: 70%.

Rủi ro lớn nhất:

- Frontend chat có hai luồng: user đăng nhập dùng `/chat`, guest/local có thể vẫn gọi `/foods/search`, dễ làm UI khác Swagger/backend intent.
- Data alias còn lỗi va chạm tiếng Việt: sữa/sứa, bơ/bò, cá/cà, mè/me.
- Rule bệnh lý nếu hard filter quá mạnh sẽ ít món; nếu soft quá nhẹ thì món rủi ro lọt top.
- Chưa có bộ regression test đủ khóa các lỗi đã phát hiện.

## 3. Ưu Tiên P0: Phải Làm Trước

### P0.1. Thống nhất luồng chat frontend

Mục tiêu: mọi tin nhắn chat trên UI phải đi qua intent dispatcher backend.

Việc cần làm:

- Sửa frontend guest/local chat adapter để gọi `POST /chat/guest/messages` thay vì gọi `GET /foods/search`.
- Logged-in chat tiếp tục dùng `POST /chat/threads/{thread_id}/messages`.
- Frontend không tự xử lý greeting bằng local rule nếu backend đã có intent `greeting`.
- Mapping response thống nhất:
  - Bubble: `assistant_message.content`.
  - Food cards: `search_result.results` hoặc `assistant_message.food_results`.
  - Intent/log debug: lấy từ `intent` nếu backend response có.

File liên quan:

- `frontend/src/features/chat/lib/chat-api-adapter.ts`
- `backend/app/modules/chat/router.py`
- `backend/app/modules/chat/service.py`
- `backend/app/modules/chat/engine/dispatcher.py`

Tiêu chí hoàn thành:

- Nhắn "Chào bạn" trên UI không gọi `/foods/search`.
- Nhắn "Tôi bị tiểu đường, tối ăn gì no mà không tăng đường?" trên UI và Swagger cho kết quả cùng một luồng.
- UI không tự sinh nội dung khác backend.

### P0.2. Chốt contract response cho chat/search

Mục tiêu: frontend không crash khi `search_result = null` ở các intent không phải search.

Việc cần làm:

- Với `greeting`, `off_topic`, `food_info`, `food_safety_check`, frontend phải chấp nhận `search_result: null`.
- Chỉ render food cards nếu `search_result?.results?.length > 0` hoặc `assistant_message.food_results?.length > 0`.
- Hiển thị intent/debug nếu cần nhưng không phụ thuộc để render chính.

File liên quan:

- `frontend/src/features/chat/lib/chat-api-adapter.ts`
- `frontend/src/features/chat/_interface.ts`
- `backend/app/modules/chat/schemas.py`
- `backend/app/modules/chat/engine/response_factory.py`

Tiêu chí hoàn thành:

- Greeting/off-topic không crash UI.
- Food safety check không có món vẫn render message tự nhiên.
- Location search không yêu cầu `search_result.results`.

### P0.3. Regression test cho 17 nhóm sức khỏe

Mục tiêu: khóa lại các lỗi quan trọng trước demo.

Việc cần làm:

- Tạo danh sách query test cố định cho từng nhóm sức khỏe.
- Mỗi query kiểm tra:
  - Không có nguyên liệu cấm rõ ràng trong top results.
  - Có đúng meal_context nếu user yêu cầu bữa ăn.
  - `ai_response` không bịa món ngoài `results`.
  - `reason` từng món không nhắc score/tag kỹ thuật.
- Ưu tiên test bằng script local, chưa cần framework phức tạp.

File liên quan:

- `backend/scripts/run_pathology_tests.py` nếu đã có.
- Có thể tạo thêm `backend/scripts/run_mvp_regression_tests.py`.
- `backend/standard-data/tags_data.json`
- `backend/standard-data/generated-rules/medical-advice-rules/medical_advice_rules.json`

Tiêu chí hoàn thành:

- Có ít nhất 25 test case chạy được bằng một command.
- Có report pass/fail rõ query nào lỗi.
- Demo trước hội đồng dùng các query đã pass.

## 4. Ưu Tiên P1: Cần Làm Để Demo Mượt

### P1.1. QA dữ liệu ingredient keys và alias

Mục tiêu: giảm lỗi loại nhầm hoặc lọt món nguy hiểm.

Nhóm cần kiểm tra trước:

- Dị ứng sữa bò: sữa, phô mai, bơ sữa, kem, sữa đặc; không loại nhầm sứa, hàu sữa, bò lát chay.
- Dị ứng trứng: trứng, mayonnaise, bánh flan, mì trứng; không loại oan mọi loại bánh mì nếu không chứa trứng.
- Dị ứng giáp xác: tôm, cua, ghẹ, bề bề, chả cua, nước hầm giáp xác.
- Tiểu đường: hạn chế lá phở sắn, bánh tráng, bột gạo/bột mì nếu rule đang muốn hard filter.
- Viêm loét dạ dày: tiêu, ớt, sa tế, chua, chiên, nhiều dầu mỡ.

File liên quan:

- `backend/scripts/generate_ingredient_key_preview.py`
- `backend/app/modules/ingredients/service.py`
- `backend/standard-data/tags_data.json`
- Food JSON runtime.

Tiêu chí hoàn thành:

- Top query demo không còn lỗi alias dễ thấy.
- Có note giải thích được vì sao món bị loại hoặc được giữ.

### P1.2. Tối ưu response tự nhiên

Mục tiêu: câu trả lời đủ hay để demo, nhưng không mâu thuẫn dữ liệu.

Luồng mong muốn:

- `final_validation_agent`: viết `results[].reason` cho từng món khi có sức khỏe.
- `post_processing_agent`: chỉ viết `ai_response` tổng quan.
- Frontend chỉ hiển thị đúng hai nguồn trên, không tự viết lại.

Việc cần làm:

- Kiểm tra prompt validation cho `reason` từng món.
- Kiểm tra prompt post-processing không nhắc món ngoài list.
- Với `REJECT`, không để món bị loại còn xuất hiện trong `ai_response`.

File liên quan:

- `backend/app/modules/search/validation.py`
- `backend/app/modules/search/explanation.py`
- `backend/app/modules/search/service.py`

Tiêu chí hoàn thành:

- `reason` 20-35 chữ, không nhắc score.
- `ai_response` nói về 3-5 món trong danh sách, không chỉ món #1.
- Có cảnh báo thực tế khi món cần điều chỉnh.

### P1.3. Hoàn thiện follow-up chat

Mục tiêu: demo được hội thoại nhiều lượt.

Kịch bản cần pass:

- "Tối nay đi tập gym về, muốn nhiều protein, thanh đạm."
- "Trong mấy món trên bỏ bún và đồ sống."
- "Món top 1 có hợp với dị ứng hải sản không?"
- "Tìm quán gần Đại học Bách Khoa bán món đó."

Việc cần làm:

- Kiểm tra classifier context có `last_food_names`, `last_assistant_has_food_results`, `last_intent`.
- Follow-up lấy assistant message gần nhất có food results, không lấy greeting/off-topic.
- Food safety resolve được "top 1", "món đó", tên món trực tiếp.

File liên quan:

- `backend/app/modules/chat/engine/intent_classifier.py`
- `backend/app/modules/chat/engine/context.py`
- `backend/app/modules/chat/engine/food_reference.py`
- `backend/app/modules/chat/engine/handlers/follow_up.py`
- `backend/app/modules/chat/engine/handlers/food_safety_check.py`

Tiêu chí hoàn thành:

- Không search lại full corpus cho follow-up đơn giản.
- Nếu không resolve được món, trả `unverified`, không kết luận bừa.

## 5. Ưu Tiên P2: Làm Nếu Còn Thời Gian

### P2.1. Places/location search

Mục tiêu: có demo "tìm quán gần đây".

Việc cần làm:

- Frontend truyền `lat/lng` nếu người dùng cho phép.
- Backend fallback location query hoặc mặc định Đà Nẵng.
- UI render place cards nếu có `place_result`.

Tiêu chí hoàn thành:

- Query "tìm quán bán món đó gần Bách Khoa" trả được danh sách địa điểm.
- Nếu thiếu API key/location, trả lỗi mềm.

### P2.2. Admin/data maintenance

Mục tiêu: có thể giải thích quy trình quản trị dữ liệu.

Việc cần làm:

- Admin tags/foods đủ demo CRUD cơ bản.
- Admin query logs xem được query, ai_insight, results.
- Alias override có thể rebuild keys.

### P2.3. Tối ưu tốc độ

Mục tiêu: response health query dưới 10-12s nếu có thể.

Việc cần làm:

- Không chạy validation nếu không có symptoms.
- Giữ timeout rõ cho classifier/supervisor/validation/post-processing.
- Cache filter options phía frontend.
- Hạn chế log quá dài khi demo.

## 6. Checklist Test Demo Bắt Buộc

### Search endpoint `/foods/search`

- `Tôi bị dị ứng trứng, muốn ăn sáng nhẹ ở Đà Nẵng, ăn được gì?`
- `Tôi bị tiểu đường type 2, buổi tối ăn gì vừa no vừa không tăng đường huyết?`
- `Tôi bị viêm loét dạ dày, buổi sáng nên ăn gì dịu dạ dày nhất?`
- `Tôi bị gout, muốn ăn món nhiều đạm nhưng ít purin`
- `Tôi bị cao huyết áp, sáng nay nên ăn gì tốt nhất?`
- `Tôi hay bị ợ hơi và nặng bụng sau ăn, ăn gì dễ tiêu nhất?`
- `Tôi bị nhiệt miệng, muốn ăn món mềm và mát`
- `Tôi bị dị ứng tôm cua ghẹ, vẫn muốn ăn hải sản thì ăn món gì?`

### Chat intent

- Greeting: `Chào bạn`
- New search: `Tối nay đi tập gym về, muốn món nhiều protein, thanh đạm`
- Follow-up: `Trong mấy món trên bỏ món nước và đồ sống`
- Food info: `Món bò lúc lắc có nguyên liệu gì?`
- Food safety: `Món top 1 có hợp với dị ứng hải sản không?`
- Location search: `Tìm quán bán món đó gần Đại học Bách Khoa`
- Off-topic: `Chỉ mình viết code crawl menu quán này`

### Frontend

- Chưa đăng nhập vẫn chat được qua guest endpoint.
- Đăng nhập dùng thread thật.
- Reload không mất thread đã lưu.
- Greeting không hiện food cards.
- Food cards dùng đúng `results[].reason`.
- Bubble dùng đúng `assistant_message.content`.
- Không crash khi `search_result = null`.

## 7. Timeline Gợi Ý

### 25/05 - 29/05: Khóa luồng frontend/backend

- Thống nhất chat UI dùng `/chat/guest/messages` cho guest.
- Fix response null-safe.
- Đảm bảo UI không tự sinh nội dung khác backend.
- Chốt contract response.

### 30/05 - 03/06: QA rules và dữ liệu

- Kiểm tra 17 nhóm sức khỏe.
- Fix alias false positive/false negative quan trọng.
- Chạy lại seed/key sync nếu cần.
- Chốt danh sách query demo.

### 04/06 - 08/06: Regression test và ổn định

- Viết script test MVP.
- Chạy test nhiều lần.
- Fix các query fail có ảnh hưởng demo.
- Kiểm tra tốc độ trung bình.

### 09/06 - 12/06: Frontend polish và demo script

- UI card/message ổn định.
- Chuẩn bị 1 luồng demo chính và 2 luồng dự phòng.
- Ghi lại screenshot/log minh họa.
- Tắt log quá ồn nếu cần.

### 13/06 - 14/06: Đóng băng code

- Không thêm feature lớn.
- Chỉ sửa bug blocking.
- Backup database/data/rules.
- Chuẩn bị slide và phần giải thích kiến trúc.

### 15/06: Demo

- Chạy backend/frontend bằng command đã chuẩn hóa.
- Dùng query đã regression pass.
- Nếu LLM/API lỗi, có fallback response và kịch bản dự phòng.

## 8. Definition Of Done Cho MVP

MVP được xem là đạt khi:

- Search và chat chạy được end-to-end trên UI.
- 8 query search bắt buộc trả kết quả hợp lý.
- 7 intent chat bắt buộc hoạt động đúng.
- Frontend không còn lệch nội dung so với backend.
- Có ít nhất một script regression test hoặc file test case rõ ràng.
- Có tài liệu giải thích được kiến trúc: dữ liệu món ăn, rule y tế, retrieval, ranking, validation, response generation.
- Có demo script cố định để bảo vệ đồ án.

## 9. Những Việc Không Nên Làm Trước Deadline

- Không mở rộng thêm bệnh lý ngoài danh sách MVP.
- Không cố làm Advanced RAG đầy đủ nếu search/rules chưa ổn định.
- Không refactor lớn frontend UI nếu không liên quan bug demo.
- Không thay toàn bộ schema/database nếu không bắt buộc.
- Không tối ưu production auth/refresh token nếu không ảnh hưởng demo.
- Không sửa data hàng loạt bằng rule code rộng nếu lỗi là lỗi từng món/alias cụ thể.

## 10. Ưu Tiên Một Câu

Từ nay đến 15/06, ưu tiên cao nhất là: thống nhất frontend đi qua intent dispatcher, khóa regression test cho 17 nhóm sức khỏe, sửa lỗi dữ liệu/rule ảnh hưởng demo, và đóng băng scope.
