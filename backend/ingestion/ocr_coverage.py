"""
OCR Coverage Report — Mục 9 GĐ1.

Phân tích chất lượng extraction từ marker-master:
- Tỷ lệ trang có chữ kỹ thuật số vs trang scan/ảnh
- Phát hiện chunk rỗng, chunk quá ngắn (< MIN_CHARS)
- Ước tính coverage % dựa trên char density
- Gợi ý: tài liệu nào cần bật OCR hoặc nhập lại bản kỹ thuật số

Mục đích: admin biết bao nhiêu % tài liệu đã được index đúng,
           tài liệu nào đang bị miss do scan không có chữ số.

Chạy:
    python -m backend.ingestion.ocr_coverage --dir data/raw_uploads
    python -m backend.ingestion.ocr_coverage --doc_id doc_abc123
"""
import re
import json
import logging
import argparse
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)

# Ngưỡng phân loại
MIN_CHARS_PER_PAGE = 100        # Trang có < 100 ký tự = trang trống/scan
GOOD_CHARS_PER_PAGE = 500       # Trang có >= 500 ký tự = tốt
MIN_CHUNK_CHARS = 80            # Chunk < 80 ký tự = suspect
COVERAGE_WARN_THRESHOLD = 0.60  # Coverage < 60% → cần OCR/re-upload


@dataclass
class PageAnalysis:
    """Phân tích từng trang."""
    page_num: int
    char_count: int
    has_table: bool
    has_list: bool
    has_heading: bool
    quality: str   # "good", "sparse", "empty"


@dataclass
class ChunkAnalysis:
    """Phân tích từng chunk."""
    chunk_id: str
    char_count: int
    chunk_type: str
    heading_path: str
    quality: str   # "good", "short", "empty"
    issue: Optional[str] = None


@dataclass
class DocumentCoverageReport:
    """Báo cáo đầy đủ cho một tài liệu."""
    doc_id: str
    title: str
    file_path: str
    total_chars: int
    total_pages: int        # 0 nếu không biết
    total_chunks: int
    good_chunks: int
    short_chunks: int
    empty_chunks: int
    coverage_pct: float     # % chunks "good"
    estimated_pages_with_text: int
    estimated_pages_scan: int
    has_tables: bool
    has_headings: bool
    recommendation: str     # "ok", "needs_ocr", "needs_reupload", "partial"
    recommendation_detail: str
    chunk_analyses: list[ChunkAnalysis] = field(default_factory=list)
    page_analyses: list[PageAnalysis] = field(default_factory=list)


def analyze_extracted_text(
    text: str,
    doc_id: str = "unknown",
    title: str = "unknown",
    file_path: str = "",
    total_pages: int = 0,
) -> DocumentCoverageReport:
    """
    Phân tích văn bản đã extract để đánh giá OCR coverage.

    Args:
        text: Nội dung markdown từ marker-master
        doc_id: ID tài liệu
        title: Tên tài liệu
        file_path: Đường dẫn file gốc
        total_pages: Tổng số trang (từ marker stats nếu có)

    Returns:
        DocumentCoverageReport với coverage %, recommendation
    """
    from backend.ingestion.chunker import chunk_markdown

    total_chars = len(text)
    has_tables = bool(re.search(r'^\s*\|.+\|', text, re.MULTILINE))
    has_headings = bool(re.search(r'^#+\s+.+', text, re.MULTILINE))

    # Phân tích theo trang (nếu marker thêm page breaks)
    # marker dùng --- hoặc \f hoặc <!-- Page N --> để phân trang
    page_texts = _split_by_pages(text)
    page_analyses = []
    pages_with_text = 0
    pages_scan = 0

    for i, ptext in enumerate(page_texts):
        pchars = len(ptext.strip())
        phas_table = bool(re.search(r'^\s*\|.+\|', ptext, re.MULTILINE))
        phas_list = bool(re.search(r'^\s*[-*+]\s|^\s*\d+\.\s', ptext, re.MULTILINE))
        phas_heading = bool(re.search(r'^#+\s+.+', ptext, re.MULTILINE))

        if pchars >= MIN_CHARS_PER_PAGE:
            pquality = "good"
            pages_with_text += 1
        elif pchars > 0:
            pquality = "sparse"
            pages_with_text += 1
        else:
            pquality = "empty"
            pages_scan += 1

        page_analyses.append(PageAnalysis(
            page_num=i + 1,
            char_count=pchars,
            has_table=phas_table,
            has_list=phas_list,
            has_heading=phas_heading,
            quality=pquality,
        ))

    # Phân tích từng chunk
    chunks = chunk_markdown(text)
    chunk_analyses = []
    good_chunks = 0
    short_chunks = 0
    empty_chunks = 0

    for chunk in chunks:
        cchars = chunk.char_count
        if cchars >= MIN_CHUNK_CHARS:
            cquality = "good"
            good_chunks += 1
            issue = None
        elif cchars > 0:
            cquality = "short"
            short_chunks += 1
            issue = f"Chunk rất ngắn ({cchars} ký tự) — có thể bị cắt nhầm"
        else:
            cquality = "empty"
            empty_chunks += 1
            issue = "Chunk rỗng — cần loại bỏ"

        chunk_analyses.append(ChunkAnalysis(
            chunk_id=f"{doc_id}_chunk_{chunk.chunk_index}",
            char_count=cchars,
            chunk_type=chunk.chunk_type,
            heading_path=chunk.heading_path,
            quality=cquality,
            issue=issue,
        ))

    total_chunks = len(chunks)
    coverage_pct = (good_chunks / total_chunks * 100) if total_chunks > 0 else 0.0

    # Đưa ra khuyến nghị
    recommendation, detail = _compute_recommendation(
        coverage_pct=coverage_pct,
        total_chars=total_chars,
        total_pages=total_pages or len(page_texts),
        pages_scan=pages_scan,
        has_tables=has_tables,
    )

    return DocumentCoverageReport(
        doc_id=doc_id,
        title=title,
        file_path=file_path,
        total_chars=total_chars,
        total_pages=total_pages or len(page_texts),
        total_chunks=total_chunks,
        good_chunks=good_chunks,
        short_chunks=short_chunks,
        empty_chunks=empty_chunks,
        coverage_pct=round(coverage_pct, 1),
        estimated_pages_with_text=pages_with_text,
        estimated_pages_scan=pages_scan,
        has_tables=has_tables,
        has_headings=has_headings,
        recommendation=recommendation,
        recommendation_detail=detail,
        chunk_analyses=chunk_analyses,
        page_analyses=page_analyses,
    )


