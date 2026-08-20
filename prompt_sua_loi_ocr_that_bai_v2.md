# Sửa lỗi OCR thất bại âm thầm trong data_pipeline.py

## Bối cảnh

File `merge_21.pdf` (286 trang scan) bị mất 267/286 trang (93.4%) khi ingest vì:

* Gemini Vision API bị rate limit do 5 luồng bắn request đồng thời
* `ocr_page_with_gemini()` chỉ retry 3 lần với backoff quá ngắn (2s/4s/6s)
* `process_and_ingest_document()` không kiểm tra tỷ lệ trang rỗng, vẫn báo `status: success`
* Chatbot trả lời "không có dữ liệu" dù tài liệu gốc có thông tin

**Ràng buộc kiến trúc quan trọng cần biết trước khi sửa:** `chunk_text()` gộp
nhiều trang liên tiếp vào cùng 1 chunk (VD: 1 chunk có thể chứa 38 trang gộp
lại nếu tổng dưới 800 ký tự). Vì vậy **không tồn tại quan hệ 1 trang = 1
chunk** — mọi logic "retry riêng 1 trang rồi update đúng 1 chunk" đều sai và
sẽ không hoạt động. Thiết kế bên dưới xử lý đúng ràng buộc này bằng cách
cache text theo từng trang riêng, và re-chunk lại toàn bộ tài liệu mỗi khi
có thay đổi.

---

## Proposed Changes

### `backend/ingestion/data_pipeline.py` [MODIFY]

**1. `ocr_page_with_gemini()` — Tăng độ bền retry**

* Tăng retry từ 3 lên 6 lần
* Backoff dài cho lỗi rate limit (429 / RESOURCE_EXHAUSTED):
  `10s → 20s → 40s → 60s → 90s → 120s` (6 mốc, khớp đúng 6 lần retry)
* Backoff ngắn cho lỗi tạm thời khác (500/502/503/504/UNAVAILABLE):
  `3s → 6s → 10s → 10s → 10s → 10s` (3 mốc tăng dần, các lần còn lại giữ
  nguyên 10s — không cần tăng vô hạn vì đây không phải lỗi do quá tải kéo
  dài như rate limit)
* Lỗi khác (không phải 2 nhóm trên): fail ngay, không retry (break)
* Hàm trả về thêm `error_type` khi thất bại hoàn toàn (VD: `"rate_limit"`,
  `"server_error"`, `"other"`, `None` nếu thành công) — dùng cho circuit
  breaker ở bước 2.

**2. `extract_text_from_pdf()` — Giảm đồng thời, xử lý theo batch, thêm circuit breaker**

* Giảm `max_workers` xuống 2 (thay vì 5)
* Xử lý scan pages theo batch 10 trang/đợt, nghỉ 5 giây giữa các đợt
* **Circuit breaker:** nếu **1 batch có ≥ 8/10 trang đều thất bại vì
  `error_type == "rate_limit"`**, dừng xử lý các batch còn lại ngay lập
  tức — đây là dấu hiệu rate limit toàn cục (không phải lỗi từng trang
  riêng lẻ), tiếp tục chỉ tốn thời gian mà chắc chắn cùng kết quả. Đánh
  dấu các trang chưa kịp xử lý là `"skipped_circuit_breaker"` (khác với
  `"failed"` — để phân biệt trang đã thử và thất bại thật với trang chưa
  kịp thử).
* **Lưu cache text theo từng trang** ngay sau khi xử lý xong (dù thành
  công hay thất bại), vào file
  `data/page_cache/{doc_id}_pages.json` dạng:
  ```json
  {
    "1": {"text": "...", "status": "ok"},
    "31": {"text": "", "status": "failed", "error_type": "rate_limit"},
    "32": {"text": "", "status": "skipped_circuit_breaker"}
  }
  ```
  Cache này là nguồn để `retry_failed_pages()` đọc/ghi mà không cần OCR
  lại các trang đã thành công.
* Trả về thêm `ocr_stats`:
  ```python
  {
      "total_scan_pages": int,
      "success": int,
      "failed": int,
      "skipped_circuit_breaker": int,
      "failed_pages": [int, ...],
      "circuit_breaker_triggered": bool,
  }
  ```

**3. Validate tỷ lệ trang rỗng sau OCR**

* Thêm hàm nội bộ `_count_empty_pages(pages_text) -> dict` — tính trực
  tiếp từ list `pages_text` đã có sẵn trong hàm (không parse lại bằng
  regex, tránh sai lệch với logic đang dùng để build `pages_text`).
* Ngưỡng trang rỗng: nội dung < 20 ký tự sau khi bỏ header
  `--- Trang N ---`.

**4. `process_and_ingest_document()` — Validate + partial_failure + full re-chunk**

* Sau khi `extract_text_from_pdf()`, kiểm tra `ocr_stats`.
* Nếu tỷ lệ trang thất bại (`failed + skipped_circuit_breaker`) so với
  tổng trang scan **> 15%**: trả `status: "partial_failure"` kèm
  `failed_pages`, **không** nạp chunk vào ChromaDB — tránh lặp lại đúng
  lỗi ban đầu (nạp dữ liệu rỗng coi như đã xong).
* Nếu ≤ 15%: nạp bình thường như hiện tại, nhưng vẫn trả kèm `ocr_stats`
  trong response để admin biết có bao nhiêu trang lỗi dù dưới ngưỡng.
* Ghi log rõ: `"X/Y trang OCR thất bại: [danh sách số trang]"`.

