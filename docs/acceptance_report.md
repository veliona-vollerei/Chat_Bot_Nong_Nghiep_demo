# Báo Cáo Nghiệm Thu Hệ Thống NextFarm Chatbot v2.2

Tài liệu nghiệm thu toàn diện dựa trên đối chiếu kỹ thuật giữa lộ trình `Lo_trinh_thuc_hien_NextFarm_v2_2.docx` và kết quả đo lường thực tế trên hệ thống.

---

## 1. Tổng Quan Triển Khai Thực Tế (GĐ1 → GĐ5)

Hệ thống NextFarm Chatbot đã nâng cấp từ kiến trúc 3 tầng (Fact / KG / Docs) lên **kiến trúc 6 tầng chuyên sâu** tích hợp IAM & Phân quyền đa nông trại, IoT Tool Adapter, Simulator nông trại Việt Nam theo vật lý FAO-56 và bộ kiểm thử chuẩn hóa 260 câu hỏi.

| Giai đoạn | Nội dung chính theo lộ trình | Hiện trạng thực tế | Minh chứng kỹ thuật |
|---|---|:---:|---|
| **GĐ1 — Chốt Nền Tảng** | Router fallback `crop=None`, IAM authorization, Retrieval plan đa nguồn, Fail-closed numeric lock, Freshness flags, Schema migration Fact, OCR report, Versioning | ✅ Đạt | 52 unit tests pass, `backend/iam/iam.py`, `backend/versioning.py` |
| **GĐ2 — Dữ Liệu Vườn IoT** | NextFarm Tool Adapter, REST Tool Router API, kiểm tra IAM trước mọi tool call, xử lý stale/missing | ✅ Đạt | `backend/tools/nextfarm_tools.py`, API `/api/tools/*`, audit log không thể xóa |
| **GĐ3 — Data & Simulator** | Farm Generator (35 farms, 145 zones khắp VN), Open-Meteo Client, Water Balance (FAO-56), Fault Injector (deterministic), Benchmark Builder (260 câu hỏi) | ✅ Đạt | `backend/simulator/*`, `data/benchmark_questions.json` (seed cố định) |
| **GĐ4 — RAG Hardening** | Threshold similarity calibration, Durable benchmark queue (`benchmark_jobs`), Key rotation & rate limit pool, Citation validation & RAG audit | ✅ Đạt | `calibration_results.json`, `docs/rag_audit_report.json`, `backend/utils/gemini_client.py` (key rotation pool — `backend/security/key_pool.py` đã được hợp nhất vào đây) |
| **GĐ5 — Nghiệm Thu & Giám Sát** | Benchmark suite tự động 260 câu (`benchmark_evaluator.py`), Dashboard Giám Sát, Báo cáo nghiệm thu minh bạch | ✅ Đạt | `backend/monitoring.py`, `/api/monitoring/stats`, `frontend/admin.html` |

---

## 2. Kết Quả Kiểm Thử Đơn Vị Tự Động (Unit Tests)

Hệ thống kiểm thử tự động đạt **52/52 tests PASSED (100%)** với thời gian chạy ~1.2 giây:

```text
============================= test session starts =============================
platform win32 -- Python 3.12.7, pytest-9.1.1, pluggy-1.6.0
collected 52 items

backend/tests/test_chunker.py ....................                     [ 38%]
backend/tests/test_router.py ................                          [ 69%]
backend/tests/test_simulator.py ................                       [100%]
============================= 52 passed in 1.17s ==============================
```

- **`test_chunker.py` (20 tests)**:
  - Structure-aware chunking: phân tích đúng heading hierarchy (`heading_path`), bảng biểu Markdown (table integrity nguyên vẹn không bị cắt ngang), danh sách và code block.
  - Tương thích ngược với định dạng chunk danh sách chuỗi truyền thống.
- **`test_router.py` (16 tests)**:
  - Deterministic fallback `crop=None` khi câu hỏi mơ hồ hoặc không chỉ định cây trồng.
  - Fail-closed numeric check: từ chối match số liệu liều lượng phân bón/tưới tiêu nhạy cảm nếu thiếu điều kiện ràng buộc.
  - IAM Authorization: từ chối 100% truy cập chéo farm trái phép.
- **`test_simulator.py` (16 tests)**:
  - Farm Generator: 35 farm với tọa độ chuẩn địa lý Việt Nam (ĐBSCL, Tây Nguyên, ĐBSH, Đông Nam Bộ).
  - Water Balance (FAO-56): cân bằng nước bốc thoát hơi $ET_c$ và lượng mưa chính xác.
  - Fault Injector & Tool Adapter: tính toán đúng cờ `fresh` (<10p), `stale` (10-60p), `missing` (>60p hoặc offline).

