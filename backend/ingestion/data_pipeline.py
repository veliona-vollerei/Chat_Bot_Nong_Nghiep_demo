"""
Data Pipeline — Xử lý tài liệu thô nông nghiệp (PDF, DOCX, TXT, MD, JSON)
Sử dụng PyMuPDF để đọc PDF và Gemini Vision API để OCR trang scan.
"""
import os
import sys
import json
import logging
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from backend.config import BASE_DIR, GEMINI_ROUTER_MODEL
from backend.utils.gemini_client import call_with_rotation, AllKeysExhaustedError
from backend.layers.layer3_docs import store_chunk
from backend.db.postgres import get_cursor

logger = logging.getLogger(__name__)

# Đảm bảo thư mục raw_uploads tồn tại
RAW_UPLOADS_DIR = BASE_DIR / "data" / "raw_uploads"
RAW_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Thư mục lưu cache text từng trang
PAGE_CACHE_DIR = BASE_DIR / "data" / "page_cache"
PAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Ngưỡng trang rỗng: nội dung < MIN_PAGE_CHARS ký tự sau khi bỏ header
MIN_PAGE_CHARS = 20

# Ngưỡng tỷ lệ thất bại: > FAIL_RATIO → partial_failure
FAIL_RATIO_THRESHOLD = 0.15

# Circuit breaker: nếu >= CB_FAIL_IN_BATCH / CB_BATCH_SIZE trang trong 1 batch đều lỗi rate_limit
CB_BATCH_SIZE = 10
CB_FAIL_THRESHOLD = 8  # 8/10 trang lỗi → kích hoạt

# Backoff tables (giây) — mỗi phần tử tương ứng attempt 0..5
BACKOFF_RATE_LIMIT = [10, 20, 40, 60, 90, 120]
BACKOFF_SERVER_ERROR = [3, 6, 10, 10, 10, 10]

# Nhóm lỗi rate limit
RATE_LIMIT_KEYWORDS = ["429", "RESOURCE_EXHAUSTED"]

# Nhóm lỗi tạm thời (server error)
SERVER_ERROR_KEYWORDS = ["500", "502", "503", "504", "UNAVAILABLE"]


# ──────────────────────────────────────────────────────────────────────────────
# Helper: xác định loại lỗi từ message
# ──────────────────────────────────────────────────────────────────────────────

def _classify_error(err_str: str) -> str:
    """
    Phân loại lỗi từ Gemini API.
    Returns: 'rate_limit' | 'server_error' | 'other'
    """
    if any(k in err_str for k in RATE_LIMIT_KEYWORDS):
        return "rate_limit"
    if any(k in err_str for k in SERVER_ERROR_KEYWORDS):
        return "server_error"
    return "other"


# ──────────────────────────────────────────────────────────────────────────────
# 1. ocr_page_with_gemini — Tăng độ bền retry với backoff phân loại
# ──────────────────────────────────────────────────────────────────────────────