**5. Hàm mới `retry_failed_pages(pdf_path, doc_id) -> dict`**

Đọc `failed_pages` trực tiếp từ cache `data/page_cache/{doc_id}_pages.json`
thay vì nhận list từ tham số — tránh admin phải tự nhớ/nhập lại danh sách
trang lỗi.

* OCR lại **chỉ** các trang có `status != "ok"` trong cache (dùng lại
  `ocr_page_with_gemini()` với cùng cơ chế backoff/circuit breaker ở
  bước 1-2, nhưng với batch nhỏ hơn, VD 5 trang/đợt — vì đây là lần retry
  nên ưu tiên độ ổn định hơn tốc độ).
* Cập nhật cache: ghi đè kết quả mới cho các trang vừa retry.
* **Ghép lại toàn bộ text theo đúng thứ tự trang** (từ cache, không phải
  chỉ các trang vừa retry) → chạy lại `chunk_text()` cho **toàn bộ tài
  liệu** → có bộ chunk mới hoàn chỉnh.
* Xóa **toàn bộ** chunk cũ của `doc_id` này trong ChromaDB
  (`collection.delete(where={"source_document_id": doc_id})`), sau đó
  nạp lại toàn bộ chunk mới — không update từng chunk lẻ vì ranh giới
  chunk đã dịch chuyển so với lần ingest trước.
* Trả về:
  ```python
  {
      "status": "success" | "partial_failure",
      "retried_pages": [int, ...],
      "still_failed_pages": [int, ...],
      "total_chunks_reingested": int,
  }
  ```

---

### `backend/app.py` [MODIFY]

**Route `POST /api/admin/upload-data`:**

* Cập nhật response: trả về `ocr_stats` nguyên bản từ pipeline
  (`total_scan_pages`, `success`, `failed`, `skipped_circuit_breaker`,
  `failed_pages`, `circuit_breaker_triggered`).
* Với `status: "partial_failure"`: trả HTTP 207 (Multi-Status) kèm
  `failed_pages` và gợi ý gọi `/api/admin/retry-ocr` để xử lý tiếp.
* Giữ nguyên logic auth và lưu file.
* **Cân nhắc kiến trúc (ghi rõ để quyết định, không bắt buộc làm ngay
  trong lần sửa này):** route hiện tại xử lý đồng bộ — request chờ tới
  khi OCR xong toàn bộ file mới trả response. Với file nhiều trăm trang
  scan, tổng thời gian có thể lên tới hàng chục phút nếu gặp rate limit
  (worst case ~340s/trang thất bại × số trang lỗi), dễ vượt timeout của
  client/reverse proxy giữa chừng. Nếu gặp tình trạng timeout thực tế sau
  khi triển khai bản sửa này, nên chuyển route sang xử lý bất đồng bộ:
  trả ngay `doc_id` + `status: "processing"`, xử lý OCR trong background
  task/queue, admin poll tiến độ qua endpoint riêng.

**Route mới `POST /api/admin/retry-ocr`:**

* Body: `{ "doc_id": str, "pdf_filename": str }` (không cần gửi
  `failed_pages` — đọc từ cache như mô tả ở mục 5 phía trên).
* Gọi `retry_failed_pages()` từ `data_pipeline`.
* Trả về kết quả retry; nếu `still_failed_pages` không rỗng, giữ nguyên
  HTTP 207 để admin biết cần thử lại lần nữa hoặc xử lý thủ công.

---

## Verification Plan

**Manual Verification**

* Upload lại `merge_21.pdf` với code mới → kiểm tra response có
  `ocr_stats` đầy đủ, `status` đúng (`partial_failure` nếu > 15% lỗi)
* Kiểm tra log server: phải thấy xử lý theo batch 10 trang, có delay 5s
  giữa các batch, và backoff đúng thang đã định nghĩa khi giả lập lỗi 429
* Giả lập rate limit kéo dài (VD mock `ocr_page_with_gemini` luôn fail
  với lỗi 429) → xác nhận circuit breaker kích hoạt sau batch có ≥8/10
  trang lỗi, không tiếp tục chạy hết toàn bộ file
* Kiểm tra file cache `data/page_cache/{doc_id}_pages.json` được tạo
  đúng, có đủ trạng thái từng trang
* Gọi `/api/admin/retry-ocr` → xác nhận chỉ các trang lỗi được OCR lại
  (theo dõi số lần gọi Gemini Vision qua log, phải khớp đúng số trang
  lỗi, không OCR lại trang đã thành công)
* Sau retry, kiểm tra ChromaDB: toàn bộ chunk cũ của `doc_id` đã bị xóa
  và thay bằng bộ chunk mới, không còn chunk trùng lặp

**Data Cleanup (sau khi code mới đã verify xong)**

* Xóa các chunk cũ của `merge_21.pdf` trong ChromaDB
  (`source_document_id = "doc_merge_21_1786903216"`)
* Xóa cache cũ nếu có (`data/page_cache/doc_merge_21_1786903216_pages.json`)
* Chạy lại ingest cho `merge_21.pdf` từ đầu bằng code đã sửa
* Chạy `audit_ocr_gaps.py` để xác nhận tỷ lệ trang rỗng đã về mức chấp
  nhận được (< 15%, lý tưởng gần 0%) trước khi coi là xong
* Thử lại câu hỏi "Cách phòng trừ sâu đục thân, đục bắp ở ngô?" để xác
  nhận bot trả lời đúng với dữ liệu thật từ trang 31
