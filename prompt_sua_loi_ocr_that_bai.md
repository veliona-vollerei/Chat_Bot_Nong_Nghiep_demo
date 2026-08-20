Nhiệm vụ: Sửa backend/ingestion/data_pipeline.py để (1) tăng độ tin cậy OCR
khi xử lý file PDF nhiều trang scan, (2) không cho phép ingest "thành công"
âm thầm khi phần lớn nội dung bị mất do OCR lỗi.

BỐI CẢNH — LỖI ĐÃ XÁC NHẬN THỰC TẾ:
File merge_21.pdf (286 trang, gần như toàn bộ là ảnh scan) khi ingest qua
extract_text_from_pdf() đã bị mất 267/286 trang (93.4%) do Gemini Vision API
bị rate limit khi 5 luồng (ThreadPoolExecutor max_workers=5) gửi request dồn
dập. Hàm ocr_page_with_gemini() trả về "" khi thất bại sau 3 lần retry,
nhưng process_and_ingest_document() không kiểm tra tỷ lệ rỗng này — vẫn báo
"status: success" và nạp các trang rỗng vào ChromaDB như dữ liệu hợp lệ.
Hậu quả: chatbot trả lời "không có dữ liệu" cho các câu hỏi mà thực chất
tài liệu gốc CÓ đề cập, vì nội dung chưa từng thực sự được nạp vào.

YÊU CẦU SỬA:

1. Tăng độ bền của ocr_page_with_gemini():
   - Tăng số lần retry từ 3 lên 5-6 lần.
   - Tăng thời gian backoff cho lỗi rate limit (429/RESOURCE_EXHAUSTED) —
     dùng backoff dài hơn hẳn so với lỗi tạm thời khác (VD: 10s, 20s, 40s,
     60s thay vì 2s/4s/6s cố định cho mọi loại lỗi).
   - Phân biệt rõ lỗi rate limit (nên đợi lâu, retry nhiều) với lỗi khác
     (nên fail nhanh, không cần đợi lâu).

2. Giảm mức độ đồng thời khi OCR nhiều trang, tránh dồn dập gây rate limit:
   - Thêm cơ chế giới hạn tốc độ gọi API (rate limiter) — VD dùng
     asyncio.Semaphore hoặc thêm delay nhỏ giữa các lần submit vào
     ThreadPoolExecutor thay vì bắn hết cùng lúc.
   - Cân nhắc giảm max_workers xuống 2-3 nếu file có > 50 trang cần OCR,
     hoặc xử lý theo batch nhỏ (VD: 10 trang/đợt, nghỉ giữa các đợt) thay vì
     toàn bộ trang scan trong 1 lần submit.

3. Thêm bước validate SAU khi extract_text_from_pdf(), TRƯỚC khi báo
   "thành công" trong process_and_ingest_document():
   - Tính tỷ lệ trang rỗng (dựa theo marker "--- Trang N ---" theo sau
     không có nội dung, hoặc nội dung < một ngưỡng ký tự tối thiểu, VD 20).
   - Nếu tỷ lệ trang rỗng > 15% (ngưỡng có thể chỉnh): KHÔNG báo "success"
     bình thường — trả về status "partial_failure" kèm danh sách số trang
     bị lỗi, để admin biết cần xử lý lại thay vì tưởng đã xong.
   - Ghi log rõ ràng: "X/Y trang OCR thất bại: [danh sách số trang]".

4. Thêm hàm mới `retry_failed_pages(pdf_path, failed_page_numbers, doc_id)`:
   - Cho phép OCR lại CHỈ những trang đã thất bại trước đó (không phải OCR
     lại toàn bộ file từ đầu) — quan trọng với file nhiều trăm trang, tránh
     tốn thời gian/chi phí OCR lại cả file chỉ vì vài chục trang lỗi.
   - Sau khi OCR lại, cần cập nhật đúng chunk trong ChromaDB tương ứng với
     các trang đó — không tạo doc_id mới trùng lặp.

5. Endpoint/response cho admin (trong app.py, route upload hiện có):
   - Trả về rõ trong response: tổng số trang, số trang OCR thành công, số
     trang thất bại, danh sách số trang thất bại — để hiển thị lên UI cho
     admin biết ngay, không phải tự đi kiểm tra ChromaDB như vừa làm ở đây.

KHÔNG YÊU CẦU: không cần đổi cấu trúc chunk_text() hay cách lưu PostgreSQL/
ChromaDB hiện có, chỉ tập trung vào độ tin cậy của bước OCR + validation.

SAU KHI SỬA — VIỆC CẦN LÀM VỚI DỮ LIỆU CŨ:
- Xóa các chunk cũ của merge_21.pdf trong ChromaDB (source_document_id =
  "doc_merge_21_1786903216") vì chúng chứa dữ liệu rỗng đã lẫn vào cùng dữ
  liệu thật, không thể sửa từng phần do đã bị gộp chung trong chunk_text().
- Chạy lại toàn bộ pipeline ingest cho merge_21.pdf từ đầu bằng code đã sửa.
- Sau khi ingest lại, chạy script audit (đã cung cấp riêng) để xác nhận tỷ
  lệ trang rỗng giờ đã về mức chấp nhận được trước khi coi là xong.
