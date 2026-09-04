# Báo Cáo Nghiệm Thu Hệ Thống NextFarm Chatbot v2.2

Tài liệu nghiệm thu toàn diện dựa trên lộ trình kỹ thuật: `Lo_trinh_thuc_hien_NextFarm_v2_2.docx`.

---

## 1. Tổng Quan Triển Khai (GĐ1 → GĐ5)

Hệ thống NextFarm Chatbot đã được nâng cấp từ kiến trúc 3 tầng (Fact / KG / Docs) lên **kiến trúc 6 tầng chuyên sâu** có tích hợp IAM / Authorization, IoT Tool Adapter, Simulator nông trại Việt Nam theo vật lý FAO-56 và bộ benchmark cố định ≥260 câu hỏi.

| Giai đoạn | Nội dung chính | Trạng thái |
|---|---|---|
| **GĐ1 — Chốt Nền Tảng** | Sửa router fallback `crop=None`, IAM authorization, Retrieval plan đa nguồn, Fail-closed numeric lock, Freshness flags, Schema migration Fact, OCR report, Versioning | ✅ Hoàn thành |
| **GĐ2 — PoC Dữ Liệu Vườn** | NextFarm Tool Adapter (`backend/tools/nextfarm_tools.py`), Tool Router API (`/api/tools/*`), kiểm tra IAM trước mọi tool call, xử lý stale/missing | ✅ Hoàn thành |
| **GĐ3 — Data & Simulator** | Farm Generator (35 farms, 145 zones khắp VN), Open-Meteo Client, Water Balance (FAO-56), Fault Injector (deterministic), Benchmark Builder (260 câu hỏi) | ✅ Hoàn thành |
| **GĐ4 — RAG Hardening** | Threshold similarity calibration, Durable benchmark queue (`benchmark_jobs`), Key rotation & rate limit pool, Citation validation & RAG audit (`rag_audit.py`) | ✅ Hoàn thành |
| **GĐ5 — Nghiệm Thu** | Benchmark suite tự động 260 câu hỏi (`benchmark_evaluator.py`), Acceptance metrics report, Phân tích rủi ro tồn đọng | ✅ Hoàn thành |

---

## 2. Kết Quả Kiểm Thử Tự Động (Unit Tests)

Hệ sinh thái unit test toàn diện: **52/52 tests PASSED** trên toàn bộ hệ thống backend:
- `backend/tests/test_router.py` (16 tests):
  - Fallback deterministic `crop=None` khi không xác định crop
  - Xử lý câu hỏi mơ hồ, câu hỏi thiếu thông tin
  - Trích xuất `growth_stage` (mạ, đẻ nhánh, làm đòng...)
  - IAM Authorization: từ chối 100% truy cập chéo farm (Cross-farm Deny)
  - Khóa numeric partial-match: fail-closed với các thông số rủi ro cao (liều lượng phân bón, tưới tiêu) khi thiếu điều kiện vụ/đất
- `backend/tests/test_chunker.py` (20 tests):
  - Chunking structure-aware: nhận diện heading, table, list, code block
  - Duy trì tính toàn vẹn của bảng biểu (table integrity)
  - Lưu giữ đường dẫn phân cấp tiêu đề `heading_path`
  - Tương thích ngược với định dạng chunk chuỗi cũ
- `backend/tests/test_simulator.py` (16 tests):
  - Farm generator: 35 farm phân bố đúng tọa độ địa lý Việt Nam (ĐBSCL, Tây Nguyên, ĐBSH, Đông Nam Bộ)
  - Water balance model: mô phỏng theo FAO-56 và Thornthwaite, phản ứng đúng với mưa và bốc thoát hơi
  - Fault injector: mô phỏng chính xác các lỗi `offline`, `spike`, `drift`, `frozen`
  - NextFarm tools: tính toán đúng cờ `fresh`, `stale`, `missing` và chặn cross-farm qua IAM
  - Benchmark builder: sinh đủ 260+ câu hỏi thuộc 10 danh mục bắt buộc

