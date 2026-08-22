# Bỏ xử lý OCR ảnh scan — chỉ lấy trang có chữ điện tử sẵn có

## Mô tả

Loại bỏ hoàn toàn việc gọi Gemini Vision API để OCR trang scan trong PDF —
lý do: tốn quá nhiều lệnh gọi API, dễ cạn hạn ngạch (đã xảy ra thật với
`merge_21.pdf`). Từ nay, trang không có chữ điện tử (ảnh scan thuần) sẽ
được **bỏ qua có ghi nhận**, không cố OCR nữa.

**Không đụng đến `backend/utils/gemini_client.py`** — module này vẫn được
dùng cho router (`query_router.py` dòng 115, 188) để gọi Gemini cho việc
phân loại câu hỏi và tổng hợp câu trả lời, không liên quan đến OCR ảnh.

---

## Proposed Changes

### `backend/ingestion/data_pipeline.py` [MODIFY]

**1. Đơn giản hoá `extract_text_from_pdf()` — bỏ toàn bộ nhánh OCR**

* Xoá: gọi `ocr_page_with_gemini()`, logic batch OCR (`CB_BATCH_SIZE`),
  circuit breaker rate-limit, `ThreadPoolExecutor` cho OCR, load/save
  page cache (không còn cần cache vì không còn gì để retry).
* Giữ nguyên: đọc chữ điện tử qua `page.get_text()` cho trang ≥ 50 ký tự.
* Với trang < 50 ký tự (trước đây coi là "cần OCR"): **bỏ qua**, không
  tạo ảnh PNG, không gọi Gemini gì cả. Ghi nhận số trang bị bỏ qua.
* Đổi return signature — vẫn giữ `Tuple[str, Dict]` để không phải sửa
  chỗ gọi hàm, nhưng đổi nội dung `stats`:

```python
def extract_text_from_pdf(pdf_path: Path, doc_id: str = "") -> Tuple[str, Dict[str, Any]]:
    """
    Rút trích văn bản từ file PDF — CHỈ lấy trang có chữ điện tử sẵn có
    (>= 50 ký tự qua PyMuPDF). Trang scan/ảnh thuần túy sẽ bị bỏ qua,
    không OCR (đã tắt theo yêu cầu — tốn API quá nhiều).

    Returns:
        (full_text, extract_stats)
        extract_stats = {
            "total_pages": int,
            "pages_with_text": int,
            "pages_skipped_no_text": int,
            "skipped_page_numbers": [int, ...],
        }
    """
    import fitz
    stats = {
        "total_pages": 0, "pages_with_text": 0,
        "pages_skipped_no_text": 0, "skipped_page_numbers": [],
    }
    try:
        doc = fitz.open(str(pdf_path))
        stats["total_pages"] = len(doc)
        pages_text = []
        for i, page in enumerate(doc):
            text = page.get_text() or ""
            if len(text.strip()) >= 50:
                pages_text.append(f"\n--- Trang {i+1} ---\n" + text.strip())
                stats["pages_with_text"] += 1
            else:
                stats["pages_skipped_no_text"] += 1
                stats["skipped_page_numbers"].append(i + 1)

        full_text = "\n\n".join(pages_text)
        logger.info(
            f"📄 {pdf_path.name}: {stats['pages_with_text']}/{stats['total_pages']} "
            f"trang có chữ điện tử, {stats['pages_skipped_no_text']} trang bị bỏ qua "
            f"(ảnh scan, không OCR)."
        )
        return full_text, stats
    except Exception as e:
        logger.error(f"Lỗi extract_text_from_pdf: {e}")
        return "", stats
```

**2. Xoá các hàm/hằng số không còn dùng:**

* `ocr_page_with_gemini()` — xoá hẳn (không còn nơi nào gọi).
* `_classify_error()`, `_count_empty_pages()`, `_cache_path()`,
  `_load_page_cache()`, `_save_page_cache()` — xoá nếu không còn dùng ở
  đâu khác trong file (kiểm tra lại trước khi xoá).
* Hằng số: `MIN_PAGE_CHARS`, `FAIL_RATIO_THRESHOLD`, `CB_BATCH_SIZE`,
  `CB_FAIL_THRESHOLD`, `BACKOFF_RATE_LIMIT`, `BACKOFF_SERVER_ERROR`,
  `RATE_LIMIT_KEYWORDS`, `SERVER_ERROR_KEYWORDS` — xoá.
* `PAGE_CACHE_DIR` — xoá (không còn cache để lưu).