def _split_by_pages(text: str) -> list[str]:
    """
    Tách text thành các trang nếu có page marker.
    marker-master thường dùng '---' hoặc '\f' hoặc <!-- Page N -->.
    """
    # Thử các separator phổ biến
    for sep in ['\f', '\n---\n', '<!-- page break -->']:
        if sep in text:
            pages = text.split(sep)
            return [p for p in pages if p]

    # Không có separator → xem như 1 trang duy nhất
    # Ước tính số trang theo độ dài (khoảng 2000 ký tự/trang)
    avg_chars_per_page = 2000
    if len(text) > avg_chars_per_page:
        pages = []
        for i in range(0, len(text), avg_chars_per_page):
            pages.append(text[i:i + avg_chars_per_page])
        return pages

    return [text]


def _compute_recommendation(
    coverage_pct: float,
    total_chars: int,
    total_pages: int,
    pages_scan: int,
    has_tables: bool,
) -> tuple[str, str]:
    """Tính recommendation dựa trên các chỉ số coverage."""
    if total_chars == 0:
        return (
            "needs_ocr",
            "Không trích xuất được ký tự nào. Tài liệu có thể toàn ảnh scan. "
            "Cần bật OCR hoặc upload bản PDF kỹ thuật số."
        )

    scan_ratio = pages_scan / total_pages if total_pages > 0 else 0

    if coverage_pct >= 80 and scan_ratio < 0.1:
        return (
            "ok",
            f"Tài liệu chất lượng tốt ({coverage_pct:.0f}% chunks đạt chuẩn). "
            f"Không cần xử lý thêm."
        )

    if coverage_pct >= 60:
        detail = f"Coverage {coverage_pct:.0f}% — chấp nhận được."
        if scan_ratio > 0.2:
            detail += f" {pages_scan}/{total_pages} trang nghi là scan."
        return ("partial", detail)

    if total_chars < 500:
        return (
            "needs_reupload",
            f"Tài liệu quá ít chữ ({total_chars} ký tự). "
            "Vui lòng upload lại bản kỹ thuật số chất lượng cao."
        )

    return (
        "needs_ocr",
        f"Coverage thấp ({coverage_pct:.0f}%). "
        f"{pages_scan}/{total_pages} trang có thể là scan. "
        "Cân nhắc bật OCR hoặc sử dụng bản PDF gốc kỹ thuật số."
    )


