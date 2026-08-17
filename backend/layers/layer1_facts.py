"""
Tầng 1 — Structured Fact Store.

Nguyên tắc bất biến:
- Số liệu định lượng CHỈ được trả về từ module này
- LLM KHÔNG được tự sinh số liệu
- Khi không có dữ liệu → trả về None, không suy đoán
"""
from typing import Optional
from backend.db.postgres import get_cursor
import logging

logger = logging.getLogger(__name__)


def get_fact(
    attribute: str,
    crop: str = "lúa",
    season: Optional[str] = None,
    soil_type: Optional[str] = None,
) -> dict:
    """
    Truy vấn fact từ PostgreSQL theo key chính xác.
    
    Returns:
        {
            "found": bool,
            "is_partial_match": bool,  # True nếu chỉ khớp một phần điều kiện
            "results": [...],          # Danh sách fact khớp
            "warning": str | None      # Cảnh báo khi partial match
        }
    """
    # Thử match đầy đủ trước
    results = _query_facts(attribute, crop, season, soil_type, strict=True)
    
    if results:
        return {
            "found": True,
            "is_partial_match": False,
            "results": results,
            "warning": None
        }
    
    # Nếu không có → thử match một phần (bỏ dần điều kiện)
    partial_results = _query_facts(attribute, crop, season=None, soil_type=None, strict=False)
    
    if partial_results:
        # Xây dựng warning message
        missing = []
        if season:
            missing.append(f"mùa vụ '{season}'")
        if soil_type:
            missing.append(f"loại đất '{soil_type}'")
        warning = (
            f"⚠️ Không tìm thấy số liệu chính xác cho {', '.join(missing)}. "
            f"Kết quả dưới đây là số liệu chung — hãy tham khảo thêm với khuyến nông địa phương."
        )
        return {
            "found": True,
            "is_partial_match": True,
            "results": partial_results,
            "warning": warning
        }
    
    # Thực sự không có dữ liệu
    return {
        "found": False,
        "is_partial_match": False,
        "results": [],
        "warning": None
    }


def _query_facts(
    attribute: str,
    crop: str,
    season: Optional[str],
    soil_type: Optional[str],
    strict: bool = True,
) -> list:
    """Chạy SQL query tìm facts."""
    conditions = ["crop = %s", "LOWER(attribute) LIKE LOWER(%s)"]
    params = [crop, f"%{attribute}%"]
    
    if season and strict:
        conditions.append("(season = %s OR season IS NULL)")
        params.append(season)
    
    if soil_type and strict:
        conditions.append("(soil_type = %s OR soil_type IS NULL)")
        params.append(soil_type)
    
    query = f"""
        SELECT fact_id, crop, season, soil_type, attribute, value, unit,
               condition_note, source, legal_basis, year_effective, confidence,
               source_chunk_id, source_document_id
        FROM facts
        WHERE {' AND '.join(conditions)}
        ORDER BY 
            CASE WHEN season IS NOT NULL THEN 0 ELSE 1 END,
            CASE WHEN soil_type IS NOT NULL THEN 0 ELSE 1 END
        LIMIT 10
    """
    
    try:
        with get_cursor() as cur:
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Lỗi query facts: {e}")
        return []


def get_rice_variety(variety_name: str) -> Optional[dict]:
    """Tra cứu thông tin giống lúa theo tên."""
    query = """
        SELECT * FROM rice_varieties
        WHERE LOWER(variety_name) LIKE LOWER(%s)
        LIMIT 5
    """
    try:
        with get_cursor() as cur:
            cur.execute(query, [f"%{variety_name}%"])
            rows = cur.fetchall()
            return [dict(r) for r in rows] if rows else None
    except Exception as e:
        logger.error(f"Lỗi query rice_varieties: {e}")
        return None


def get_all_rice_varieties() -> list:
    """Lấy danh sách tất cả giống lúa."""
    try:
        with get_cursor() as cur:
            cur.execute("SELECT variety_name, duration_days, yield_potential, resistance FROM rice_varieties ORDER BY variety_name")
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Lỗi query rice_varieties: {e}")
        return []


def search_facts_by_topic(topic: str) -> list:
    """Tìm tất cả facts liên quan đến một chủ đề."""
    query = """
        SELECT attribute, value, unit, season, soil_type, condition_note, source_document_id
        FROM facts
        WHERE LOWER(attribute) LIKE LOWER(%s) OR LOWER(condition_note) LIKE LOWER(%s)
        ORDER BY season NULLS LAST
        LIMIT 20
    """
    try:
        with get_cursor() as cur:
            cur.execute(query, [f"%{topic}%", f"%{topic}%"])
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"Lỗi search_facts_by_topic: {e}")
        return []
