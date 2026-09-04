"""
Data Pipeline — Xử lý tài liệu thô nông nghiệp (PDF, DOCX, PPTX, XLSX, EPUB, HTML, TXT, MD, JSON)
Sử dụng marker-master để đọc tài liệu. Chỉ lấy chữ kỹ thuật số có sẵn trong file.
OCR đã tắt (disable_ocr=True) — không khởi động inference server, không xử lý ảnh scan.
Trang scan/ảnh thuần túy sẽ bị bỏ qua tự động mà không cần OCR.

CHANGELOG:
    GĐ1 Mục 8: Dùng StructureAwareChunker thay chunk_text() cũ cho thiết lập markdown (từ marker).
              Chúnh heading_path, chunk_type vào metadata ChromaDB.
    GĐ1 Mục 9: Thêm mini OCR coverage check sau extract.
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
from backend.ingestion.chunker import chunk_markdown, StructuredChunk
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
# Cấu hình marker-master path — thêm vào sys.path để import trực tiếp
# ──────────────────────────────────────────────────────────────────────────────
_MARKER_DIR = str(BASE_DIR / "marker-master")
if _MARKER_DIR not in sys.path:
    sys.path.insert(0, _MARKER_DIR)

# Định dạng marker hỗ trợ (ngoài txt/md/json xử lý riêng)
MARKER_SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".pptx", ".ppt",
    ".xlsx", ".xls", ".epub", ".html", ".htm",
}

# ──────────────────────────────────────────────────────────────────────────────
# Khởi tạo marker model dict một lần duy nhất (lazy — chỉ load khi cần)
# ──────────────────────────────────────────────────────────────────────────────
_marker_model_dict: Optional[Dict[str, Any]] = None


def _get_marker_models() -> Dict[str, Any]:
    """Lazy-load marker model dict (chỉ load lần đầu, tái dùng sau đó)."""
    global _marker_model_dict
    if _marker_model_dict is None:
        logger.info("🔧 Đang khởi tạo marker model dict (lần đầu)...")
        # pyrefly: ignore [missing-import]
        from marker.models import create_model_dict
        _marker_model_dict = create_model_dict()
        logger.info("✅ Marker model dict đã sẵn sàng.")
    return _marker_model_dict


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
# 1. extract_text_with_marker — Dùng marker-master để trích xuất văn bản
#    Hỗ trợ: PDF, DOCX, PPTX, XLSX, EPUB, HTML
#    OCR đã TẮT (disable_ocr=True) — chỉ đọc chữ kỹ thuật số, bỏ qua ảnh scan
# ──────────────────────────────────────────────────────────────────────────────

def extract_text_with_marker(
    file_path: Path,
    doc_id: str = "",
) -> Tuple[str, Dict[str, Any]]:
    """
    Trích xuất văn bản từ tài liệu bằng marker-master.
    Hỗ trợ: .pdf, .docx, .doc, .pptx, .ppt, .xlsx, .xls, .epub, .html

    OCR đã TẮT — chỉ đọc chữ kỹ thuật số có sẵn trong file.
    Trang scan/ảnh thuần túy sẽ bị bỏ qua tự động (không crash, không tốn API).

    Returns:
        (markdown_text, stats)
        stats = {
            "extractor": "marker",
            "file_type": str,
            "page_count": int,
            "char_count": int,
            "ocr_disabled": True,
        }
    """
    # pyrefly: ignore [missing-import]
    from marker.converters.pdf import PdfConverter

    stats: Dict[str, Any] = {
        "extractor": "marker",
        "file_type": file_path.suffix.lower(),
        "page_count": 0,
        "char_count": 0,
        "ocr_disabled": True,
    }

    try:
        model_dict = _get_marker_models()

        # Config: tắt OCR, tắt LLM, tắt debug
        config = {
            "disable_ocr": True,   # Không dùng OCR — chỉ đọc chữ kỹ thuật số
            "use_llm": False,      # Không dùng LLM processor
            "disable_tqdm": True,  # Ẩn progress bar trong log
        }

        converter = PdfConverter(
            artifact_dict=model_dict,
            config=config,
        )

        rendered = converter(str(file_path))

        # rendered là MarkdownOutput: .markdown, .images, .metadata
        markdown_text = rendered.markdown or ""
        stats["char_count"] = len(markdown_text)

        # Lấy page count từ converter nếu có
        if hasattr(converter, "page_count") and converter.page_count:
            stats["page_count"] = converter.page_count

        logger.info(
            f"📄 marker [{file_path.suffix.upper()}] {file_path.name}: "
            f"{stats['char_count']:,} ký tự, "
            f"{stats['page_count']} trang, OCR=OFF"
        )
        return markdown_text, stats

    except Exception as e:
        logger.error(f"❌ Lỗi extract_text_with_marker({file_path.name}): {e}")
        return "", stats


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
    1. Đọc văn bản thô qua marker-master (không OCR)
    2. Chia chunks
    3. Tạo metadata & lưu vào ChromaDB + PostgreSQL

    Định dạng hỗ trợ:
      marker-master (không OCR): .pdf, .docx, .doc, .pptx, .ppt,
                                  .xlsx, .xls, .epub, .html, .htm
      Xử lý riêng (không cần marker): .txt, .md, .json

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
    extract_stats: Optional[Dict[str, Any]] = None

    # ── Định dạng xử lý bằng marker-master ──
    if ext in MARKER_SUPPORTED_EXTENSIONS:
        raw_text, extract_stats = extract_text_with_marker(fp, doc_id=doc_id)

        if extract_stats and extract_stats.get("char_count", 0) == 0:
            logger.warning(
                f"⚠️ {fp.name}: marker không trích xuất được chữ nào "
                f"(có thể toàn ảnh scan — OCR đã tắt)."
            )

    # ── Định dạng đơn giản xử lý trực tiếp ──
    elif ext in (".txt", ".md"):
        raw_text = fp.read_text(encoding="utf-8", errors="ignore")

    elif ext == ".json":
        data = json.loads(fp.read_text(encoding="utf-8", errors="ignore"))
        if isinstance(data, list):
            chunks_list = [
                str(item.get("text", item)) if isinstance(item, dict) else str(item)
                for item in data
            ]
        else:
            raw_text = str(data)

    else:
        raise ValueError(f"Định dạng file không được hỗ trợ: {ext}")

    if not chunks_list and raw_text:
        if ext in MARKER_SUPPORTED_EXTENSIONS:
            # GĐ1 Mục 8: Dùng Structure-Aware Chunker cho văn bản markdown từ marker
            structured = chunk_markdown(raw_text)
            chunks_list = structured  # List[StructuredChunk]

            # Mini OCR coverage check (Mục 9)
            _n_good = sum(1 for c in structured if c.char_count >= 80)
            _coverage = (_n_good / len(structured) * 100) if structured else 0
            if _coverage < 60:
                logger.warning(
                    f"⚠️ OCR coverage thấp: {_coverage:.0f}% chunks đạt chuẩn ({_n_good}/{len(structured)}). "
                    f"Tài liệu '{title}' có thể cần OCR hoặc upload lại bản kỹ thuật số."
                )
        else:
            # Fallback đơn giản cho .txt / .md
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
    for i, c_item in enumerate(chunks_list):
        # GĐ1 Mục 8: hỗ trợ cả StructuredChunk lẫn str (fallback)
        if isinstance(c_item, StructuredChunk):
            c_text = c_item.chunk_text
            heading_path = c_item.heading_path
            chunk_type = c_item.chunk_type
            source_section = c_item.source_section
        else:
            c_text = c_item
            heading_path = ""
            chunk_type = "paragraph"
            source_section = ""

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
            # GĐ1 Mục 8: metadata cấu trúc — phục vụ context-aware retrieval
            "heading_path": heading_path,
            "chunk_type": chunk_type,
            "source_section": source_section,
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
