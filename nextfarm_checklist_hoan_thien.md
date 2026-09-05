# Checklist Hoàn Thiện Nghiệm Thu — NextFarm Chatbot v2.2

> Dựa trên đối chiếu thực tế giữa `Lo_trinh_thuc_hien_NextFarm_v2_2.docx` và code trong repo `chatbot`.
> Đã xác minh bằng cách: clone repo, đọc code, **chạy thật** 52 unit test (đều pass), đọc kỹ `benchmark_evaluator.py` và các file kết quả JSON.

---

## 🔴 P0 — Bắt buộc trước khi được coi là "đã nghiệm thu"

### 1. Sửa `benchmark_evaluator.py` — bỏ chấm điểm giả (`fast_mode`)
**Vấn đề:** Nhóm `agricultural_factual_qa` (50 câu) và `no_answer_hallucination_guard` (30 câu) — 2 nhóm quan trọng nhất để đo hallucination — hiện chỉ kiểm tra router trả về đúng *schema* (`"question_type" in routing`), **không kiểm tra nội dung câu trả lời cuối có đúng không**.

**Việc cần làm:**
- [ ] Viết pipeline chấm điểm gọi full flow: `route_question` → `execute_retrieval_plan` → Gemini synthesis → so sánh với oracle answer
- [ ] Với câu định lượng: exact-match hoặc so khớp số liệu trong oracle
- [ ] Với câu diễn giải: dùng LLM-as-judge (đã có ý tưởng trong PROGRESS.md nhưng chưa nối vào evaluator)
- [ ] Với `no_answer_hallucination_guard`: kiểm tra chatbot **thực sự từ chối / hỏi lại**, không phải chỉ routing hợp lệ
- [ ] Xóa hoặc đổi tên rõ ràng flag `fast_mode` thành `schema_check_only_mode` để không ai nhầm đây là kết quả nghiệm thu thật

### 2. Chạy calibration threshold thật
**Vấn đề:** File `calibration_results.json` (mục 7 lộ trình) **chưa từng tồn tại** dù `threshold_calibration.py` đã viết sẵn.

**Việc cần làm:**
- [ ] Chuẩn bị validation set: câu hỏi + tài liệu liên quan đã gán nhãn thủ công (relevant/not relevant)
- [ ] Chạy: `python -m backend.retrieval.threshold_calibration`
- [ ] Lưu báo cáo Recall@k, precision, context hit rate thật vào `calibration_results.json`
- [ ] Chỉ sau đó mới điều chỉnh ngưỡng similarity 0.35 dựa trên số liệu

### 3. Đo latency thật (p50/p95)
**Vấn đề:** `acceptance_results.json` hiện ghi **0.0ms cho mọi category** — bằng chứng chưa từng gọi Gemini API thật trong lần "nghiệm thu" trước.

**Việc cần làm:**
- [ ] Chạy lại `benchmark_evaluator.py` với API key Gemini thật, KHÔNG bật `fast_mode`
- [ ] Đo latency thực tế từng tool call + từng LLM call
- [ ] Cập nhật `acceptance_results.json` với số liệu thật, kèm phân tích chi phí theo lượt hội thoại (checklist mục 12)

### 4. Xây dashboard / alerting giám sát (checklist mục 15)
**Vấn đề:** Chưa có endpoint hay UI nào cho việc này — chỉ tồn tại trong sơ đồ mô tả kiến trúc, không có code thật.

**Việc cần làm:**
- [ ] Thêm endpoint `/api/monitoring/stats` trả về:
  - Tool failure rate, timeout, latency từng tool
  - Log cross-farm access bị chặn (không chỉ test 1 lần lúc nghiệm thu)
  - Tỷ lệ câu trả lời dùng dữ liệu sensor stale/missing theo thời gian thực
  - Hallucination rate theo thời gian
  - Recall@k / context hit rate theo thời gian
- [ ] Thêm trang admin hiển thị các số liệu trên (tận dụng khung có sẵn ở `frontend/admin.html`)
- [ ] Đảm bảo audit log lệnh điều khiển thiết bị **không tắt được** (theo đúng yêu cầu mục 6 lộ trình)

