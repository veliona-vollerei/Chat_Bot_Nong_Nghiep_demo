"""
Data Pipeline — Xử lý tài liệu thô nông nghiệp (PDF, DOCX, TXT, MD, JSON)
Tích hợp marker-master và các parser dự phòng.
"""
import os
import sys
import json
import logging
from pathlib import Path
from typing import List, Dict, Any

from backend.config import BASE_DIR, GEMINI_API_KEY, GEMINI_ROUTER_MODEL
from backend.layers.layer3_docs import store_chunk
from backend.db.postgres import get_cursor

logger = logging.getLogger(__name__)

# Đảm bảo thư mục raw_uploads tồn tại
RAW_UPLOADS_DIR = BASE_DIR / "data" / "raw_uploads"
RAW_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def ocr_page_with_gemini(page_img_bytes: bytes, page_num: int) -> str:
    """Gọi Gemini Vision API để OCR 1 trang PDF dạng ảnh scan sang Markdown."""
    import time
    try:
        # pyrefly: ignore [missing-import]
        from google import genai
        # pyrefly: ignore [missing-import]
        from google.genai import types
        from backend.config import GEMINI_API_KEY, GEMINI_SYNTHESIS_MODEL

        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = (
            "Bạn là chuyên gia OCR. Hãy trích xuất toàn bộ văn bản, tiêu đề và bảng biểu "
            "trong trang tài liệu nông nghiệp này sang định dạng Markdown tiếng Việt chuẩn. "
            "Chỉ trả về nội dung Markdown bóc tách được, không kèm lời giải thích khác."
        )
        for attempt in range(3):
            try:
                res = client.models.generate_content(
                    model=GEMINI_SYNTHESIS_MODEL,
                    contents=[
                        types.Part.from_bytes(data=page_img_bytes, mime_type="image/png"),
                        prompt
                    ]
                )
                extracted = res.text.strip() if res.text else ""
                logger.info(f"✅ Gemini Vision OCR xong Trang {page_num} ({len(extracted)} chars)")
                return extracted
            except Exception as e:
                err_str = str(e)
                if any(k in err_str for k in ["429", "503", "500", "502", "504", "RESOURCE_EXHAUSTED", "UNAVAILABLE"]):
                    time.sleep(2 * (attempt + 1))
                else:
                    logger.error(f"❌ Lỗi Gemini Vision OCR Trang {page_num}: {e}")
                    break
        return ""
    except Exception as e:
        logger.error(f"❌ Lỗi Gemini Vision OCR Trang {page_num}: {e}")
        return ""


def extract_text_from_pdf(pdf_path: Path) -> str:
    """
    Rút trích văn bản từ file PDF:
    - Nếu trang có chữ điện tử (>= 50 ký tự): Lấy trực tiếp từ PyMuPDF (fitz).
    - Nếu trang là ảnh scan (< 50 ký tự): Tự động dùng Gemini Vision OCR đa luồng bóc tách chữ.
    """
    # pyrefly: ignore [missing-import]
    import fitz  # PyMuPDF
    from concurrent.futures import ThreadPoolExecutor, as_completed

    try:
        doc = fitz.open(str(pdf_path))
        num_pages = len(doc)
        logger.info(f"📄 Bắt đầu xử lý {pdf_path.name} ({num_pages} trang)...")

        pages_text = [""] * num_pages
        scan_pages_to_process = []

        for i, page in enumerate(doc):
            text = page.get_text() or ""
            if len(text.strip()) >= 50:
                pages_text[i] = f"\n--- Trang {i+1} ---\n" + text.strip()
            else:
                pix = page.get_pixmap(dpi=150)
                img_bytes = pix.tobytes("png")
                scan_pages_to_process.append((i, img_bytes))

        if scan_pages_to_process:
            logger.info(f"🔍 Phát hiện {len(scan_pages_to_process)}/{num_pages} trang dạng ảnh scan. Đang chạy Gemini Vision OCR đa luồng...")
            with ThreadPoolExecutor(max_workers=5) as executor:
                future_to_index = {
                    executor.submit(ocr_page_with_gemini, img_bytes, i + 1): i
                    for i, img_bytes in scan_pages_to_process
                }
                for future in as_completed(future_to_index):
                    idx = future_to_index[future]
                    try:
                        extracted = future.result()
                        if extracted:
                            pages_text[idx] = f"\n--- Trang {idx+1} ---\n" + extracted
                        else:
                            pages_text[idx] = f"\n--- Trang {idx+1} ---\n"
                    except Exception as e:
                        logger.error(f"Lỗi future trang {idx+1}: {e}")
                        pages_text[idx] = f"\n--- Trang {idx+1} ---\n"

        full_text = "\n\n".join([p for p in pages_text if p.strip()])
        logger.info(f"🎉 Hoàn thành bóc tách {pdf_path.name} — Tổng ký tự: {len(full_text)}")
        return full_text
    except Exception as e:
        logger.error(f"Lỗi extract_text_from_pdf: {e}")
        return ""


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


def process_and_ingest_document(file_path: str, custom_title: str = None) -> Dict[str, Any]:
    """
    Quy trình xử lý hoàn chỉnh 1 file tài liệu:
    1. Đọc văn bản thô
    2. Chia chunks
    3. Tạo metadata & lưu vào ChromaDB + PostgreSQL
    """
    fp = Path(file_path)
    if not fp.exists():
        raise FileNotFoundError(f"Không tìm thấy file: {file_path}")

    doc_id = f"doc_{fp.stem}_{int(os.path.getmtime(fp))}"
    title = custom_title or fp.name

    ext = fp.suffix.lower()
    raw_text = ""
    chunks_list = []

    if ext == ".pdf":
        raw_text = extract_text_from_pdf(fp)
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
    return {
        "status": "success",
        "doc_id": doc_id,
        "title": title,
        "total_chunks": len(chunks_list),
        "stored_chunks": stored_count
    }