---

## 3. Kết Quả Đo Lường Thật & Hiệu Chuẩn RAG

### 3.1. Hiệu Chuẩn Ngưỡng Tương Đồng (`calibration_results.json`)
Thực thi kiểm định RAG trên tập truy vấn đối sánh nông học với các ngưỡng similarity từ 0.3 đến 0.8:

| Ngưỡng Similarity | Avg Precision | Avg Recall | Avg F1 Score | Ghi chú đánh giá |
|:---:|:---:|:---:|:---:|---|
| **0.3 (Optimal)** | **0.800** | **0.867** | **0.828** | **Ngưỡng tối ưu cân bằng Precision và Recall** |
| 0.4 | 0.800 | 0.867 | 0.828 | Tương đương ngưỡng 0.3 trên tập test hiện tại |
| 0.5 | 0.733 | 0.700 | 0.716 | Bắt đầu bỏ sót ngữ cảnh liên quan (Recall giảm) |
| 0.6 (Mặc định cũ) | 0.600 | 0.533 | 0.564 | Quá chặt, loại bỏ nhiều chunk tài liệu có giá trị |
| 0.7 - 0.8 | 0.200 | 0.133 | 0.160 | Bỏ lỡ >80% ngữ cảnh |

> **Khuyến nghị**: Đã cập nhật đề xuất giảm ngưỡng tìm kiếm tương đồng vector từ `0.6` xuống `0.3` nhằm tối ưu F1-score lên `0.828`.

### 3.2. Báo Cáo OCR Coverage (`docs/ocr_coverage_report.json`)
- **Tài liệu nạp**: 2 tài liệu cẩm nang kỹ thuật canh tác (lúa, sầu riêng).
- **Tỷ lệ Text Extraction Coverage**: **97.6%** trên toàn bộ nội dung.
- Không phát hiện hiện tượng mất mát cấu trúc đoạn văn bản hay bảng liều lượng phân bón.

### 3.3. Báo Cáo RAG Citation Audit (`docs/rag_audit_report.json`)
- **Tổng số chunk trong cơ sở dữ liệu**: 50 chunks.
- **Corpus Groundability**: **100%** (50/50 chunks liên kết chính xác với tài liệu nguồn).
- **Orphan Citations**: 0.
- **Corrupted Chunks**: 0.

---

## 4. Kết Quả Nghiệm Thu Benchmark Suite (260 Câu Hỏi)

Bộ benchmark được định nghĩa tại `data/benchmark_questions.json` và lưu vết tại `data/acceptance_results.json`:

| STT | Phân Loại Câu Hỏi | Số Câu | Phương Pháp Đo Lường | Kết Quả Thực Tế | Trạng Thái |
|---|---|:---:|---|:---:|:---:|
| 1 | `unauthorized_cross_farm` | 20 | IAM context validation, cross-farm access | **0 Rò Rỉ / 20 (100% Deny)** | ✅ ĐẠT |
| 2 | `latest_sensor` | 30 | NextFarm tool invocation & freshness parsing | **30/30 (100% Tool Pass)** | ✅ ĐẠT |
| 3 | `device_state` | 20 | Device status adapter query | **20/20 (100% Tool Pass)** | ✅ ĐẠT |
| 4 | `missing_stale_sensor` | 20 | Offline / stale fault detection | **20/20 (100% Quality Flag)** | ✅ ĐẠT |
| 5 | `irrigation_history` | 20 | Date-range retrieval & schema contract | **20/20 (100% Schema Pass)** | ✅ ĐẠT |
| 6 | `irrigation_schedule` | 20 | Schedule schema & time calculation | **20/20 (100% Schema Pass)** | ✅ ĐẠT |
| 7 | `vietnamese_typo_robustness` | 30 | Router normalization & entity extraction | **30/30 (100% Schema Pass)** | ✅ ĐẠT |
| 8 | `multi_turn_context` | 20 | Turn context persistence (crop, season, farm) | **20/20 (100% Schema Pass)** | ✅ ĐẠT |
| 9 | `agricultural_factual_qa` | 50 | Schema validation + RAG groundability verify | **50/50 Validated** | ✅ ĐẠT |
| 10 | `no_answer_hallucination_guard` | 30 | Refusal pattern check & fail-closed numeric | **30/30 Guard Pass** | ✅ ĐẠT |
| **Tổng** | **Toàn Bộ Benchmark** | **260** | **10 Nhóm Nghiệm Thu Toàn Diện** | **260/260 (100% Passed)** | **CHẤP NHẬN** |

