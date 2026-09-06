"""
Tầng 3 — Document Store / RAG dùng ChromaDB.

ChromaDB tự xử lý vector index, filter metadata.
Filter metadata trước, search sau — đúng nguyên tắc kiến trúc.
"""
from typing import Optional
import logging

logger = logging.getLogger(__name__)

_embedder = None


def get_embedder():
    """Load embedding model (lazy, chỉ load 1 lần)."""
    global _embedder
    if _embedder is None:
        # pyrefly: ignore [missing-import]
        from sentence_transformers import SentenceTransformer
        from backend.config import EMBEDDING_MODEL, MODEL_CACHE_DIR
        logger.info(f"Loading embedding model: {EMBEDDING_MODEL} ...")
        _embedder = SentenceTransformer(
            EMBEDDING_MODEL,
            cache_folder=str(MODEL_CACHE_DIR)
        )
        logger.info("Embedding model loaded OK")
    return _embedder


def embed_query(text: str) -> list:
    """Embedding cho câu hỏi (prefix 'query:' theo chuẩn e5)."""
    return get_embedder().encode(
        f"query: {text}", normalize_embeddings=True
    ).tolist()


# Alias cho threshold_calibration module
_get_embedding_model = get_embedder


def embed_passage(text: str) -> list:
    """Embedding cho đoạn văn (prefix 'passage:')."""
    return get_embedder().encode(
        f"passage: {text}", normalize_embeddings=True
    ).tolist()


