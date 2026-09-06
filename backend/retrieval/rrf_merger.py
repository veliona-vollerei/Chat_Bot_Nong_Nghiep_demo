"""
Reciprocal Rank Fusion (RRF) Merger — GĐ3 Mục Hybrid Retrieval.

Học từ RAG-and-Agent (kavsir):
- Hợp nhất Dense + BM25 bằng RRF: score = 1/(k + rank)
- Không cộng điểm thô (thang điểm khác nhau)
- k=60 là giá trị mặc định từ paper RRF gốc (Cormack et al. 2009)

Ưu điểm:
- Dense: tốt cho semantic similarity (khái niệm, ý nghĩa)
- BM25: tốt cho exact match (tên thuốc, tên giống, mã số, liều lượng)
- RRF: kết hợp cả hai, giảm phụ thuộc vào "threshold tối ưu" duy nhất

CHANGELOG:
    v1.0.0: RRF merger cho Dense + BM25.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def rrf_merge(
    dense_chunks: list[dict],
    sparse_chunks: list[dict],
    k: int = 60,
    top_k: int = 5,
) -> list[dict]:
    """
    Hợp nhất kết quả dense và sparse retrieval bằng Reciprocal Rank Fusion.

    Công thức: score(d) = sum( 1 / (k + rank_in_list) ) cho mỗi list mà d xuất hiện

    Args:
        dense_chunks: list từ semantic_search, có field 'chunk_id', 'chunk_text', 'similarity'
        sparse_chunks: list từ bm25_search, có field 'chunk_id', 'chunk_text', 'bm25_rank'
        k: RRF constant (mặc định 60 theo paper gốc)
        top_k: số kết quả trả về sau merge

    Returns:
        list[dict] — merged chunks sorted by RRF score, có thêm:
            'rrf_score': float
            'sources': list[str] — ["dense"] | ["sparse"] | ["dense", "sparse"]
    """
    # Build dict: chunk_id → {chunk data + rrf_score}
    rrf_scores: dict[str, dict] = {}

    # Dense results (rank dựa trên vị trí trong list, đã sắp xếp giảm dần theo similarity)
    for rank, chunk in enumerate(dense_chunks):
        cid = chunk.get("chunk_id", "")
        if not cid:
            continue
        score = 1.0 / (k + rank + 1)  # +1 vì rank bắt đầu từ 0
        if cid not in rrf_scores:
            rrf_scores[cid] = {**chunk, "rrf_score": 0.0, "sources": []}
        rrf_scores[cid]["rrf_score"] += score
        if "dense" not in rrf_scores[cid]["sources"]:
            rrf_scores[cid]["sources"].append("dense")

    # Sparse (BM25) results (rank đã có trong chunk, 1-indexed)
    for chunk in sparse_chunks:
        cid = chunk.get("chunk_id", "")
        if not cid:
            continue
        bm25_rank = chunk.get("bm25_rank", len(sparse_chunks))  # fallback cuối danh sách
        score = 1.0 / (k + bm25_rank)
        if cid not in rrf_scores:
            rrf_scores[cid] = {**chunk, "rrf_score": 0.0, "sources": []}
        rrf_scores[cid]["rrf_score"] += score
        if "sparse" not in rrf_scores[cid]["sources"]:
            rrf_scores[cid]["sources"].append("sparse")

    if not rrf_scores:
        return []

    # Sắp xếp theo RRF score giảm dần
    merged = sorted(rrf_scores.values(), key=lambda x: x["rrf_score"], reverse=True)

    # Trả về top_k
    result = merged[:top_k]

    logger.debug(
        f"RRF: {len(dense_chunks)} dense + {len(sparse_chunks)} sparse → {len(result)} merged "
        f"(top rrf_score={result[0]['rrf_score']:.4f} if result else 'N/A')"
    )

    return result