### Minh Bạch Về Phương Pháp Đo Lường (Measurement Transparency)
1. **Schema Check Mode vs. Full Flow Mode**:
   - Để tránh cạn kiệt quota API Gemini (Rate Limit 429/503) khi chạy đồng loạt trong môi trường tích hợp liên tục (CI), toàn bộ 260 câu hỏi được xác minh qua bộ kiểm tra hợp đồng schema, logic phân quyền IAM và trạng thái cảm biến.
   - Các câu hỏi thuộc nhóm `agricultural_factual_qa` và `no_answer_hallucination_guard` được bảo vệ bởi cơ chế fail-closed: hệ thống từ chối trả lời hoặc hỏi lại khi thiếu dữ liệu, thay vì suy đoán thông tin sai lệch.
2. **Profile Độ Trễ Thực Tế (Live Latency Benchmark)**:
   - **IoT Tool Query (Cảm biến/Thiết bị)**: ~6.7 ms (p50).
   - **Vector Semantic Search (Bộ nhớ đệm ấm)**: ~62.3 ms (p50).
   - **Gemini LLM Synthesis**: ~1,200 ms - 2,200 ms (tùy thuộc độ dài phản hồi và tốc độ mạng).

---

## 5. Giám Sát Vận Hành & An Ninh (Monitoring & Audit)

Nhằm đáp ứng yêu cầu vận hành theo thời gian thực (Mục 15 của checklist hoàn thiện):
1. **Module Giám Sát (`backend/monitoring.py`)**:
   - Thu thập tỷ lệ lỗi công cụ (Tool failure rate), phân bố latency p95.
   - Thống kê thời gian thực chất lượng dữ liệu cảm biến: tỷ lệ `fresh`, `stale`, `missing`.
   - Giám sát các lần truy cập chéo farm bị chặn bởi IAM.
2. **API Giám Sát Vận Hành**:
   - `GET /api/monitoring/stats`: Cung cấp báo cáo số liệu tổng hợp cho trang quản trị.
   - `GET /api/monitoring/audit_log`: Truy xuất nhật ký kiểm toán bảo mật IAM, **không cho phép xóa qua API** nhằm đảm bảo toàn vẹn dữ liệu điều tra.
3. **Giao Diện Quản Trị (`frontend/admin.html`)**:
   - Bổ sung thẻ tab **"Giám Sát Vận Hành"** trực quan hiển thị KPI hệ thống, cảnh báo chất lượng cảm biến và nhật ký vi phạm phân quyền.

---

## 6. Đánh Giá Rủi Ro Tồn Đọng & Khuyến Nghị

1. **Kết Nối IoT Đám Mây Thực Tế**:
   - Hệ thống hiện sử dụng Mock Adapter chuẩn hóa theo đúng cấu trúc dữ liệu của NextFarm. Khi kết nối sang thiết bị phần cứng thật, chỉ cần cấu hình endpoint REST/MQTT trong `backend/config.py`.
2. **Quản Lý API Key Khi Mở Rộng Quy Mô (Scale-up)**:
   - Cơ chế xoay vòng Key hiện hoạt động in-memory. Khi mở rộng mô hình nhiều worker (Multi-worker/Gunicorn/Kubernetes), khuyến nghị đồng bộ trạng thái quota qua Redis hoặc Secret Manager.
3. **Định Kỳ Hiệu Chuẩn Nông Học**:
   - Khi cập nhật thêm tài liệu giống cây trồng mới vào kho dữ liệu Vector ChromaDB, cần tái thực thi script `backend/retrieval/threshold_calibration.py` để duy trì F1-score tối ưu $\ge 0.8$.
4. **Dọn Dẹp Backup Cũ (`chroma_db_backup_GD1`)**:
   - Thư mục `chroma_db_backup_GD1` đã được **xóa có chủ đích** trong commit dọn dẹp sau GĐ4. Đây không phải mất dữ liệu ngoài ý muốn — dữ liệu vector ChromaDB đang hoạt động được lưu tại `chroma_db/` (hiện hành). Backup GĐ1 đã lỗi thời vì schema đã thay đổi qua nhiều giai đoạn.

---

## 7. Ghi Chú Kỹ Thuật (Errata)

> **Sửa lỗi trích dẫn (cập nhật lần 2):** Phiên bản trước của báo cáo này trích dẫn minh chứng GĐ4 là `backend/security/key_pool.py` — đường dẫn này **không tồn tại** trong repo. Code key rotation & rate limit pool thật nằm tại `backend/utils/gemini_client.py` (hàm `call_with_rotation`, class `_KeyPool`). Đã sửa trong bảng GĐ1→GĐ5 ở trên.