**3. Xoá hẳn `retry_failed_pages()`** — hàm này chỉ có ý nghĩa khi có
OCR để retry; không còn OCR thì không còn gì để retry lại.

**4. Sửa `process_and_ingest_document()`:**

* Đổi tên biến nhận về từ `extract_text_from_pdf()` cho khớp:
  `raw_text, extract_stats = extract_text_from_pdf(fp, doc_id=doc_id)`.
* **Bỏ hẳn khối validate "tỷ lệ OCR thất bại > 15% → partial_failure"**
  — không còn OCR nên không còn khái niệm "thất bại". Thay bằng cảnh báo
  thông tin (không chặn nạp dữ liệu):

```python
if extract_stats and extract_stats["pages_skipped_no_text"] > 0:
    skip_ratio = extract_stats["pages_skipped_no_text"] / extract_stats["total_pages"]
    logger.warning(
        f"⚠️ {extract_stats['pages_skipped_no_text']}/{extract_stats['total_pages']} "
        f"trang ({skip_ratio:.1%}) là ảnh scan, KHÔNG được nạp vào hệ thống "
        f"(đã tắt OCR). Trang: {extract_stats['skipped_page_numbers']}"
    )
```

* Vẫn tiếp tục nạp bình thường với phần chữ điện tử lấy được (dù ít),
  không từ chối nạp — khác với hành vi cũ (không nạp nếu lỗi > 15%), vì
  giờ đây "bỏ qua trang scan" là hành vi **có chủ đích**, không phải lỗi.
* Đưa `extract_stats` vào `result` trả về (đổi key `ocr_stats` thành
  `extract_stats` cho đúng bản chất, hoặc giữ tên cũ nếu muốn đỡ phải sửa
  chỗ khác gọi tới — tự quyết theo mức độ ngại sửa các chỗ liên quan).

**5. Xoá import không dùng:** `time` có thể vẫn cần cho phần khác trong
file (kiểm tra lại trước khi xoá); `call_with_rotation`,
`AllKeysExhaustedError` từ `backend.utils.gemini_client` — xoá khỏi
import của file này nếu không còn chỗ nào dùng trong `data_pipeline.py`.

---

### `backend/app.py` [MODIFY]

* **Xoá route `POST /api/admin/retry-ocr`** (nếu đã được thêm từ lần sửa
  trước) — không còn `retry_failed_pages()` để gọi.
* Route `POST /api/admin/upload-data`: cập nhật response để phản ánh
  đúng `extract_stats` mới thay vì `ocr_stats` — báo rõ cho admin biết
  bao nhiêu % nội dung file bị bỏ qua do là ảnh scan, để họ tự quyết
  định có cần xử lý riêng file đó bằng cách khác không (VD: chuyển đổi
  thủ công, hoặc dùng công cụ OCR khác ngoài hệ thống).

---

## Việc cần làm với dữ liệu cũ

* `merge_21.pdf` hiện tại (nếu đã ingest lần nào thành công một phần
  trước đây) nên được **ingest lại bằng code mới** để đảm bảo dữ liệu
  trong ChromaDB nhất quán với hành vi mới (chỉ chứa phần chữ điện tử
  thật, không lẫn phần OCR cũ nếu có).
* Vì tài liệu này gần như toàn ảnh scan, sau khi ingest lại, lượng nội
  dung thu được sẽ **rất ít** (chỉ vài trang có chữ điện tử, chủ yếu
  bìa/mục lục) — đây là kết quả **đúng như dự kiến**, không phải lỗi.

---

## Verification Plan

* Upload `tai-lieu-5-2024-tap-huan-kn-lua-caphe.pdf` (chỉ 1.6% là scan)
  → xác nhận vẫn nạp được gần như đầy đủ nội dung, không có lệnh gọi
  Gemini Vision nào trong log (kiểm tra không còn dòng log OCR)
* Upload `merge_21.pdf` → xác nhận:
  * Không có bất kỳ lệnh gọi Gemini Vision nào trong log
  * Response trả về đúng `extract_stats` với số trang bị bỏ qua ~93%
  * Dữ liệu vẫn được nạp (không bị chặn như hành vi `partial_failure`
    cũ), dù ít nội dung
* Kiểm tra `/api/admin/retry-ocr` đã bị xoá — gọi route này phải trả về
  404, không còn tồn tại
* Xác nhận `backend/utils/gemini_client.py` không bị đụng tới, router
  (`query_router.py`) vẫn hoạt động bình thường (test 1 câu hỏi bất kỳ,
  xác nhận vẫn trả lời được)
