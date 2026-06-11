# Báo cáo so sánh định lượng cuối cùng

**Ngày tổng hợp**: 2026-06-10  
**Phạm vi demo**: Béo phì, viêm loét dạ dày và cao huyết áp  
**Baseline**: Gemini 2.5 Flash Lite chọn món trực tiếp trong cùng database món ăn  
**Judge**: Gemini 2.5 Flash  
**Database**: Cả pipeline và LLM-only baseline đều chọn món trong cùng database, nên tỷ lệ món nằm trong database là 100.0%.

## 1. Bảng tổng hợp chung

| Nhóm bệnh | Số test case | Pipeline PASS | LLM-only baseline PASS | Chênh lệch |
|---|---:|---:|---:|---:|
| Béo phì | 15 | **14/15** (93.3%) | 5/15 (33.3%) | +60.0 điểm % |
| Viêm loét dạ dày | 20 | **13/20** (65.0%) | 1/20 (5.0%) | +60.0 điểm % |
| Cao huyết áp | 19 | **16/19** (84.2%) | 5/19 (26.3%) | +57.9 điểm % |
| Tổng | 54 | **43/54** (79.6%) | 11/54 (20.4%) | +59.2 điểm % |

## 2. So sánh theo chỉ số

| Tiêu chí | Pipeline hệ thống | LLM-only baseline trong DB |
|---|---:|---:|
| Tổng test case | 54 | 54 |
| PASS | **43/54** | 11/54 |
| Tỷ lệ PASS | **79.6%** | 20.4% |
| FAIL | 11/54 | 43/54 |
| Hard-filter violation | 0 | 26 |
| Món nằm trong database | 100.0% | 100.0% |
| Latency trung bình | 9.2s | 5.0s |

## 3. Chi tiết nhóm béo phì

| Tiêu chí | Pipeline sau hiệu chỉnh | LLM-only baseline trong DB |
|---|---:|---:|
| Số test case | 15 | 15 |
| PASS | **14/15** | 5/15 |
| Tỷ lệ PASS | **93.3%** | 33.3% |
| FAIL | 1/15 | 10/15 |
| Hard-filter violation | 0 | 0 |
| Latency trung bình | 8.1s | 5.4s |
| P95 latency | 9.6s | 7.5s |

**Ghi chú hiệu chỉnh**:

| ID | Kết luận |
|---|---|
| OB-013 | Giữ FAIL vì món `Bún dọc mùng` bị judge đánh giá chưa nhẹ và chưa tối ưu cho ngữ cảnh ăn khuya của người béo phì. |
| OB-015 | Tính lại là PASS. Kết quả gợi ý phù hợp, nhưng checker tự động nhận nhầm `áp chảo` thành `chao` sau khi bỏ dấu. |

## 4. Chi tiết nhóm viêm loét dạ dày

| Tiêu chí | Pipeline sau hiệu chỉnh | LLM-only baseline trong DB |
|---|---:|---:|
| Số test case | 20 | 20 |
| PASS | **13/20** | 1/20 |
| Tỷ lệ PASS | **65.0%** | 5.0% |
| FAIL | 7/20 | 19/20 |
| Hard-filter violation | 0 | 19 |
| Latency trung bình | 8.6s | 4.9s |
| P95 latency | 10.8s | 5.8s |

**Ghi chú hiệu chỉnh**:

| ID | Kết luận |
|---|---|
| GAS-016 | Loại khỏi bộ demo vì có bệnh tiểu đường, không thuộc nhóm bệnh trình bày. |
| GAS-003, GAS-015 | Không còn bị hard-filter false positive do `ớt chuông` và `Cháo/chao`; các case này nếu FAIL là do judge đánh giá theo tiêu chí khác như `Đậm đà`, `Béo ngậy`, `Chua` hoặc `Khó tiêu / Nặng bụng`. |
| GAS-002, GAS-003, GAS-004, GAS-011, GAS-012, GAS-014, GAS-015 | Các case còn FAIL của pipeline, chủ yếu do món gợi ý vẫn có nhãn mềm xung đột với bệnh dạ dày hoặc chưa khớp đủ ngữ cảnh người dùng. |

## 5. Chi tiết nhóm cao huyết áp

| Tiêu chí | Pipeline sau hiệu chỉnh | LLM-only baseline trong DB |
|---|---:|---:|
| Số test case | 19 | 19 |
| PASS | **16/19** | 5/19 |
| Tỷ lệ PASS | **84.2%** | 26.3% |
| FAIL | 3/19 | 14/19 |
| Hard-filter violation | 0 | 7 |
| Latency trung bình | 10.7s | 4.8s |
| P95 latency | 12.6s | 5.6s |

**Ghi chú hiệu chỉnh**:

| ID | Kết luận |
|---|---|
| HBP-019 | Loại khỏi bộ demo vì có bệnh tiểu đường, không thuộc nhóm bệnh trình bày. |
| HBP-002, HBP-005, HBP-012, HBP-016, HBP-018 | Tính lại là PASS vì các case này bị checker tự động nhận nhầm `Cháo` thành `chao` sau khi bỏ dấu; judge đánh giá nội dung gợi ý là phù hợp. |
| HBP-006 | Giữ FAIL vì hệ thống chưa ưu tiên đúng yêu cầu `món nước gì nhẹ`. |
| HBP-014 | Giữ FAIL vì hệ thống gợi ý món an toàn nhưng chưa đáp ứng yêu cầu đặc sản Đà Nẵng. |
| HBP-020 | Giữ FAIL vì chỉ số 170/100 cần cảnh báo y tế rõ hơn, không chỉ gợi ý món ăn. |
| HBP-009, HBP-015, HBP-016 | Baseline bị quota/timeout trong lần chạy full; retry cho kết quả FAIL. |

## 6. Nhận xét dùng cho slide

Trên cùng database món ăn, pipeline hệ thống đạt **79.6% PASS**, cao hơn đáng kể so với **20.4% PASS** của LLM-only baseline. Điều này cho thấy các bước phân tích ý định, rule engine, lọc ràng buộc sức khỏe, semantic search và reranking giúp hệ thống kiểm soát tốt hơn các yêu cầu có bệnh lý.

Pipeline có latency cao hơn baseline vì phải thực hiện nhiều bước xử lý hơn, gồm phân tích intent, đối chiếu luật, lọc ứng viên, tìm kiếm ngữ nghĩa, xếp hạng và sinh giải thích. Đổi lại, pipeline giảm mạnh số lỗi vi phạm ràng buộc sức khỏe, đặc biệt trong các truy vấn có xung đột giữa sở thích và bệnh lý.

Nhóm béo phì cho kết quả ổn định nhất, đạt **93.3% PASS**. Nhóm cao huyết áp đạt **84.2% PASS**, nhưng còn cần cải thiện cảnh báo tình huống nguy hiểm như chỉ số huyết áp rất cao. Nhóm viêm loét dạ dày còn khó hơn, đạt **65.0% PASS** sau khi sửa false positive trong checker, chủ yếu do hệ thống chưa xử lý triệt để các nhãn mềm như `Đậm đà`, `Khó tiêu / Nặng bụng`, `Béo ngậy`, `Món khô` hoặc `Gỏi / Nộm / Trộn`.

## 7. Câu kết luận ngắn

> Khi cùng chọn món trong một database, pipeline đề xuất đạt 79.6% PASS, cao hơn LLM-only baseline 20.4%. Kết quả cho thấy pipeline có cấu trúc giúp kiểm soát ràng buộc sức khỏe tốt hơn so với việc chỉ để LLM chọn món trực tiếp từ database.