def ocr_page_with_gemini(page_img_bytes: bytes, page_num: int) -> Tuple[str, Optional[str]]:
    """
    Gọi Gemini Vision API để OCR 1 trang PDF dạng ảnh scan sang Markdown.
    Tự động xoay vòng Gemini API key khi gặp rate limit / quota exceeded.

    Returns:
        (extracted_text, error_type)
        - extracted_text: nội dung OCR được (rỗng nếu thất bại)
        - error_type: None nếu thành công, 'rate_limit' | 'server_error' | 'other' nếu thất bại
    """
    try:
        # pyrefly: ignore [missing-import]
        from google import genai
        # pyrefly: ignore [missing-import]
        from google.genai import types
        from backend.config import GEMINI_SYNTHESIS_MODEL

        prompt = (
            "Bạn là chuyên gia OCR. Hãy trích xuất toàn bộ văn bản, tiêu đề và bảng biểu "
            "trong trang tài liệu nông nghiệp này sang định dạng Markdown tiếng Việt chuẩn. "
            "Chỉ trả về nội dung Markdown bóc tách được, không kèm lời giải thích khác."
        )

        def _call_ocr(client: genai.Client) -> str:
            """Hàm OCR thực tế, nhận client từ key_manager."""
            res = client.models.generate_content(
                model=GEMINI_SYNTHESIS_MODEL,
                contents=[
                    types.Part.from_bytes(data=page_img_bytes, mime_type="image/png"),
                    prompt
                ]
            )
            return res.text.strip() if res.text else ""

        # call_with_rotation tự xoay key khi rate_limit / invalid_key,
        # tự retry với backoff khi server_error
        extracted = call_with_rotation(
            _call_ocr,
            server_error_retries=5,
            server_error_backoff=tuple(BACKOFF_SERVER_ERROR),
        )
        logger.info(f"✅ Gemini Vision OCR xong Trang {page_num} ({len(extracted)} chars)")
        return extracted, None  # Thành công

    except AllKeysExhaustedError as e:
        logger.error(f"❌ Trang {page_num}: Tất cả Gemini key đều exhausted — {e}")
        return "", "rate_limit"

    except Exception as e:
        err_str = str(e)
        error_type = _classify_error(err_str)
        logger.error(f"❌ Lỗi không phục hồi Trang {page_num} (error_type={error_type}): {e}")
        return "", error_type


# ──────────────────────────────────────────────────────────────────────────────
# Helper: đếm trang rỗng từ pages_text list
# ──────────────────────────────────────────────────────────────────────────────