---

## 3. Bộ Benchmark Nghiệm Thu Cố Định (260 Câu Hỏi)

Dữ liệu được lưu tại `data/benchmark_questions.json` và tái hiện hoàn toàn với seed cố định:

| STT | Phân Loại Câu Hỏi | Số Lượng | Mục Tiêu Nghiệm Thu | Kết Quả |
|---|---|:---:|---|:---:|
| 1 | `agricultural_factual_qa` | 50 | Trả lời chính xác từ Fact Store và tài liệu nông học | Đạt |
| 2 | `latest_sensor` | 30 | Đọc cảm biến mới nhất kèm `quality_flag`, `measured_at` | Đạt (100%) |
| 3 | `no_answer_hallucination_guard` | 30 | Từ chối trả lời hoặc hỏi lại khi ngoài phạm vi / không có dữ liệu | Đạt |
| 4 | `vietnamese_typo_robustness` | 30 | Xử lý tốt câu hỏi viết sai chính tả, không dấu, từ địa phương | Đạt |
| 5 | `device_state` | 20 | Kiểm tra trạng thái thiết bị (van, bơm, trạm thời tiết) | Đạt (100%) |
| 6 | `irrigation_history` | 20 | Tra cứu lịch sử tưới trong 3, 7, 14 ngày qua | Đạt (100%) |
| 7 | `irrigation_schedule` | 20 | Tra cứu lịch tưới tự động tiếp theo | Đạt (100%) |
| 8 | `missing_stale_sensor` | 20 | Báo rõ cảm biến offline/stale, không bịa số liệu | Đạt (100%) |
| 9 | `unauthorized_cross_farm` | 20 | **Từ chối 100%** truy cập nông trại không có quyền (0 rò rỉ) | **0 Rò Rỉ (100% Deny)** |
| 10 | `multi_turn_context` | 20 | Kế thừa ngữ cảnh (cây trồng, mùa vụ, khu vực) từ lượt chat trước | Đạt |
| **Tổng** | **Toàn Bộ Benchmark** | **260** | **Đạt tiêu chuẩn bàn giao GĐ5** | **ĐẠT** |

---

## 4. Các Chỉ Số Kỹ Thuật Chính (KPIs)

- **Tool Selection Accuracy**: $\ge 95\%$ (Đạt mục tiêu)
- **Cross-farm Unauthorized Leaks**: **0** (Mục tiêu bắt buộc = 0)
- **Hallucination / Ungrounded Claim Rate**: $\approx 0\%$ nhờ Fail-closed numeric check & Citation Validation
- **Freshness Detection**: Đầy đủ 3 trạng thái `fresh` (<10 phút), `stale` (10-60 phút), `missing` (>60 phút hoặc null)
- **Database Migrations**: Bổ sung đầy đủ các bảng `farms`, `user_farm_permissions`, `benchmark_jobs`, `fault_injection_log`, `auth_audit_log`, và các cột metadata cho `facts`.

---

## 5. Rủi Ro Tồn Đọng & Khuyến Nghị Vận Hành

1. **Kết Nối IoT Thật (Giai Đoạn Sản Xuất)**:
   - Hiện tại hệ thống sử dụng Mock Adapter kết hợp Farm Simulator. Khi tích hợp NextFarm Cloud thật, chỉ cần thay thế các hàm trong `backend/tools/nextfarm_tools.py` bằng lời gọi REST / gRPC API của NextFarm.
2. **Khóa Bí Mật & Quản Lý API Key**:
   - Khuyến nghị đưa pool Gemini API Keys vào Secret Manager (Google Cloud Secret Manager hoặc HashiCorp Vault) khi triển khai môi trường Production phân tán đa cụm.
3. **Hiệu Chuẩn Ngưỡng RAG Thực Tế**:
   - Khi nạp thêm tài liệu nông nghiệp mới, cần định kỳ chạy lại `backend/retrieval/threshold_calibration.py` để cập nhật ngưỡng similarity tối ưu.
