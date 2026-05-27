# Evidence So Sánh Model AI

Tài liệu này dùng để lưu bằng chứng thực nghiệm khi lựa chọn model AI cho pipeline gợi ý món ăn.

## Mục Tiêu

So sánh tốc độ phản hồi giữa các model text Gemini đang dùng trong backend, tập trung vào hai model:

- `gemini-2.5-flash`
- `gemini-2.5-flash-lite`

Metric chính:

- `supervisor`: thời gian LLM phân tích ý định, bệnh lý, sở thích ăn uống.
- `embedding`: thời gian tạo embedding truy vấn bằng `gemini-embedding-001`.
- `post_processing`: thời gian LLM viết câu trả lời tư vấn tự nhiên.
- `LLM total`: tổng `supervisor + embedding + post_processing`.
- `request total`: tổng thời gian xử lý một request search.

## Nguồn Test Case

File test case:

```text
[GTP26] Test case - Test Case bệnh lý.csv
```

Script benchmark sẽ đọc cột:

- `Test Case ID`
- `Nhóm`
- `Tag kiểm chứng`
- `Prompt test`
- `Mục tiêu kiểm thử`
- `Expected Result`

## Cách Chạy Benchmark

Chạy nhanh 3 test case đầu để kiểm tra:

```bash
./venv/bin/python scripts/benchmark_ai_models.py --limit 3 --sleep 1
```

Chạy toàn bộ test case:

```bash
./venv/bin/python scripts/benchmark_ai_models.py --sleep 1
```

Chỉ định model tùy ý:

```bash
./venv/bin/python scripts/benchmark_ai_models.py \
  --models gemini-2.5-flash gemini-2.5-flash-lite \
  --output docs/ai_model_selection_evidence.md \
  --sleep 1
```

Script sẽ tự:

1. Đọc danh sách query từ file test case.
2. Set `GEMINI_TEXT_MODEL` lần lượt theo từng model.
3. Gọi trực tiếp `search_food()` để tránh nhiễu từ frontend.
4. Lấy latency từng stage từ `query_logs.excluded_summary.llm_runtime.stage_latency_ms`.
5. Ghi lại kết quả vào file Markdown evidence.

## Evidence Mẫu Đã Đo

### TC-SYM - Nhiệt miệng / Loét miệng

Query: "Tôi đang bị nhiệt miệng đau lắm, ăn gì cho mau khỏi và bớt đau?"

Trước đây (`gemini-2.5-flash`):

```text
supervisor:       6456ms
embedding:        1608ms
post_processing: 10473ms
LLM total:       ~18537ms
```

Hiện tại (`gemini-2.5-flash-lite`):

```text
supervisor:       2425ms
embedding:        1567ms
post_processing:  2484ms
request total:   8080ms
```

Nhận xét:

- `gemini-2.5-flash-lite` cải thiện rõ nhất ở `post_processing`.
- `embedding` gần như không đổi vì pipeline vẫn dùng `gemini-embedding-001`.
- Với query này, thời gian xử lý giảm từ khoảng 18-20s xuống khoảng 8s.

## Format Ghi Evidence Cho Từng Case

```text
Query: "<nội dung Prompt test>"

Trước đây (`gemini-2.5-flash`):
supervisor:       <...>ms
embedding:        <...>ms
post_processing:  <...>ms
LLM total:       ~<...>ms
request total:    <...>ms

Hiện tại (`gemini-2.5-flash-lite`):
supervisor:       <...>ms
embedding:        <...>ms
post_processing:  <...>ms
LLM total:       ~<...>ms
request total:    <...>ms

Cải thiện request total: `<...>%`
```

## Kết Luận Tạm Thời

Dựa trên phép đo ban đầu, `gemini-2.5-flash-lite` phù hợp hơn cho chế độ chatbot cần phản hồi nhanh. Tuy nhiên, để kết luận chắc chắn cho đồ án, cần chạy toàn bộ bộ test case và xem đồng thời cả tốc độ lẫn chất lượng phản hồi.
