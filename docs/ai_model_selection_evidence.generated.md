# Evidence So Sánh Model AI

- Thời điểm chạy: `2026-05-22 10:36:17`
- File test case: `/Users/truongxuanphuc/Documents/01-Graduation-Project/Code/food-recommendation-system/backend/[GTP26] Test case - Test Case bệnh lý.csv`
- Models so sánh: `gemini-2.5-flash, gemini-2.5-flash-lite`
- Endpoint logic: `search_food()` nội bộ, không qua frontend.
- Metric chính: latency từng stage lấy từ `query_logs.excluded_summary.llm_runtime.stage_latency_ms`.

## Tổng Hợp

| Model | Số case thành công | Avg request total | Avg supervisor | Avg embedding | Avg post-processing | Avg LLM total |
|---|---:|---:|---:|---:|---:|---:|
| `gemini-2.5-flash` | 1 | 25294ms | 7355ms | 1889ms | 11930ms | 21174ms |
| `gemini-2.5-flash-lite` | 1 | 10624ms | 1389ms | 576ms | 2357ms | 4322ms |

## Kết Luận Nhanh

- `gemini-2.5-flash-lite` cải thiện request total trung bình so với `gemini-2.5-flash`: `58.0%`.
- `embedding` gần như không thay đổi vì vẫn dùng `gemini-embedding-001`; model text chỉ ảnh hưởng `supervisor` và `post_processing`.
- Nếu cần chatbot nhanh hơn nữa, bước tiếp theo nên tối ưu số lần gọi LLM tuần tự, không chỉ đổi model.

## Chi Tiết Từng Test Case

### TC-ALG-001 - Dị ứng động vật giáp xác

Query: "Tôi bị dị ứng tôm cua ghẹ, muốn ăn món hải sản, giàu đạm, ăn tối ở Đà Nẵng."

Trước đây (`gemini-2.5-flash`):
supervisor:       7355ms
embedding:        1889ms
post_processing:  11930ms
LLM total:       ~21174ms
request total:    25294ms

Hiện tại (`gemini-2.5-flash-lite`):
supervisor:       1389ms
embedding:        576ms
post_processing:  2357ms
LLM total:       ~4322ms
request total:    10624ms

Cải thiện request total: `58.0%`
