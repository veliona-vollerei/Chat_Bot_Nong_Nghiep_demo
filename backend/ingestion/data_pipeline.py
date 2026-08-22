"""
Data Pipeline — Xử lý tài liệu thô nông nghiệp (PDF, DOCX, TXT, MD, JSON)
Sử dụng PyMuPDF để đọc PDF. Chỉ lấy trang có chữ điện tử sẵn có (>= 50 ký tự).
Trang scan/ảnh thuần túy sẽ bị bỏ qua, không OCR (đã tắt — tốn API quá nhiều).
"""
import os
import sys
import json
import hashlib
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from backend.config import BASE_DIR
from backend.layers.layer3_docs import store_chunk
from backend.db.postgres import (
    get_cursor,
    query_document_by_hash,
    query_document_by_filename,
    get_all_known_filenames,
    update_document_status,
)

logger = logging.getLogger(__name__)

# Đảm bảo các thư mục cần thiết tồn tại
RAW_UPLOADS_DIR = BASE_DIR / "data" / "raw_uploads"
RAW_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Thư mục lưu file tạm đang chờ admin xác nhận (case 3, 4)
PENDING_UPLOADS_DIR = BASE_DIR / "data" / "pending_uploads"
PENDING_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


# ──────────────────────────────────────────────────────────────────────────────
# 0. Nhận diện tài liệu theo content hash (SHA-256)
# ──────────────────────────────────────────────────────────────────────────────

def compute_content_hash(file_bytes: bytes) -> str:
    """Tính SHA-256 hash của nội dung file (hex string, 64 ký tự)."""
    return hashlib.sha256(file_bytes).hexdigest()


def check_upload_status(file_bytes: bytes, filename: str) -> dict:
    """
    Kiểm tra trạng thái upload, phân loại vào 1 trong 5 case:

    Returns dict với key 'action':
      - 'process_new'              : Case 1 — tài liệu mới hoàn toàn
      - 'auto_continue'            : Case 2 — nội dung giống, dở dang → tiếp tục
      - 'confirm_duplicate_content': Case 3 — nội dung giống, tên hoàn toàn mới → hỏi admin
      - 'confirm_content_changed'  : Case 4 — cùng tên, nội dung khác → hỏi admin
      - 'already_complete'         : Case 5 — nội dung giống, tên đã alias → bỏ qua
    """
    content_hash = compute_content_hash(file_bytes)
    by_hash = query_document_by_hash(content_hash)
    by_filename = query_document_by_filename(filename)

    if by_hash and by_hash["processing_status"] != "complete":
        # Case 2: đang xử lý dở dang (processing/partial_failure) — tiếp tục
        return {"action": "auto_continue", "doc_id": by_hash["doc_id"]}

    if by_hash and by_hash["processing_status"] == "complete":
        known_filenames = get_all_known_filenames(by_hash["doc_id"])
        if filename in known_filenames:
            # Case 5: tên này đã từng được xác nhận (alias hoặc gốc) — không hỏi lại
            return {"action": "already_complete", "doc_id": by_hash["doc_id"]}
        else:
            # Case 3: nội dung trùng, tên hoàn toàn mới — cần hỏi admin
            return {
                "action": "confirm_duplicate_content",
                "doc_id": by_hash["doc_id"],
                "existing_filenames": known_filenames,
                "existing_uploaded_at": str(by_hash.get("updated_at", "")),
            }

    if by_filename and by_filename["content_hash"] != content_hash:
        # Case 4: cùng tên, nội dung đã thay đổi
        return {
            "action": "confirm_content_changed",
            "old_doc_id": by_filename["doc_id"],
            "old_uploaded_at": str(by_filename.get("updated_at", "")),
        }

    # Case 1: hoàn toàn mới
    return {"action": "process_new", "content_hash": content_hash}


# ──────────────────────────────────────────────────────────────────────────────
# 1. extract_text_from_pdf — CHỈ lấy trang có chữ điện tử, bỏ qua trang scan
# ──────────────────────────────────────────────────────────────────────────────

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
    # pyrefly: ignore [missing-import]
    import fitz  # PyMuPDF
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
# 2. process_and_ingest_document — Xử lý và nạp tài liệu vào ChromaDB
# ──────────────────────────────────────────────────────────────────────────────

def process_and_ingest_document(
    file_path: str,
    custom_title: str = None,
    content_hash: str = None,
    original_filename: str = None,
) -> Dict[str, Any]:
    """
    Quy trình xử lý hoàn chỉnh 1 file tài liệu:
    1. Đọc văn bản thô (chỉ chữ điện tử với PDF, không OCR)
    2. Chia chunks
    3. Tạo metadata & lưu vào ChromaDB + PostgreSQL

    Tham số bổ sung:
      content_hash      : SHA-256 của file bytes (nếu đã tính sẵn ở upstream)
      original_filename : Tên file gốc do admin upload (nếu khác tên trên disk)
    """
    fp = Path(file_path)
    if not fp.exists():
        raise FileNotFoundError(f"Không tìm thấy file: {file_path}")

    # Xác định original_filename và tính content_hash nếu chưa có
    _original_filename = original_filename or fp.name
    if not content_hash:
        content_hash = compute_content_hash(fp.read_bytes())

    # doc_id dựa trên content_hash (16 ký tự đầu) — ổn định, không phụ thuộc timestamp
    doc_id = f"doc_{content_hash[:16]}"
    title = custom_title or _original_filename

    ext = fp.suffix.lower()
    raw_text = ""
    chunks_list = []
    extract_stats = None

    if ext == ".pdf":
        raw_text, extract_stats = extract_text_from_pdf(fp, doc_id=doc_id)
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

    # Cảnh báo thông tin nếu có trang scan bị bỏ qua (không chặn nạp dữ liệu)
    if extract_stats and extract_stats["pages_skipped_no_text"] > 0:
        skip_ratio = extract_stats["pages_skipped_no_text"] / extract_stats["total_pages"]
        logger.warning(
            f"⚠️ {extract_stats['pages_skipped_no_text']}/{extract_stats['total_pages']} "
            f"trang ({skip_ratio:.1%}) là ảnh scan, KHÔNG được nạp vào hệ thống "
            f"(đã tắt OCR). Trang: {extract_stats['skipped_page_numbers']}"
        )

    if not chunks_list and raw_text:
        chunks_list = chunk_text(raw_text)

    if not chunks_list:
        return {"status": "error", "message": "Không trích xuất được văn bản từ tài liệu."}

    # Lưu document vào PostgreSQL (kèm content_hash, original_filename, processing_status)
    try:
        with get_cursor() as cur:
            cur.execute("""
                INSERT INTO documents (document_id, title, file_path, content_hash, original_filename, processing_status)
                VALUES (%s, %s, %s, %s, %s, 'processing')
                ON CONFLICT (document_id) DO UPDATE
                SET title = EXCLUDED.title, updated_at = NOW()
            """, (doc_id, title, str(fp), content_hash, _original_filename))
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

    # Ghi processing_status = 'complete' vào PostgreSQL
    try:
        with get_cursor() as cur:
            cur.execute("""
                UPDATE documents
                SET processing_status = 'complete', updated_at = NOW()
                WHERE document_id = %s
            """, (doc_id,))
    except Exception as e:
        logger.error(f"Lỗi cập nhật processing_status=complete: {e}")

    result = {
        "status": "success",
        "doc_id": doc_id,
        "title": title,
        "total_chunks": len(chunks_list),
        "stored_chunks": stored_count,
    }
    if extract_stats:
        result["extract_stats"] = extract_stats

    return result

