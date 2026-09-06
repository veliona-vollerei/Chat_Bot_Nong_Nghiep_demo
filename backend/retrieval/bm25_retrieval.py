"""
BM25 Sparse Retrieval — GĐ3 Mục Hybrid Retrieval.

Học từ RAG-and-Agent (kavsir):
- Dense (ChromaDB + bge-m3) + BM25 Okapi song song
- Hợp nhất bằng Reciprocal Rank Fusion (RRF)
- Đặc biệt giúp bắt chính xác: tên thuốc BVTV, mã liều lượng,
  tên giống cây mà embedding hay nhầm/bỏ sót

Index BM25:
- Build lần đầu từ toàn bộ chunks trong ChromaDB
- Cache in-memory (lazy, chỉ build 1 lần)
- Tự rebuild khi chunk count thay đổi (invalidation đơn giản)

CHANGELOG:
    v1.0.0: BM25 sparse retrieval, kết hợp với ChromaDB dense qua RRF.
"""
import logging
import re
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# ─── BM25 Index Cache ──────────────────────────────────────────────────────────
_bm25_lock = threading.Lock()
_bm25_index = None          # BM25Okapi object
_bm25_corpus = None         # list[str] — raw text của từng chunk
_bm25_chunk_ids = None      # list[str] — chunk_id tương ứng
_bm25_chunk_count = 0       # số chunk lúc build index (để detect thay đổi)


def _tokenize_vi(text: str) -> list[str]:
    """
    Tokenizer đơn giản cho tiếng Việt (không dùng thư viện nặng).
    - Tách theo whitespace và dấu câu
    - Lowercase
    - Loại bỏ token < 2 ký tự
    """
    text = text.lower()
    tokens = re.findall(r'\b[\w]{2,}\b', text)
    return tokens


def _build_bm25_index(force_rebuild: bool = False) -> bool:
    """
    Build/rebuild BM25 index từ ChromaDB.

    Returns:
        True nếu index sẵn sàng, False nếu corpus rỗng hoặc lỗi.
    """
    global _bm25_index, _bm25_corpus, _bm25_chunk_ids, _bm25_chunk_count

    try:
        from backend.db.chroma_db import get_collection
        col = get_collection()
        total = col.count()

        if total == 0:
            logger.warning("BM25: ChromaDB trống, không build index")
            return False

        # Nếu count không thay đổi và index đã có → không cần rebuild
        if not force_rebuild and _bm25_index is not None and total == _bm25_chunk_count:
            return True

        logger.info(f"BM25: Building index từ {total} chunks...")

        # Lấy toàn bộ chunks từ ChromaDB
        results = col.get(
            include=["documents", "metadatas"],
            limit=total,
        )

        documents = results.get("documents", [])
        ids = results.get("ids", [])

        if not documents:
            logger.warning("BM25: Không lấy được documents từ ChromaDB")
            return False

        corpus = [_tokenize_vi(doc) for doc in documents]

        # pyrefly: ignore [missing-import]
        from rank_bm25 import BM25Okapi
        new_index = BM25Okapi(corpus)

        _bm25_index = new_index
        _bm25_corpus = documents
        _bm25_chunk_ids = ids
        _bm25_chunk_count = total

        logger.info(f"BM25: Index built OK ({total} chunks)")
        return True

    except Exception as e:
        logger.error(f"BM25: Build index error: {e}")
        return False


def bm25_search(
    query: str,
    top_k: int = 10,
    crop: Optional[str] = None,
) -> list[dict]:
    """
    Tìm kiếm BM25 trên toàn bộ corpus.

    Args:
        query: câu hỏi hoặc từ khóa tìm kiếm
        top_k: số kết quả trả về
        crop: nếu có, ưu tiên chunk cùng crop (không hard filter)

    Returns:
        list[{chunk_id, chunk_text, bm25_rank, bm25_score}]
        sorted by bm25_score descending
    """
    with _bm25_lock:
        ready = _build_bm25_index()
        if not ready:
            return []

        idx = _bm25_index
        corpus = _bm25_corpus
        chunk_ids = _bm25_chunk_ids

    if idx is None or not corpus:
        return []

    try:
        query_tokens = _tokenize_vi(query)
        if not query_tokens:
            return []

        scores = idx.get_scores(query_tokens)

        # Tạo list (index, score)
        indexed_scores = list(enumerate(scores))

        # Sắp xếp giảm dần theo score
        indexed_scores.sort(key=lambda x: x[1], reverse=True)

        results = []
        for rank, (i, score) in enumerate(indexed_scores[:top_k * 2]):  # lấy nhiều hơn để có buffer
            if score <= 0:
                continue
            results.append({
                "chunk_id": chunk_ids[i],
                "chunk_text": corpus[i],
                "bm25_rank": rank + 1,
                "bm25_score": float(score),
            })
            if len(results) >= top_k:
                break

        return results

    except Exception as e:
        logger.error(f"BM25: Search error: {e}")
        return []


def invalidate_bm25_cache():
    """Invalidate BM25 index cache (gọi sau khi có chunk mới được ingest)."""
    global _bm25_index, _bm25_chunk_count
    with _bm25_lock:
        _bm25_index = None
        _bm25_chunk_count = 0
    logger.info("BM25: Index cache invalidated")
