# Checklist Hoàn Thiện Nghiệm Thu — NextFarm Chatbot v2.2 (Cập nhật lần 2)

> So với bản checklist trước, repo đã có 3 commit mới. Đã pull về, đọc code, chạy thử số liệu thật để xác minh — không chỉ tin vào `docs/acceptance_report.md` tự viết.

---

## ✅ Đã sửa THẬT — có bằng chứng cụ thể

| Hạng mục | Trước | Bây giờ | Bằng chứng |
|---|---|---|---|
| Threshold calibration | Không có file | ✅ Có | `calibration_results.json`: latency thật 1.0–1046.3ms, `optimal_threshold=0.3`, F1=0.828 (không phải số giả) |
| Dashboard giám sát | Không có code | ✅ Có | `/api/monitoring/stats`, `/api/monitoring/audit_log` trong `app.py`, nối đúng vào tab Monitoring trong `admin.html` |
| OCR/RAG audit report | Chỉ có code, không có output | ✅ Có | `docs/ocr_coverage_report.json`, `docs/rag_audit_report.json` đã tồn tại |
| IAM logging | Chỉ log ra console | ✅ Có | `iam.py` giờ gọi `record_iam_check()` để đẩy vào `monitoring.py` — mọi lượt allow/deny đều được ghi nhận có hệ thống, không chỉ log rời rạc |
| Minh bạch evaluation mode | Không rõ ràng | ✅ Có | Code ghi rõ `evaluation_mode: "schema_check_only"` hay `"full_flow"` vào kết quả — không giấu cách chấm điểm |
| `fast_mode` → đổi tên | — | ⚠️ Chỉ đổi tên | Giờ gọi là `schema_check_only`, mặc định hàm đã đổi thành `False` (tốt), nhưng… (xem mục dưới) |

---

## 🔴 Vẫn CHƯA sửa xong — cần làm tiếp

### 1. Kết quả nghiệm thu chính thức (260 câu) vẫn dùng chế độ rút gọn
**Vấn đề:** Dù code đã hỗ trợ chấm điểm thật (`full_flow`, mặc định giờ là `False` cho `schema_check_only` — tức đã chuyển default sang full_flow), nhưng file `data/acceptance_results.json` đang có trong repo vẫn ghi:
```json
"evaluation_mode": "schema_check_only",
"p50_latency_ms": 0.0, "p90_latency_ms": 0.0, "p95_latency_ms": 0.0,
"status": "ACCEPTED"
```
→ Nghĩa là lần chạy nghiệm thu **thực tế được lưu vào repo** vẫn là chế độ rút gọn (có thể do người chạy dùng flag `--fast` hoặc `--schema-check-only` khi gọi CLI), nhưng status vẫn ghi "ACCEPTED" — dễ gây hiểu lầm là đã nghiệm thu thật.

**Việc cần làm:**
- [ ] Chạy lại: `python -m backend.simulator.benchmark_evaluator` **KHÔNG** truyền `--fast` / `--schema-check-only`
- [ ] Xác nhận `acceptance_results.json` mới có `evaluation_mode: "full_flow"` và latency > 0
- [ ] Chỉ gắn `status: "ACCEPTED"` sau khi có full_flow thật

### 2. Calibration chỉ chạy trên 6 câu — quá ít để tin cậy
**Vấn đề:** `calibration_results.json` xác nhận số liệu thật (latency thật, không giả), nhưng chỉ có **6 câu hỏi** cho mỗi threshold. Recall@k/F1 tính trên mẫu quá nhỏ không đủ ý nghĩa thống kê.

**Việc cần làm:**
- [ ] Mở rộng validation set lên tối thiểu 30–50 câu, phủ đều 10 category benchmark
- [ ] Chạy lại calibration, xác nhận `optimal_threshold` không đổi nhiều so với kết quả 6 câu hiện tại

### 3. Sai lệch đường dẫn trong báo cáo nghiệm thu
**Vấn đề:** `docs/acceptance_report.md` (GĐ4) trích dẫn minh chứng là `backend/security/key_pool.py`, nhưng thư mục này **không tồn tại** — code key rotation thật nằm ở `backend/utils/gemini_client.py`.

**Việc cần làm:**
- [ ] Sửa lại đường dẫn minh chứng trong `acceptance_report.md` cho đúng thực tế
- [ ] Rà soát toàn bộ báo cáo xem còn đường dẫn nào trích sai không (dấu hiệu báo cáo có thể do AI viết chưa đối chiếu kỹ với code thật)

### 4. Review nông học với chuyên gia thật
**Vẫn chưa có bằng chứng nào** trong repo cho thấy đã có chuyên gia nông nghiệp thật review — đây là việc không thể làm bằng code, cần con người thật thực hiện và ghi nhận kết quả (`expert_acceptance_rate`, `factual_error_rate`) vào báo cáo.

---

## 🟡 Việc nên làm thêm (không bắt buộc nhưng nên có)

- [ ] Audit log IAM/monitoring cần đảm bảo **không thể xóa/sửa** bởi bất kỳ role nào kể cả admin (kiểm tra lại quyền ghi vào bảng log)
- [ ] Thêm alerting tự động (không chỉ dashboard xem thụ động) khi hallucination rate hoặc IAM leak vượt ngưỡng
- [ ] `chroma_db_backup_GD1` đã bị xóa trong commit mới — xác nhận đây là dọn dẹp có chủ đích, không phải mất dữ liệu backup ngoài ý muốn

---

## Tóm tắt

**Tiến bộ rõ rệt** so với lần kiểm tra trước — 4/4 vấn đề P0 cũ đã có code sửa thật (không phải chỉ thêm tài liệu suông). Tuy nhiên **file kết quả nghiệm thu chính thức trong repo vẫn chưa phản ánh đúng năng lực mới của code** — cần chạy lại một lần cuối ở chế độ `full_flow` đầy đủ, mở rộng calibration set, và sửa vài chỗ trích dẫn sai trong báo cáo trước khi có thể coi là "đã nghiệm thu" một cách đáng tin cậy.
