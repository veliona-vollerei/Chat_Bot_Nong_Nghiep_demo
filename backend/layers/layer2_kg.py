"""
Tầng 2 — Knowledge Graph lưu trong PostgreSQL.

Thay Neo4j bằng bảng kg_triples trong PostgreSQL.
Truy vấn bằng SQL thay Cypher — đơn giản hơn, không cần cài Neo4j.

Nguyên tắc bất biến:
- Quan hệ giống-đất-kỹ thuật-sâu bệnh CHỈ đến từ bảng này
- LLM KHÔNG được tự suy luận quan hệ
"""
from typing import Optional
from backend.db.postgres import get_cursor
import logging

logger = logging.getLogger(__name__)


def find_suitable_varieties(
    soil_type: Optional[str] = None,
    season: Optional[str] = None,
) -> dict:
    """Tìm giống lúa phù hợp theo loại đất hoặc mùa vụ."""

    if soil_type:
        query = """
            SELECT t.entity_a AS giong,
                   t.entity_b AS loai_dat,
                   t.source_chunk_id,
                   t.confidence,
                   rv.duration_days AS tgst,
                   rv.yield_potential AS nang_suat
            FROM kg_triples t
            LEFT JOIN rice_varieties rv ON LOWER(rv.variety_name) = LOWER(t.entity_a)
            WHERE t.relationship = 'PHÙ_HỢP_VỚI'
              AND t.entity_b_type = 'LoạiĐất'
              AND LOWER(t.entity_b) LIKE LOWER(%s)
            ORDER BY t.confidence DESC
        """
        params = [f"%{soil_type}%"]

    elif season:
        query = """
            SELECT t.entity_a AS giong,
                   t.entity_b AS thoi_vu,
                   t.source_chunk_id,
                   t.confidence,
                   rv.duration_days AS tgst,
                   rv.yield_potential AS nang_suat
            FROM kg_triples t
            LEFT JOIN rice_varieties rv ON LOWER(rv.variety_name) = LOWER(t.entity_a)
            WHERE t.relationship = 'TRỒNG_ĐƯỢC_VỤ'
              AND LOWER(t.entity_b) LIKE LOWER(%s)
            ORDER BY t.confidence DESC
        """
        params = [f"%{season}%"]

    else:
        # Trả về tất cả giống
        query = """
            SELECT variety_name AS giong, duration_days AS tgst,
                   yield_potential AS nang_suat, resistance AS chong_chiu,
                   suitability AS thich_nghi, source_document_id AS source
            FROM rice_varieties
            ORDER BY variety_name
        """
        params = []

    try:
        with get_cursor() as cur:
            cur.execute(query, params)
            rows = [dict(r) for r in cur.fetchall()]
        return {
            "found": len(rows) > 0,
            "results": rows,
            "source_info": "Dữ liệu từ Knowledge Graph (PostgreSQL)"
        }
    except Exception as e:
        logger.error(f"KG query giống lúa: {e}")
        return {"found": False, "results": [], "source_info": ""}


def find_pest_info(pest_name: Optional[str] = None) -> dict:
    """Tìm thông tin sâu bệnh."""
    if pest_name:
        query = """
            SELECT entity_a AS sau_benh,
                   relationship AS quan_he,
                   entity_b AS lien_quan,
                   entity_b_type AS loai_lien_quan,
                   source_chunk_id AS source
            FROM kg_triples
            WHERE entity_a_type = 'SâuBệnh'
              AND LOWER(entity_a) LIKE LOWER(%s)
            ORDER BY relationship
        """
        params = [f"%{pest_name}%"]
    else:
        query = """
            SELECT DISTINCT entity_a AS sau_benh, entity_a_type
            FROM kg_triples WHERE entity_a_type = 'SâuBệnh'
        """
        params = []

    try:
        with get_cursor() as cur:
            cur.execute(query, params)
            rows = [dict(r) for r in cur.fetchall()]
        return {"found": len(rows) > 0, "results": rows, "source_info": "Knowledge Graph"}
    except Exception as e:
        logger.error(f"KG query sâu bệnh: {e}")
        return {"found": False, "results": [], "source_info": ""}


def find_technique_info(technique_name: Optional[str] = None) -> dict:
    """Tìm thông tin kỹ thuật canh tác."""
    if technique_name:
        query = """
            SELECT entity_a AS ky_thuat,
                   relationship AS quan_he,
                   entity_b AS ap_dung_cho,
                   source_chunk_id AS source
            FROM kg_triples
            WHERE entity_a_type = 'KỹThuật'
              AND (LOWER(entity_a) LIKE LOWER(%s)
                   OR LOWER(entity_b) LIKE LOWER(%s))
        """
        params = [f"%{technique_name}%", f"%{technique_name}%"]
    else:
        query = """
            SELECT DISTINCT entity_a AS ky_thuat
            FROM kg_triples WHERE entity_a_type = 'KỹThuật'
        """
        params = []

    try:
        with get_cursor() as cur:
            cur.execute(query, params)
            rows = [dict(r) for r in cur.fetchall()]
        return {"found": len(rows) > 0, "results": rows, "source_info": "Knowledge Graph"}
    except Exception as e:
        logger.error(f"KG query kỹ thuật: {e}")
        return {"found": False, "results": [], "source_info": ""}