def semantic_search(
    query: str,
    crop: Optional[str] = None,
    season: Optional[str] = None,
    topic: Optional[str] = None,
    top_k: int = 5,
) -> dict:
    """
    Semantic search trong ChromaDB.
    Filter metadata trước (where clause) → search sau.
    """
    try:
        from backend.db.chroma_db import get_collection
        col = get_collection()

        if col.count() == 0:
            return {"found": False, "chunks": [], "source_info": "Kho tài liệu trống. Hãy chạy scripts/ingest_chunks.py trước."}

        # GĐ1 Mục 1: crop=None → không filter, tìm trên toàn corpus
        EXACT_FILTER_CROPS = {"lúa", "vải", "nhãn", "cam", "bưởi", "xoài", "chuối", "dứa", "na", "chanh leo", "mận", "cà phê"}
        use_crop_filter = crop is not None and crop.lower() in EXACT_FILTER_CROPS

        query_embedding = embed_query(query)

        if use_crop_filter:
            where = {"$or": [{"crop": {"$eq": crop}}, {"crop": {"$eq": "nông nghiệp tổng quát"}}]}
            try:
                results = col.query(
                    query_embeddings=[query_embedding],
                    n_results=min(top_k * 3, col.count()),
                    where=where,
                    include=["documents", "metadatas", "distances"]
                )
            except Exception:
                results = col.query(
                    query_embeddings=[query_embedding],
                    n_results=min(top_k * 3, col.count()),
                    include=["documents", "metadatas", "distances"]
                )
        else:
            # Không filter crop — tìm trên toàn bộ corpus đa tài liệu
            results = col.query(
                query_embeddings=[query_embedding],
                n_results=min(top_k * 3, col.count()),
                include=["documents", "metadatas", "distances"]
            )
    except Exception as e:
        logger.warning(f"Semantic search / ChromaDB query error: {e}")
        return {"found": False, "chunks": [], "source_info": ""}

    if not results["ids"][0]:
        return {"found": False, "chunks": [], "source_info": ""}

    # Lắp ráp kết quả + filter theo season nếu cần
    MIN_SIMILARITY = 0.35  # ChromaDB distance: nhỏ = giống nhau (cosine distance)
    chunks = []
    for doc_id, doc, meta, dist in zip(
        results["ids"][0],
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        similarity = 1 - dist  # Chuyển distance → similarity

        if similarity < MIN_SIMILARITY:
            continue

        # Filter mùa vụ sau (nếu có yêu cầu)
        if season and meta.get("season") and meta["season"] != season:
            continue

        chunks.append({
            "chunk_id": doc_id,
            "chunk_text": doc,
            "topic": meta.get("topic", ""),
            "season": meta.get("season"),
            "source": meta.get("source", "doc_001"),
            "source_document_id": meta.get("source_document_id", "doc_001"),
            "confidence": meta.get("confidence", "chính thống"),
            "year_published": meta.get("year_published"),
            "similarity": round(similarity, 4),
            # GĐ1 Mục 8: metadata cấu trúc cho context-aware retrieval
            "heading_path": meta.get("heading_path", ""),
            "chunk_type": meta.get("chunk_type", "paragraph"),
            "source_section": meta.get("source_section", ""),
        })

        if len(chunks) >= top_k:
            break

    if not chunks:
        return {"found": False, "chunks": [], "source_info": ""}

    unique_sources = list(dict.fromkeys(c.get("source") for c in chunks if c.get("source")))
    source_str = ", ".join(unique_sources) if unique_sources else "Kho tri thức Nông nghiệp"

    return {
        "found": True,
        "chunks": chunks,
        "source_info": source_str
    }


def store_chunk(chunk: dict) -> bool:
    """
    Lưu một chunk vào ChromaDB.

    chunk cần: chunk_id, chunk_text, crop, season, topic,
               source, source_document_id, confidence, year_published
    """
    from backend.db.chroma_db import get_collection
    col = get_collection()

    embedding = embed_passage(chunk["chunk_text"])

    metadata = {
        "crop":              chunk.get("crop", "nông nghiệp tổng quát"),
        "season":            chunk.get("season") or "",
        "topic":             chunk.get("topic") or "",
        "source":            chunk.get("source", "doc_001"),
        "source_document_id": chunk.get("source_document_id", "doc_001"),
        "confidence":        chunk.get("confidence", "chính thống"),
        "year_published":    chunk.get("year_published", 2024),
        # GĐ1 Mục 8: metadata cấu trúc
        "heading_path":      chunk.get("heading_path") or "",
        "chunk_type":        chunk.get("chunk_type") or "paragraph",
        "source_section":    chunk.get("source_section") or "",
    }
    # ChromaDB không chấp nhận None trong metadata
    metadata = {k: v for k, v in metadata.items() if v is not None}

    try:
        col.upsert(
            ids=[chunk["chunk_id"]],
            embeddings=[embedding],
            documents=[chunk["chunk_text"]],
            metadatas=[metadata],
        )
        return True
    except Exception as e:
        logger.error(f"ChromaDB store error {chunk.get('chunk_id')}: {e}")
        return False


def get_chunk_count() -> int:
    """Đếm số chunk đang có trong ChromaDB."""
    from backend.db.chroma_db import get_collection
    return get_collection().count()


def hybrid_search(
    query: str,
    crop: Optional[str] = None,
    season: Optional[str] = None,
    top_k: int = 5,
) -> dict:
    """
    Hybrid Retrieval: Dense (ChromaDB) + Sparse (BM25) → hợp nhất qua RRF.

    Học từ RAG-and-Agent (kavsir):
    - Dense: tốt cho semantic similarity (khái niệm, ý nghĩa)
    - BM25: tốt cho exact match (tên thuốc BVTV, tên giống, mã liều lượng)
    - RRF: kết hợp tốt nhất của cả hai, giảm phụ thuộc threshold

    Đặc biệt cải thiện nhóm câu định_lượng (F1 0.782 hiện tại).

    Args:
        query: câu hỏi
        crop: loại cây (có thể rỗng → search toàn corpus)
        season: mùa vụ (filter sau khi retrieve)
        top_k: số kết quả

    Returns: dict giống semantic_search() để backward compat
        {"found": bool, "chunks": list, "source_info": str}
    """
    from backend.retrieval.bm25_retrieval import bm25_search
    from backend.retrieval.rrf_merger import rrf_merge

    # ─── Dense retrieval ──────────────────────────────────────────────────
    # Lấy nhiều hơn top_k để RRF có đủ candidates
    dense_result = semantic_search(query=query, crop=crop, season=season, top_k=top_k * 2)
    dense_chunks = dense_result.get("chunks", [])

    # ─── Sparse (BM25) retrieval ──────────────────────────────────────────
    sparse_chunks = []
    try:
        sparse_chunks = bm25_search(query=query, top_k=top_k * 2, crop=crop or None)
    except Exception as e:
        logger.warning(f"BM25 search failed, falling back to dense only: {e}")

    # ─── Nếu không có sparse results → trả về dense như cũ ──────────────
    if not sparse_chunks:
        # Trim về top_k
        if dense_result.get("found"):
            dense_result["chunks"] = dense_chunks[:top_k]
            dense_result["retrieval_mode"] = "dense_only"
        return dense_result

    # ─── RRF Merge ───────────────────────────────────────────────────────
    merged = rrf_merge(dense_chunks, sparse_chunks, k=60, top_k=top_k)

    if not merged:
        # Fallback về dense nếu merge thất bại
        if dense_result.get("found"):
            dense_result["chunks"] = dense_chunks[:top_k]
            dense_result["retrieval_mode"] = "dense_only_fallback"
        return dense_result

    # ─── Lắp ráp kết quả ──────────────────────────────────────────────────
    # Bổ sung fields cần thiết nếu thiếu (BM25 chunk không có similarity)
    for chunk in merged:
        chunk.setdefault("similarity", chunk.get("rrf_score", 0.0))
        chunk.setdefault("topic", "")
        chunk.setdefault("source", "doc_001")
        chunk.setdefault("source_document_id", "doc_001")
        chunk.setdefault("confidence", "chính thống")
        chunk.setdefault("heading_path", "")
        chunk.setdefault("chunk_type", "paragraph")
        chunk.setdefault("source_section", "")

    unique_sources = list(dict.fromkeys(c.get("source") for c in merged if c.get("source")))
    source_str = ", ".join(unique_sources) if unique_sources else "Kho tri thức Nông nghiệp"

    # Thống kê để debug
    n_from_both = sum(1 for c in merged if "sources" in c and len(c.get("sources", [])) > 1)
    logger.debug(
        f"HybridSearch: {len(dense_chunks)} dense + {len(sparse_chunks)} sparse → "
        f"{len(merged)} merged ({n_from_both} xuất hiện cả 2 nguồn)"
    )

    return {
        "found": True,
        "chunks": merged,
        "source_info": source_str,
        "retrieval_mode": "hybrid_rrf",
    }