def analyze_from_chromadb(doc_id: str) -> Optional[DocumentCoverageReport]:
    """
    Phân tích coverage từ chunks đã lưu trong ChromaDB (không cần re-extract).
    Hữu ích để audit tài liệu đã ingest.
    """
    try:
        from backend.db.chroma_db import get_collection

        collection = get_collection()
        results = collection.get(
            where={"source_document_id": doc_id},
            include=["documents", "metadatas"],
        )

        if not results or not results.get("documents"):
            logger.warning(f"Không tìm thấy chunks cho doc_id={doc_id}")
            return None

        docs = results["documents"]
        metas = results.get("metadatas", [])

        chunk_analyses = []
        good = short = empty = 0

        for i, (chunk_text, meta) in enumerate(zip(docs, metas or [{}] * len(docs))):
            cchars = len(chunk_text) if chunk_text else 0
            if cchars >= MIN_CHUNK_CHARS:
                quality = "good"
                good += 1
                issue = None
            elif cchars > 0:
                quality = "short"
                short += 1
                issue = f"Ngắn ({cchars} ký tự)"
            else:
                quality = "empty"
                empty += 1
                issue = "Rỗng"

            chunk_analyses.append(ChunkAnalysis(
                chunk_id=f"{doc_id}_chunk_{i+1}",
                char_count=cchars,
                chunk_type=meta.get("chunk_type", "unknown"),
                heading_path=meta.get("heading_path", ""),
                quality=quality,
                issue=issue,
            ))

        total = len(docs)
        coverage = (good / total * 100) if total > 0 else 0.0
        rec, detail = _compute_recommendation(coverage, sum(len(d) for d in docs), 0, 0, False)

        return DocumentCoverageReport(
            doc_id=doc_id,
            title=metas[0].get("source", doc_id) if metas else doc_id,
            file_path="(từ ChromaDB)",
            total_chars=sum(len(d) for d in docs if d),
            total_pages=0,
            total_chunks=total,
            good_chunks=good,
            short_chunks=short,
            empty_chunks=empty,
            coverage_pct=round(coverage, 1),
            estimated_pages_with_text=0,
            estimated_pages_scan=0,
            has_tables=any(m.get("chunk_type") == "table" for m in (metas or [])),
            has_headings=any(m.get("heading_path") for m in (metas or [])),
            recommendation=rec,
            recommendation_detail=detail,
            chunk_analyses=chunk_analyses,
        )

    except Exception as e:
        logger.error(f"analyze_from_chromadb error: {e}")
        return None


def print_report(report: DocumentCoverageReport):
    """In báo cáo dạng human-readable."""
    rec_icon = {
        "ok": "✅",
        "partial": "⚠️",
        "needs_ocr": "🔴",
        "needs_reupload": "🔴",
    }.get(report.recommendation, "❓")

    print(f"\n{'='*60}")
    print(f"📄 OCR Coverage Report: {report.title}")
    print(f"   doc_id: {report.doc_id}")
    print(f"   file  : {report.file_path}")
    print(f"{'='*60}")
    print(f"  Total chars    : {report.total_chars:,}")
    print(f"  Total pages    : {report.total_pages}")
    print(f"  Pages w/ text  : {report.estimated_pages_with_text}")
    print(f"  Pages (scan?)  : {report.estimated_pages_scan}")
    print(f"  Total chunks   : {report.total_chunks}")
    print(f"  Good chunks    : {report.good_chunks} ({report.coverage_pct:.1f}%)")
    print(f"  Short chunks   : {report.short_chunks}")
    print(f"  Empty chunks   : {report.empty_chunks}")
    print(f"  Has tables     : {report.has_tables}")
    print(f"  Has headings   : {report.has_headings}")
    print(f"\n{rec_icon} Recommendation: {report.recommendation.upper()}")
    print(f"  {report.recommendation_detail}")

    if report.chunk_analyses:
        issues = [c for c in report.chunk_analyses if c.issue]
        if issues:
            print(f"\n  ⚠️  {len(issues)} chunk(s) có vấn đề:")
            for c in issues[:5]:  # Chỉ show 5 đầu
                print(f"     • {c.chunk_id}: {c.issue}")
            if len(issues) > 5:
                print(f"     ... và {len(issues) - 5} chunk khác")
    print()


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

    parser = argparse.ArgumentParser(description="OCR Coverage Report")
    parser.add_argument("--doc_id", help="doc_id để phân tích từ ChromaDB")
    parser.add_argument("--all", action="store_true", help="Phân tích tất cả tài liệu trong ChromaDB")
    parser.add_argument("--json", action="store_true", help="Xuất JSON thay vì text")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)

    if args.doc_id:
        report = analyze_from_chromadb(args.doc_id)
        if report:
            if args.json:
                print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
            else:
                print_report(report)
        else:
            print(f"Không tìm thấy doc_id={args.doc_id}")

    elif args.all:
        try:
            from backend.db.chroma_db import get_collection
            col = get_collection()
            all_metas = col.get(include=["metadatas"])["metadatas"] or []
            doc_ids = list({m.get("source_document_id") for m in all_metas if m.get("source_document_id")})
            print(f"Phân tích {len(doc_ids)} tài liệu...")
            reports = []
            for did in doc_ids:
                r = analyze_from_chromadb(did)
                if r:
                    reports.append(r)
                    if not args.json:
                        print_report(r)
            if args.json:
                print(json.dumps([asdict(r) for r in reports], ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"Lỗi: {e}")
    else:
        parser.print_help()