---

## 🟡 P1 — Cần thiết cho chất lượng, làm ngay sau P0

### 5. Review nông học với chuyên gia thật
**Vấn đề:** Không thể xác minh bằng code — cần con người thật.

**Việc cần làm:**
- [ ] Mời ít nhất 1 kỹ sư/chuyên gia nông nghiệp review một mẫu câu trả lời thực tế của hệ thống (đề xuất: tối thiểu 30-50 câu ngẫu nhiên từ benchmark)
- [ ] Ghi nhận `expert acceptance rate` và `factual error rate` thật, đưa vào báo cáo nghiệm thu

### 6. Chạy các báo cáo audit đã viết code nhưng chưa từng chạy
**Vấn đề:** `rag_audit.py` và `ocr_coverage.py` có code hoàn chỉnh nhưng không tìm thấy file output nào — nghĩa là chưa từng chạy trên corpus thật.

**Việc cần làm:**
- [ ] Chạy `python -m backend.ingestion.ocr_coverage --dir data/raw_uploads`, lưu báo cáo coverage thật
- [ ] Chạy `rag_audit.py` trên toàn bộ corpus đã ingest, lưu báo cáo citation validation thật

### 7. Viết lại `docs/acceptance_report.md` với số liệu thật
**Việc cần làm:**
- [ ] Sau khi có kết quả thật từ mục 1-6, viết lại báo cáo — bỏ các dòng "Đạt 100%" khi thực chất chỉ là schema check
- [ ] Ghi rõ phương pháp đo cho từng metric để tránh hiểu nhầm sau này

---

## 🟢 P2 — Cải thiện vận hành dài hạn (có thể làm sau khi nghiệm thu)

### 8. Rate limit & secret management tập trung
**Vấn đề:** Hiện tại key rotation Gemini chỉ ở dạng in-memory (per-worker) — chưa đủ nếu triển khai multi-worker/HA.

**Việc cần làm:**
- [ ] Nếu có kế hoạch chạy nhiều worker: chuyển rate limit/key state sang Redis hoặc DB dùng chung
- [ ] Đánh giá lại secret management (hiện dùng biến môi trường `.env` — cân nhắc vault nếu lên production)

---

## Tóm tắt trạng thái hiện tại (đã xác minh bằng code + chạy test)

| Hạng mục | Trạng thái thật |
|---|---|
| Router fallback crop=None | ✅ Có code + unit test pass |
| IAM/Farm authorization | ✅ Có code + unit test pass |
| Retrieval plan đa nguồn | ✅ Có code (asyncio.gather) |
| Fail-closed numeric lock | ✅ Có code + unit test pass |
| Freshness/quality sensor | ✅ Có code + unit test pass |
| Schema Fact chuẩn hóa | ✅ Có migration đầy đủ |
| Threshold calibration | ⚠️ Có code, **chưa từng chạy thật** |
| Chunking structure-aware | ✅ Có code + unit test pass |
| OCR coverage report | ⚠️ Có code, **chưa có output thật** |
| Benchmark job queue durable | ✅ Có bảng `benchmark_jobs` trong DB |
| Key rotation / rate limit | ✅ Có, nhưng chỉ in-memory |
| Safety design điều khiển thiết bị | ✅ Có tài liệu thiết kế |
| Versioning xuyên suốt | ✅ Có `versioning.py` |
| Benchmark 260 câu | ✅ Có đủ 260 câu, đúng 10 category |
| **Chấm điểm benchmark thật** | ❌ **Đang chạy fast_mode — chưa đo thật** |
| **Latency thật** | ❌ **0.0ms — chưa từng gọi API thật** |
| **Dashboard giám sát** | ❌ **Chưa có code** |
| **Expert review nông học** | ❌ **Chưa thực hiện** |

**Kết luận:** Nền tảng kỹ thuật (P0 GĐ1) đã vững, nhưng phần "nghiệm thu" (GĐ5) hiện mới chỉ là bộ khung — cần chạy thật 4 hạng mục P0 ở trên trước khi công bố hệ thống đã hoàn thành.