def _count_empty_pages(pages_text: List[str]) -> Dict[str, Any]:
    """
    Tính số trang rỗng từ list pages_text.
    Trang rỗng: nội dung < MIN_PAGE_CHARS ký tự sau khi bỏ dòng header '--- Trang N ---'.
    """
    empty_pages = []
    for i, pt in enumerate(pages_text):
        if not pt:
            empty_pages.append(i + 1)
            continue
        # Bỏ dòng header "--- Trang N ---"
        lines = pt.strip().splitlines()
        content_lines = [l for l in lines if not l.strip().startswith("---")]
        content = "\n".join(content_lines).strip()
        if len(content) < MIN_PAGE_CHARS:
            empty_pages.append(i + 1)
    return {
        "empty_count": len(empty_pages),
        "empty_pages": empty_pages,
        "total_pages": len(pages_text),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Helper: load / save page cache
# ──────────────────────────────────────────────────────────────────────────────

def _cache_path(doc_id: str) -> Path:
    return PAGE_CACHE_DIR / f"{doc_id}_pages.json"


def _load_page_cache(doc_id: str) -> Dict[str, Any]:
    p = _cache_path(doc_id)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_page_cache(doc_id: str, cache: Dict[str, Any]) -> None:
    p = _cache_path(doc_id)
    try:
        p.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"⚠️ Không thể lưu page cache cho {doc_id}: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# 2. extract_text_from_pdf — Batch OCR với circuit breaker + page cache
# ──────────────────────────────────────────────────────────────────────────────

def extract_text_from_pdf(pdf_path: Path, doc_id: str = "") -> Tuple[str, Dict[str, Any]]:
    """
    Rút trích văn bản từ file PDF:
    - Trang có chữ điện tử (>= 50 ký tự): lấy trực tiếp từ PyMuPDF (fitz).
    - Trang là ảnh scan (< 50 ký tự): OCR bằng Gemini Vision, xử lý theo batch
      10 trang/đợt với max_workers=2 để tránh rate limit.

    Returns:
        (full_text, ocr_stats)
        ocr_stats = {
            "total_scan_pages": int,
            "success": int,
            "failed": int,
            "skipped_circuit_breaker": int,
            "failed_pages": [int, ...],
            "circuit_breaker_triggered": bool,
        }
    """
    # pyrefly: ignore [missing-import]
    import fitz  # PyMuPDF
    from concurrent.futures import ThreadPoolExecutor, as_completed

    ocr_stats = {
        "total_scan_pages": 0,
        "success": 0,
        "failed": 0,
        "skipped_circuit_breaker": 0,
        "failed_pages": [],
        "circuit_breaker_triggered": False,
    }

    try:
        doc = fitz.open(str(pdf_path))
        num_pages = len(doc)
        logger.info(f"📄 Bắt đầu xử lý {pdf_path.name} ({num_pages} trang)...")

        pages_text = [""] * num_pages
        scan_pages_to_process: List[Tuple[int, bytes]] = []

        for i, page in enumerate(doc):
            text = page.get_text() or ""
            if len(text.strip()) >= 50:
                pages_text[i] = f"\n--- Trang {i+1} ---\n" + text.strip()
            else:
                pix = page.get_pixmap(dpi=150)
                img_bytes = pix.tobytes("png")
                scan_pages_to_process.append((i, img_bytes))

        ocr_stats["total_scan_pages"] = len(scan_pages_to_process)

        if not scan_pages_to_process:
            full_text = "\n\n".join([p for p in pages_text if p.strip()])
            logger.info(f"🎉 Không có trang scan — hoàn thành {pdf_path.name} ({len(full_text)} chars)")
            return full_text, ocr_stats

        logger.info(
            f"🔍 Phát hiện {len(scan_pages_to_process)}/{num_pages} trang scan. "
            f"Bắt đầu Gemini Vision OCR (max_workers=2, batch={CB_BATCH_SIZE} trang)..."
        )

        # Load cache nếu có (tránh OCR lại trang đã xong)
        page_cache = _load_page_cache(doc_id) if doc_id else {}

        circuit_breaker_triggered = False

        # Chia thành batches
        batches = [
            scan_pages_to_process[i:i + CB_BATCH_SIZE]
            for i in range(0, len(scan_pages_to_process), CB_BATCH_SIZE)
        ]

        for batch_idx, batch in enumerate(batches):
            if circuit_breaker_triggered:
                # Đánh dấu tất cả trang còn lại là skipped
                for page_idx, _ in batch:
                    page_num = page_idx + 1
                    pages_text[page_idx] = f"\n--- Trang {page_num} ---\n"
                    ocr_stats["skipped_circuit_breaker"] += 1
                    if page_num not in ocr_stats["failed_pages"]:
                        ocr_stats["failed_pages"].append(page_num)
                    if doc_id:
                        page_cache[str(page_num)] = {
                            "text": "",
                            "status": "skipped_circuit_breaker"
                        }
                continue

            logger.info(f"📦 Batch {batch_idx+1}/{len(batches)} — {len(batch)} trang scan...")

            batch_rate_limit_failures = 0

            with ThreadPoolExecutor(max_workers=2) as executor:
                future_to_index = {}
                for page_idx, img_bytes in batch:
                    page_num = page_idx + 1
                    # Kiểm tra cache: nếu đã thành công thì bỏ qua OCR
                    cached = page_cache.get(str(page_num))
                    if cached and cached.get("status") == "ok":
                        pages_text[page_idx] = f"\n--- Trang {page_num} ---\n" + cached["text"]
                        ocr_stats["success"] += 1
                        logger.info(f"🗂️ Trang {page_num}: dùng từ cache (bỏ qua OCR)")
                        continue
                    future = executor.submit(ocr_page_with_gemini, img_bytes, page_num)
                    future_to_index[future] = page_idx

                for future in as_completed(future_to_index):
                    page_idx = future_to_index[future]
                    page_num = page_idx + 1
                    try:
                        extracted, error_type = future.result()
                        if extracted:
                            pages_text[page_idx] = f"\n--- Trang {page_num} ---\n" + extracted
                            ocr_stats["success"] += 1
                            if doc_id:
                                page_cache[str(page_num)] = {
                                    "text": extracted,
                                    "status": "ok"
                                }
                        else:
                            pages_text[page_idx] = f"\n--- Trang {page_num} ---\n"
                            ocr_stats["failed"] += 1
                            if page_num not in ocr_stats["failed_pages"]:
                                ocr_stats["failed_pages"].append(page_num)
                            if error_type == "rate_limit":
                                batch_rate_limit_failures += 1
                            if doc_id:
                                page_cache[str(page_num)] = {
                                    "text": "",
                                    "status": "failed",
                                    "error_type": error_type or "unknown"
                                }
                    except Exception as e:
                        logger.error(f"Lỗi future trang {page_num}: {e}")
                        pages_text[page_idx] = f"\n--- Trang {page_num} ---\n"
                        ocr_stats["failed"] += 1
                        if page_num not in ocr_stats["failed_pages"]:
                            ocr_stats["failed_pages"].append(page_num)
                        if doc_id:
                            page_cache[str(page_num)] = {
                                "text": "",
                                "status": "failed",
                                "error_type": "exception"
                            }

            # Lưu cache sau mỗi batch
            if doc_id:
                _save_page_cache(doc_id, page_cache)

            # Kiểm tra circuit breaker
            if batch_rate_limit_failures >= CB_FAIL_THRESHOLD:
                logger.error(
                    f"🚨 Circuit breaker kích hoạt! Batch {batch_idx+1}: "
                    f"{batch_rate_limit_failures}/{len(batch)} trang thất bại vì rate_limit. "
                    f"Dừng xử lý các batch còn lại."
                )
                circuit_breaker_triggered = True
                ocr_stats["circuit_breaker_triggered"] = True

            # Nghỉ 5s giữa các batch (trừ batch cuối)
            if batch_idx < len(batches) - 1 and not circuit_breaker_triggered:
                logger.info(f"⏸️ Nghỉ 5s giữa các batch để tránh rate limit...")
                time.sleep(5)

        ocr_stats["failed_pages"].sort()
        full_text = "\n\n".join([p for p in pages_text if p.strip()])
        logger.info(
            f"🎉 Hoàn thành bóc tách {pdf_path.name} — "
            f"Tổng ký tự: {len(full_text)} | "
            f"OCR: {ocr_stats['success']} ok, {ocr_stats['failed']} failed, "
            f"{ocr_stats['skipped_circuit_breaker']} skipped"
        )
        return full_text, ocr_stats

    except Exception as e:
        logger.error(f"Lỗi extract_text_from_pdf: {e}")
        return "", ocr_stats


# ──────────────────────────────────────────────────────────────────────────────
# extract_text_from_docx
# ──────────────────────────────────────────────────────────────────────────────

def extract_text_from_docx(docx_path: Path) -> str:
    """Rút trích văn bản từ file Word (.docx)."""
    try:
        # pyrefly: ignore [missing-import]
        import docx
        doc = docx.Document(str(docx_path))
        full_text = []
        for para in doc.paragraphs:
            if para.text.strip():
                full_text.append(para.text.strip())
        return "\n\n".join(full_text)
    except Exception as e:
        logger.error(f"Lỗi đọc file docx {docx_path.name}: {e}")
        return ""


# ──────────────────────────────────────────────────────────────────────────────
# chunk_text — giữ nguyên, không thay đổi
# ──────────────────────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = 800, overlap: int = 150) -> List[str]:
    """Chia văn bản thành các đoạn (chunks) chuẩn hoá."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    current_chunk = ""

    for p in paragraphs:
        if len(current_chunk) + len(p) <= chunk_size:
            current_chunk += ("\n\n" + p) if current_chunk else p
        else:
            if current_chunk:
                chunks.append(current_chunk)
            # Nếu paragraph dài hơn chunk_size, cắt theo chiều dài
            if len(p) > chunk_size:
                start = 0
                while start < len(p):
                    chunks.append(p[start:start+chunk_size])
                    start += (chunk_size - overlap)
                current_chunk = ""
            else:
                current_chunk = p

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


# ──────────────────────────────────────────────────────────────────────────────
# 4. process_and_ingest_document — Validate + partial_failure
# ──────────────────────────────────────────────────────────────────────────────

def process_and_ingest_document(file_path: str, custom_title: str = None) -> Dict[str, Any]:
    """
    Quy trình xử lý hoàn chỉnh 1 file tài liệu:
    1. Đọc văn bản thô
    2. Chia chunks
    3. Validate tỷ lệ trang rỗng (chỉ áp dụng cho PDF scan)
    4. Tạo metadata & lưu vào ChromaDB + PostgreSQL
    """
    fp = Path(file_path)
    if not fp.exists():
        raise FileNotFoundError(f"Không tìm thấy file: {file_path}")

    doc_id = f"doc_{fp.stem}_{int(os.path.getmtime(fp))}"
    title = custom_title or fp.name

    ext = fp.suffix.lower()
    raw_text = ""
    chunks_list = []
    ocr_stats = None

    if ext == ".pdf":
        raw_text, ocr_stats = extract_text_from_pdf(fp, doc_id=doc_id)
    elif ext in [".docx", ".doc"]:
        raw_text = extract_text_from_docx(fp)
    elif ext in [".txt", ".md"]:
        raw_text = fp.read_text(encoding="utf-8", errors="ignore")
    elif ext == ".json":
        data = json.loads(fp.read_text(encoding="utf-8", errors="ignore"))
        if isinstance(data, list):
            chunks_list = [str(item.get("text", item)) if isinstance(item, dict) else str(item) for item in data]
        else:
            raw_text = str(data)
    else:
        raise ValueError(f"Định dạng file không được hỗ trợ: {ext}")

    # Validate tỷ lệ OCR thất bại (chỉ với PDF có scan pages)
    if ocr_stats and ocr_stats["total_scan_pages"] > 0:
        total_failed = ocr_stats["failed"] + ocr_stats["skipped_circuit_breaker"]
        fail_ratio = total_failed / ocr_stats["total_scan_pages"]

        if total_failed > 0:
            logger.warning(
                f"⚠️ {total_failed}/{ocr_stats['total_scan_pages']} trang OCR thất bại: "
                f"{ocr_stats['failed_pages']}"
            )

        if fail_ratio > FAIL_RATIO_THRESHOLD:
            logger.error(
                f"🚫 Tỷ lệ OCR thất bại quá cao ({fail_ratio:.1%} > {FAIL_RATIO_THRESHOLD:.0%}). "
                f"Từ chối nạp dữ liệu để tránh lưu nội dung rỗng."
            )
            return {
                "status": "partial_failure",
                "doc_id": doc_id,
                "title": title,
                "message": (
                    f"OCR thất bại {total_failed}/{ocr_stats['total_scan_pages']} trang "
                    f"({fail_ratio:.1%} > ngưỡng {FAIL_RATIO_THRESHOLD:.0%}). "
                    f"Dữ liệu KHÔNG được nạp vào hệ thống. "
                    f"Vui lòng gọi /api/admin/retry-ocr để xử lý lại."
                ),
                "ocr_stats": ocr_stats,
                "hint": "Gọi POST /api/admin/retry-ocr với doc_id và pdf_filename để OCR lại các trang lỗi.",
            }

    if not chunks_list and raw_text:
        chunks_list = chunk_text(raw_text)

    if not chunks_list:
        return {"status": "error", "message": "Không trích xuất được văn bản từ tài liệu."}

    # Lưu document vào PostgreSQL
    try:
        with get_cursor() as cur:
            cur.execute("""
                INSERT INTO documents (document_id, title, file_path)
                VALUES (%s, %s, %s)
                ON CONFLICT (document_id) DO UPDATE SET title = EXCLUDED.title
            """, (doc_id, title, str(fp)))
    except Exception as e:
        logger.error(f"Lỗi lưu thông tin document vào PG: {e}")

    # Nạp từng chunk vào ChromaDB
    stored_count = 0
    for i, c_text in enumerate(chunks_list):
        if not c_text.strip():
            continue

        chunk_id = f"{doc_id}_chunk_{i+1}"
        chunk_obj = {
            "chunk_id": chunk_id,
            "chunk_text": c_text,
            "crop": "nông nghiệp tổng quát",
            "topic": f"Tài liệu {title}",
            "source": title,
            "source_document_id": doc_id,
            "confidence": "chính thống",
            "year_published": 2026,
        }

        if store_chunk(chunk_obj):
            stored_count += 1

    logger.info(f"🎉 Đã xử lý & nạp thành công {stored_count}/{len(chunks_list)} chunks từ {title}")

    result = {
        "status": "success",
        "doc_id": doc_id,
        "title": title,
        "total_chunks": len(chunks_list),
        "stored_chunks": stored_count,
    }
    if ocr_stats:
        result["ocr_stats"] = ocr_stats

    return result


# ──────────────────────────────────────────────────────────────────────────────
# 5. retry_failed_pages — OCR lại chỉ trang lỗi, re-chunk toàn bộ tài liệu
# ──────────────────────────────────────────────────────────────────────────────

def retry_failed_pages(pdf_path: str, doc_id: str) -> Dict[str, Any]:
    """
    OCR lại chỉ các trang có status != 'ok' trong cache, sau đó:
    - Ghép lại toàn bộ text theo đúng thứ tự trang (từ cache)
    - Re-chunk toàn bộ tài liệu
    - Xóa toàn bộ chunk cũ của doc_id trong ChromaDB
    - Nạp lại toàn bộ chunk mới

    Returns:
        {
            "status": "success" | "partial_failure",
            "retried_pages": [int, ...],
            "still_failed_pages": [int, ...],
            "total_chunks_reingested": int,
            "ocr_stats": dict,
        }
    """
    # pyrefly: ignore [missing-import]
    import fitz
    from concurrent.futures import ThreadPoolExecutor, as_completed

    fp = Path(pdf_path)
    if not fp.exists():
        raise FileNotFoundError(f"Không tìm thấy file PDF: {pdf_path}")

    page_cache = _load_page_cache(doc_id)
    if not page_cache:
        return {
            "status": "error",
            "message": f"Không tìm thấy cache cho doc_id={doc_id}. "
                       f"Vui lòng ingest lại từ đầu.",
        }

    # Xác định trang cần retry
    pages_to_retry = [
        int(pn) for pn, info in page_cache.items()
        if info.get("status") != "ok"
    ]

    if not pages_to_retry:
        return {
            "status": "success",
            "retried_pages": [],
            "still_failed_pages": [],
            "total_chunks_reingested": 0,
            "message": "Không có trang nào cần retry.",
        }

    pages_to_retry.sort()
    logger.info(f"🔄 Bắt đầu retry {len(pages_to_retry)} trang: {pages_to_retry}")

    # Mở PDF và lấy ảnh các trang cần retry
    try:
        doc = fitz.open(str(fp))
    except Exception as e:
        return {"status": "error", "message": f"Không mở được PDF: {e}"}

    retry_images: List[Tuple[int, bytes]] = []
    for page_num in pages_to_retry:
        try:
            page = doc[page_num - 1]
            pix = page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes("png")
            retry_images.append((page_num, img_bytes))
        except Exception as e:
            logger.error(f"Lỗi lấy ảnh trang {page_num}: {e}")

    # OCR lại theo batch nhỏ (5 trang/đợt)
    RETRY_BATCH_SIZE = 5
    retried_pages = []
    still_failed_pages = []
    retry_ocr_stats = {"success": 0, "failed": 0, "rate_limit_failures": 0}

    retry_batches = [
        retry_images[i:i + RETRY_BATCH_SIZE]
        for i in range(0, len(retry_images), RETRY_BATCH_SIZE)
    ]

    for batch_idx, batch in enumerate(retry_batches):
        logger.info(f"🔄 Retry batch {batch_idx+1}/{len(retry_batches)} ({len(batch)} trang)...")

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_to_page = {
                executor.submit(ocr_page_with_gemini, img_bytes, page_num): page_num
                for page_num, img_bytes in batch
            }
            for future in as_completed(future_to_page):
                page_num = future_to_page[future]
                try:
                    extracted, error_type = future.result()
                    if extracted:
                        page_cache[str(page_num)] = {"text": extracted, "status": "ok"}
                        retried_pages.append(page_num)
                        retry_ocr_stats["success"] += 1
                        logger.info(f"✅ Retry thành công Trang {page_num} ({len(extracted)} chars)")
                    else:
                        page_cache[str(page_num)] = {
                            "text": "",
                            "status": "failed",
                            "error_type": error_type or "unknown"
                        }
                        still_failed_pages.append(page_num)
                        retry_ocr_stats["failed"] += 1
                        if error_type == "rate_limit":
                            retry_ocr_stats["rate_limit_failures"] += 1
                        logger.warning(f"❌ Retry thất bại Trang {page_num} (error_type={error_type})")
                except Exception as e:
                    logger.error(f"Lỗi future retry trang {page_num}: {e}")
                    still_failed_pages.append(page_num)
                    retry_ocr_stats["failed"] += 1

        # Lưu cache sau mỗi batch retry
        _save_page_cache(doc_id, page_cache)

        # Nghỉ giữa retry batches
        if batch_idx < len(retry_batches) - 1:
            logger.info(f"⏸️ Nghỉ 5s giữa các retry batch...")
            time.sleep(5)

    # Ghép lại toàn bộ text theo thứ tự trang từ cache
    try:
        total_pages = len(doc)
    except Exception:
        total_pages = max(int(k) for k in page_cache.keys())

    all_pages_text = []
    for page_num in range(1, total_pages + 1):
        cached = page_cache.get(str(page_num))
        if cached and cached.get("status") == "ok" and cached.get("text"):
            all_pages_text.append(f"\n--- Trang {page_num} ---\n{cached['text']}")
        else:
            # Thử lấy text điện tử từ PDF (trang không phải scan)
            try:
                page = doc[page_num - 1]
                text = page.get_text() or ""
                if len(text.strip()) >= 50:
                    all_pages_text.append(f"\n--- Trang {page_num} ---\n{text.strip()}")
                # else: trang scan thất bại — bỏ qua (không thêm header rỗng vào full_text)
            except Exception:
                pass

    full_text = "\n\n".join([p for p in all_pages_text if p.strip()])

    # Re-chunk toàn bộ tài liệu
    chunks_list = chunk_text(full_text)

    if not chunks_list:
        return {
            "status": "error",
            "message": "Sau retry vẫn không có nội dung để nạp vào hệ thống.",
            "retried_pages": retried_pages,
            "still_failed_pages": still_failed_pages,
        }

    # Xóa toàn bộ chunk cũ của doc_id trong ChromaDB
    try:
        from backend.db.chroma_db import get_collection
        collection = get_collection()
        collection.delete(where={"source_document_id": doc_id})
        logger.info(f"🗑️ Đã xóa toàn bộ chunk cũ của {doc_id} trong ChromaDB")
    except Exception as e:
        logger.error(f"Lỗi xóa chunk cũ trong ChromaDB: {e}")

    # Nạp lại toàn bộ chunk mới
    title_for_chunk = fp.name
    stored_count = 0
    for i, c_text in enumerate(chunks_list):
        if not c_text.strip():
            continue
        chunk_id = f"{doc_id}_chunk_{i+1}"
        chunk_obj = {
            "chunk_id": chunk_id,
            "chunk_text": c_text,
            "crop": "nông nghiệp tổng quát",
            "topic": f"Tài liệu {title_for_chunk}",
            "source": title_for_chunk,
            "source_document_id": doc_id,
            "confidence": "chính thống",
            "year_published": 2026,
        }
        if store_chunk(chunk_obj):
            stored_count += 1

    logger.info(
        f"🎉 Retry hoàn tất — {len(retried_pages)} trang thành công, "
        f"{len(still_failed_pages)} trang vẫn lỗi. "
        f"Đã nạp lại {stored_count}/{len(chunks_list)} chunks."
    )

    still_failed_pages.sort()
    fail_count = len(still_failed_pages)
    total_scan = len(pages_to_retry)
    status = "success" if fail_count == 0 else (
        "partial_failure" if fail_count / total_scan > FAIL_RATIO_THRESHOLD else "success"
    )

    return {
        "status": status,
        "retried_pages": sorted(retried_pages),
        "still_failed_pages": still_failed_pages,
        "total_chunks_reingested": stored_count,
        "ocr_stats": retry_ocr_stats,
    }
