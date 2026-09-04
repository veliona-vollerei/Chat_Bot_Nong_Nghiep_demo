"""
Tầng 1 — Structured Fact Store.

Nguyên tắc bất biến:
- Số liệu định lượng CHỈ được trả về từ module này
- LLM KHÔNG được tự sinh số liệu
- Khi không có dữ liệu → trả về None, không suy đoán

CHANGELOG:
    GĐ1 Mục 4: Thêm fail-closed policy cho dữ liệu rủi ro (liều lượng, tưới, nồng độ).
              Không được bỏ qua season/soil/growth_stage khi thiếu — phải từ chối hoặc hỏi thêm.
    GĐ1 Mục 6: Thêm growth_stage vào signature để khớp với schema Fact mới.
"""
from typing import Optional
from backend.db.postgres import get_cursor
import logging

logger = logging.getLogger(__name__)

# Danh sách attribute có rủi ro cao (liều lượng, tưới, nồng độ)
# Fail-closed: bắt buộc có growth_stage hoặc soil_type khi có lượng câu hỏi định lượng
HIGH_RISK_KEYWORDS = {
    "liều", "liều lượng", "lượng", "nồng độ", "tưới", "phân",
    "thuốc", "dose", "concentration", "irrigation",
    "bón", "xịt", "phụn",
}


def get_fact(
    attribute: str,
    crop: Optional[str] = None,     # GĐ1 Mục 1: None nếu không xác định
    season: Optional[str] = None,
    soil_type: Optional[str] = None,
    growth_stage: Optional[str] = None,  # GĐ1 Mục 6: thêm mới
) -> dict:
    """
    Truy vấn fact từ PostgreSQL theo key chính xác.

    GĐ1 Mục 4 — Fail-Closed Policy:
    Khi attribute là dữ liệu rủi ro (liều lượng, tưới, nồng độ),
    nếu thiếu điều kiện áp dụng (season/soil/growth_stage) → trả về
    found=False với flag requires_clarification=True.
    Không trả về số liệu chung cho dữ liệu rủi ro.

    Returns:
        {
            "found": bool,
            "is_partial_match": bool,  # True nếu chỉ khớp một phần điều kiện
            "requires_clarification": bool,  # True nếu fail-closed do thiếu điều kiện
            "results": [...],          # Danh sách fact khớp
            "warning": str | None      # Cảnh báo khi partial match
        }
    """
    # GĐ1 Mục 4: Kiểm tra fail-closed cho dữ liệu rủi ro
    attr_lower = attribute.lower()
    is_high_risk = any(kw in attr_lower for kw in HIGH_RISK_KEYWORDS)

    if is_high_risk:
        # Với dữ liệu rủi ro: cần ít nhất 1 trong {season, soil_type, growth_stage}
        has_condition = season or soil_type or growth_stage
        if not has_condition:
            logger.warning(
                f"FAIL-CLOSED: attribute='{attribute}' là dữ liệu rủi ro nhưng thiếu "
                f"season/soil_type/growth_stage. Từ chối trả về số liệu chung."
            )
            return {
                "found": False,
                "is_partial_match": False,
                "requires_clarification": True,
                "results": [],
                "warning": (
                    f"⚠️ Dữ liệu '{attribute}' đòi hỏi điều kiện cụ thể ("
                    f"mùa vụ, loại đất, hoặc giai đoạn sinh trưởng). "
                    f"Không thể trả về số liệu chung cho thông tin rủi ro này."
                ),
            }

    # Thử match đầy đủ trước
    results = _query_facts(attribute, crop, season, soil_type, growth_stage, strict=True)

    if results:
        return {
            "found": True,
            "is_partial_match": False,
            "requires_clarification": False,
            "results": results,
            "warning": None
        }

    # Nếu không có → thử match một phần (bỏ dần điều kiện)
    # Chỉ thực hiện cho dữ liệu KHÔNG rủi ro (fail-open)
    if not is_high_risk:
        partial_results = _query_facts(
            attribute, crop, season=None, soil_type=None, growth_stage=None, strict=False
        )

        if partial_results:
            # Xây dựng warning message
            missing = []
            if season:
                missing.append(f"mùa vụ '{season}'")
            if soil_type:
                missing.append(f"loại đất '{soil_type}'")
            if growth_stage:
                missing.append(f"giai đoạn '{growth_stage}'")
            warning = (
                f"⚠️ Không tìm thấy số liệu chính xác cho {', '.join(missing)}. "
                f"Kết quả dưới đây là số liệu chung — hãy tham khảo thêm với khuyến nông địa phương."
            )
            return {
                "found": True,
                "is_partial_match": True,
                "requires_clarification": False,
                "results": partial_results,
                "warning": warning
            }

    # Thực sự không có dữ liệu
    return {
        "found": False,
        "is_partial_match": False,
        "requires_clarification": False,
        "results": [],
        "warning": None
    }


def _query_facts(
    attribute: str,
    crop: Optional[str],
    season: Optional[str],
    soil_type: Optional[str],
    growth_stage: Optional[str] = None,  # GĐ1 Mục 6: thêm mới
    strict: bool = True,
) -> list:
    """Chạy SQL query tìm facts."""
    conditions = ["LOWER(attribute) LIKE LOWER(%s)"]
    params = [f"%{attribute}%"]

    # Crop: filter nếu có (GĐ1 Mục 1: crop có thể là None)
    if crop:
        conditions.append("crop = %s")
        params.append(crop)

    if season and strict:
        conditions.append("(season = %s OR season IS NULL)")
        params.append(season)

    if soil_type and strict:
        conditions.append("(soil_type = %s OR soil_type IS NULL)")
        params.append(soil_type)

    # GĐ1 Mục 6: filter growth_stage nếu có (cột có thể chưa tồn tại trong DB cũ)
    if growth_stage and strict:
        # Dùng try/except để backward compat nếu cột chưa migrate
        conditions.append("(growth_stage = %s OR growth_stage IS NULL)")
        params.append(growth_stage)

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
        # Nếu cột growth_stage chưa tồn tại, thử lại không có nó
        if "growth_stage" in str(e) and growth_stage:
            logger.warning(f"growth_stage column not yet migrated, retrying without: {e}")
            conditions_no_gs = [c for c in conditions if "growth_stage" not in c]
            params_no_gs = params[:-1] if growth_stage in params else params
            query_no_gs = f"""
                SELECT fact_id, crop, season, soil_type, attribute, value, unit,
                       condition_note, source, legal_basis, year_effective, confidence,
                       source_chunk_id, source_document_id
                FROM facts
                WHERE {' AND '.join(conditions_no_gs)}
                ORDER BY
                    CASE WHEN season IS NOT NULL THEN 0 ELSE 1 END,
                    CASE WHEN soil_type IS NOT NULL THEN 0 ELSE 1 END
                LIMIT 10
            """
            try:
                with get_cursor() as cur2:
                    cur2.execute(query_no_gs, params_no_gs)
                    return [dict(row) for row in cur2.fetchall()]
            except Exception as e2:
                logger.error(f"Lỗi query facts (fallback): {e2}")
                return []
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
