"""
Fast-path Rule-based Router — GĐ3 Mục Router.

Kiến trúc học từ RAG-and-Agent (kavsir):
- Layer 0→4 rule-based, 0 external API call, <5ms cho fast-path
- Chỉ fallback sang Gemini khi rule không chắc (ambiguous)
- Ghi reason_code/decision_path vào mọi quyết định để audit được

Nguyên tắc:
  1. Thử khớp pattern rõ ràng trước
  2. Nếu khớp → trả kết quả ngay (skip Gemini hoàn toàn)
  3. Nếu không khớp → trả None → caller fallback sang Gemini

CHANGELOG:
    v1.0.0: Initial fast-path router, học từ RAG-and-Agent Layer 0-4.
"""
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Từ khóa định lượng rõ ràng ──────────────────────────────────────────────
# Câu hỏi về số liệu cụ thể: liều lượng, hệ số, năng suất, mật độ, v.v.
_QUANTITATIVE_KEYWORDS = [
    # Phân bón
    r"\bliều lượng\b", r"\bkg/ha\b", r"\bkg/sào\b", r"\bkg/công\b",
    r"\bkg/m2\b", r"\bg/lít\b", r"\bml/lít\b", r"\bppm\b", r"\b%N\b",
    r"\bphân đạm\b.*\bliều\b", r"\bphân lân\b.*\bliều\b", r"\bphân kali\b.*\bliều\b",
    r"\bbón.*\bkg\b", r"\bbón.*\bgam\b", r"\blượng.*\bphân\b",
    # Mật độ, khoảng cách trồng
    r"\bmật độ\b.*\bcây\b", r"\bkhoảng cách\b.*\btrồng\b", r"\bcây/m2\b",
    r"\bcây/ha\b", r"\bhàng.*\bcây\b", r"\bcách.*\bcây\b",
    # Năng suất
    r"\bnăng suất\b.*\btấn\b", r"\bnăng suất\b.*\bkg\b", r"\btấn/ha\b",
    r"\bnăng suất trung bình\b",
    # Nước tưới
    r"\blượng nước\b", r"\bnước tưới\b.*\bmm\b", r"\bnước tưới\b.*\blít\b",
    r"\bngưỡng\b.*\bnước\b", r"\bngập\b.*\bcm\b",
    # Thời gian sinh trưởng
    r"\bngày sinh trưởng\b", r"\bthời gian\b.*\bngày\b.*\blúa\b",
    r"\bngày\b.*\btrổ\b", r"\bngày\b.*\bthu hoạch\b",
    # Thuốc BVTV liều lượng
    r"\bnồng độ\b.*\bthuốc\b", r"\bliều\b.*\bthuốc\b", r"\bphun.*\bml\b",
    r"\bphun.*\bgam\b", r"\bl/ha\b", r"\bcc/lít\b",
]

# ─── Từ khóa phù hợp/quan hệ rõ ràng ────────────────────────────────────────
_RELATION_KEYWORDS = [
    r"\bgiống nào\b.*\bphù hợp\b", r"\bgiống nào\b.*\bthích hợp\b",
    r"\bgiống nào\b.*\bchịu\b", r"\bgiống.*\bphù hợp\b.*\bđất\b",
    r"\bgiống.*\bphù hợp\b.*\bmùa\b", r"\bgiống.*\bphù hợp\b.*\bvùng\b",
    r"\bnên trồng giống\b", r"\bchọn giống\b",
    r"\bsâu\b.*\bgây hại\b", r"\bbệnh\b.*\bgây hại\b", r"\bsâu bệnh\b.*\btrên\b",
    r"\bphòng trừ\b.*\bsâu\b", r"\bphòng trừ\b.*\bbệnh\b",
    r"\bthiên địch\b", r"\bkiểm soát sinh học\b",
    r"\bđất phèn\b.*\btrồng\b", r"\bđất mặn\b.*\btrồng\b",
    r"\bphù hợp\b.*\bvụ\b.*\b(Đông Xuân|Hè Thu|Mùa)\b",
    r"\bquan hệ\b.*\b(cây|giống|sâu|bệnh)\b",
]

# ─── Từ khóa diễn giải rõ ràng ───────────────────────────────────────────────
_EXPLANATION_KEYWORDS = [
    r"\btại sao\b", r"\bvì sao\b", r"\bnguyên nhân\b",
    r"\bcách\b.*\b(bón|tưới|phun|phòng|xử lý|canh tác|thu hoạch|bảo quản)\b",
    r"\bquy trình\b", r"\bkỹ thuật\b.*\bcanh tác\b",
    r"\bhướng dẫn\b", r"\bgiải thích\b", r"\bkhái niệm\b",
    r"\bbảo quản\b.*\b(lúa|gạo|rau|quả|nông sản)\b",
    r"\bquy trình thu hoạch\b", r"\bkỹ thuật canh tác\b",
]

# ─── Từ khóa ngoài phạm vi rõ ràng ──────────────────────────────────────────
_OUT_OF_SCOPE_KEYWORDS = [
    r"\bbất động sản\b", r"\bnhà đất\b", r"\bmua nhà\b", r"\bbán nhà\b",
    r"\bchứng khoán\b", r"\bcổ phiếu\b", r"\btrái phiếu\b", r"\btiền mã hóa\b",
    r"\bbitcoin\b", r"\bcrypto\b",
    r"\bdu lịch\b", r"\bkhách sạn\b", r"\bvé máy bay\b",
    r"\bthể thao\b.*\b(bóng đá|bóng rổ|tennis)\b",
    r"\bgiải trí\b", r"\bphim\b", r"\bnhạc\b", r"\bca sĩ\b",
    r"\btín dụng\b", r"\bvay vốn\b.*\b(ngân hàng|tín dụng)\b",
    r"\bgiá vàng\b", r"\btỷ giá\b",
    r"\bpháp luật\b", r"\bluật\b.*\b(hình sự|dân sự|hành chính)\b",
    r"\by tế\b.*\b(bệnh nhân|thuốc|bệnh viện)\b",
]

# ─── Từ khóa IoT / Farm sensor rõ ràng ──────────────────────────────────────
_IOT_KEYWORDS = [
    r"\bfarm_id\b", r"\bzone_id\b", r"\bsensor\b",
    r"\bđộ ẩm\b.*\bkhu\b", r"\bkhu\b.*\bđộ ẩm\b",
    r"\bkhu [A-Za-z]\b", r"\bzone [A-Za-z0-9]\b",
    r"\bnhiệt độ\b.*\bkhu\b", r"\bcảnh báo\b.*\bfarm\b",
    r"\blịch tưới\b.*\btự động\b", r"\bcảm biến\b",
]

# ─── Từ khóa nông nghiệp rõ ràng (để exclude câu quá ngắn/mơ hồ) ──────────
_AGRICULTURE_CONTEXT = [
    "lúa", "gạo", "ngô", "ngô", "cà phê", "tiêu", "điều", "dưa hấu",
    "dưa lưới", "sầu riêng", "cam", "bưởi", "xoài", "nhãn", "vải",
    "chuối", "rau", "cải", "bắp cải", "cà chua", "ớt", "hành", "tỏi",
    "khoai", "sắn", "mía", "lạc", "đậu", "bông", "thuốc lá",
    "phân bón", "thuốc bvtv", "thuốc trừ sâu", "thuốc diệt cỏ",
    "đất phù sa", "đất phèn", "đất mặn", "đất đỏ",
    "vụ đông xuân", "vụ hè thu", "vụ mùa", "canh tác", "gieo trồng",
    "thu hoạch", "bảo quản", "tưới tiêu", "phun thuốc",
    "sâu bệnh", "rầy nâu", "bọ trĩ", "nhện đỏ", "nấm bệnh",
    "đạo ôn", "khô vằn", "lem lép", "cháy lá",
]


def _compile_patterns(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


# Pre-compile patterns khi module load (1 lần duy nhất)
_QUANTITATIVE_RE = _compile_patterns(_QUANTITATIVE_KEYWORDS)
_RELATION_RE = _compile_patterns(_RELATION_KEYWORDS)
_EXPLANATION_RE = _compile_patterns(_EXPLANATION_KEYWORDS)
_OUT_OF_SCOPE_RE = _compile_patterns(_OUT_OF_SCOPE_KEYWORDS)
_IOT_RE = _compile_patterns(_IOT_KEYWORDS)


def _has_agriculture_context(text: str) -> bool:
    """Kiểm tra câu hỏi có ngữ cảnh nông nghiệp không (để tránh fast-path nhầm)."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in _AGRICULTURE_CONTEXT)


def _extract_topic_keywords(text: str) -> list[str]:
    """Trích từ khóa chủ đề đơn giản từ câu hỏi (không dùng NLP nặng)."""
    # Loại bỏ dấu câu và từ phổ biến
    stop_words = {"là", "gì", "thế", "nào", "có", "không", "và", "của", "để",
                  "cho", "với", "trong", "bao nhiêu", "như", "thế nào", "ở"}
    words = re.findall(r'\b\w{2,}\b', text.lower())
    return [w for w in words if w not in stop_words][:5]


def try_fast_path(
    question: str,
    history: Optional[list] = None,
    farm_id: Optional[str] = None,
    zone_id: Optional[str] = None,
) -> Optional[dict]:
    """
    Thử phân loại câu hỏi bằng rule-based (0 API call, <5ms).

    Returns:
        dict (routing result) nếu rule khớp với confidence cao
        None nếu không chắc → caller nên fallback sang Gemini

    Result format giống route_question() để tương thích:
        {
            "question_type": str,
            "crop": str | None,
            "season": str | None,
            "soil_type": str | None,
            "growth_stage": str | None,
            "variety": str | None,
            "topic_keywords": list,
            "confidence": "high",
            "clarification_question": None,
            "error": None,
            "decision_path": str,   # THÊM MỚI: audit trail
            "reason_code": str,     # THÊM MỚI: lý do route
        }
    """
    if not question or len(question.strip()) < 3:
        return None

    q = question.strip()
    keywords = _extract_topic_keywords(q)

    # SỬA LỖI (2026-09-06), lần 2: pattern IoT như \bkhu [A-Za-z]\b khớp cả
    # câu định lượng có nhắc tên khu (vd "...khu A"), khiến Layer 0 vẫn cướp
    # mất phân loại dù đã bỏ điều kiện farm_id đơn thuần. Sửa triệt để: kiểm
    # tra Out-of-scope/Quantitative/Relation/Explanation (ý định cụ thể)
    # TRƯỚC, IoT-keyword chỉ là lựa chọn khi không có ý định cụ thể nào khác.

    # ─── Layer 1: Ngoài phạm vi ──────────────────────────────────────────
    # Check trước để tránh false positive từ các layer sau
    for pattern in _OUT_OF_SCOPE_RE:
        if pattern.search(q):
            logger.debug(f"FastPath: Out-of-scope match")
            return {
                "question_type": "ngoài_phạm_vi",
                "crop": None, "season": None, "soil_type": None,
                "growth_stage": None, "variety": None,
                "topic_keywords": keywords,
                "confidence": "high",
                "clarification_question": None,
                "error": None,
                "decision_path": "fast_path → Layer1_OutOfScope",
                "reason_code": "OUT_OF_SCOPE_KEYWORD",
            }

    # ─── Layer 2: Định lượng ─────────────────────────────────────────────
    for pattern in _QUANTITATIVE_RE:
        if pattern.search(q):
            # Chỉ fast-path nếu có ngữ cảnh nông nghiệp rõ ràng
            if _has_agriculture_context(q) or len(q) > 15:
                logger.debug(f"FastPath: Quantitative match")
                return {
                    "question_type": "định_lượng",
                    "crop": _extract_crop(q),
                    "season": _extract_season_simple(q),
                    "soil_type": _extract_soil_simple(q),
                    "growth_stage": _extract_growth_stage_simple(q),
                    "variety": None,
                    "topic_keywords": keywords,
                    "confidence": "high",
                    "clarification_question": None,
                    "error": None,
                    "decision_path": "fast_path → Layer2_Quantitative",
                    "reason_code": "QUANTITATIVE_KEYWORD_MATCH",
                }

    # ─── Layer 3: Phù hợp / Quan hệ ──────────────────────────────────────
    for pattern in _RELATION_RE:
        if pattern.search(q):
            if _has_agriculture_context(q) or len(q) > 15:
                logger.debug(f"FastPath: Relation match")
                return {
                    "question_type": "phù_hợp/quan_hệ",
                    "crop": _extract_crop(q),
                    "season": _extract_season_simple(q),
                    "soil_type": _extract_soil_simple(q),
                    "growth_stage": None,
                    "variety": None,
                    "topic_keywords": keywords,
                    "confidence": "high",
                    "clarification_question": None,
                    "error": None,
                    "decision_path": "fast_path → Layer3_Relation",
                    "reason_code": "RELATION_KEYWORD_MATCH",
                }

    # ─── Layer 4: Diễn giải ──────────────────────────────────────────────
    for pattern in _EXPLANATION_RE:
        if pattern.search(q):
            if _has_agriculture_context(q):
                logger.debug(f"FastPath: Explanation match")
                return {
                    "question_type": "diễn_giải",
                    "crop": _extract_crop(q),
                    "season": _extract_season_simple(q),
                    "soil_type": _extract_soil_simple(q),
                    "growth_stage": None,
                    "variety": None,
                    "topic_keywords": keywords,
                    "confidence": "high",
                    "clarification_question": None,
                    "error": None,
                    "decision_path": "fast_path → Layer4_Explanation",
                    "reason_code": "EXPLANATION_KEYWORD_MATCH",
                }

    # ─── Layer 0 (giờ chạy sau cùng): IoT / Farm sensor ───────────────────
    # Chỉ fire khi KHÔNG có ý định cụ thể nào khác (định lượng/quan hệ/diễn
    # giải/ngoài phạm vi) đã khớp ở trên — tránh việc một câu định lượng có
    # nhắc tên khu (vd "khu A") bị cướp mất phân loại đúng.
    for pattern in _IOT_RE:
        if pattern.search(q):
            logger.debug(f"FastPath: IoT keyword match (farm_id={farm_id}, zone_id={zone_id})")
            return {
                "question_type": "diễn_giải",
                "crop": None, "season": None, "soil_type": None,
                "growth_stage": None, "variety": None,
                "topic_keywords": keywords,
                "confidence": "high",
                "clarification_question": None,
                "error": None,
                "decision_path": "fast_path → Layer0_IoT_Keyword",
                "reason_code": "IOT_KEYWORD_MATCH",
            }

    # farm_id/zone_id có mặt nhưng câu hỏi không khớp rule cụ thể nào và rất
    # ngắn/mơ hồ (vd "có gì mới không?") → coi là truy vấn tình trạng farm
    # chung chung thay vì bắt Gemini xử lý một câu gần như vô nghĩa.
    if (farm_id or zone_id) and not _has_agriculture_context(q) and len(q) <= 20:
        logger.debug(f"FastPath: bare farm context, no clear intent (farm_id={farm_id}, zone_id={zone_id})")
        return {
            "question_type": "diễn_giải",
            "crop": None, "season": None, "soil_type": None,
            "growth_stage": None, "variety": None,
            "topic_keywords": keywords,
            "confidence": "high",
            "clarification_question": None,
            "error": None,
            "decision_path": "fast_path → Layer0_IoT_FarmContext",
            "reason_code": "FARM_CONTEXT_PRESENT_NO_SPECIFIC_INTENT",
        }

    # ─── Không khớp rule nào → fallback Gemini ───────────────────────────
    logger.debug(f"FastPath: No rule matched → fallback to Gemini")
    return None


# ─── Helper extractors (đơn giản, không NLP nặng) ────────────────────────────

_CROP_MAP = {
    "lúa": "lúa", "gạo": "lúa",
    "cà phê": "cà phê", "cafe": "cà phê",
    "tiêu": "hồ tiêu", "hồ tiêu": "hồ tiêu",
    "điều": "điều",
    "dưa hấu": "dưa hấu", "dưa lưới": "dưa lưới",
    "sầu riêng": "sầu riêng",
    "cam": "cam", "bưởi": "bưởi", "xoài": "xoài",
    "nhãn": "nhãn", "vải": "vải", "chuối": "chuối",
    "cà chua": "cà chua", "ớt": "ớt", "hành": "hành",
    "khoai lang": "khoai lang", "khoai tây": "khoai tây",
    "sắn": "sắn", "mía": "mía", "ngô": "ngô", "bắp": "ngô",
    "đậu nành": "đậu nành", "lạc": "lạc",
    "rau muống": "rau muống", "rau cải": "rau cải",
}

_SEASON_RE = {
    "đông xuân": "Đông Xuân", "dong xuan": "Đông Xuân",
    "hè thu": "Hè Thu", "he thu": "Hè Thu",
    r"vụ mùa\b": "Mùa",
}

_SOIL_MAP = {
    "phù sa": "phù sa",
    "phèn nhẹ": "phèn nhẹ", "phèn trung": "phèn trung bình",
    "phèn nặng": "phèn nặng", "phèn": "phèn nhẹ",
    "mặn": "mặn",
    "đất đỏ": "đất đỏ",
}

_GROWTH_STAGE_MAP = {
    "mạ": "mạ", "giai đoạn mạ": "mạ",
    "đẻ nhánh": "đẻ_nhánh", "đẻ nhành": "đẻ_nhánh",
    "làm đòng": "làm_đòng",
    "trổ bông": "trổ_bông", "ra bông": "trổ_bông",
    "chín": "chín", "thu hoạch": "chín",
}


def _extract_crop(text: str) -> Optional[str]:
    text_lower = text.lower()
    for keyword, crop_name in _CROP_MAP.items():
        if keyword in text_lower:
            return crop_name
    return None


def _extract_season_simple(text: str) -> Optional[str]:
    text_lower = text.lower()
    for keyword, season_name in _SEASON_RE.items():
        if re.search(keyword, text_lower):
            return season_name
    return None


def _extract_soil_simple(text: str) -> Optional[str]:
    text_lower = text.lower()
    for keyword, soil_name in _SOIL_MAP.items():
        if keyword in text_lower:
            return soil_name
    return None


def _extract_growth_stage_simple(text: str) -> Optional[str]:
    text_lower = text.lower()
    for keyword, stage_name in _GROWTH_STAGE_MAP.items():
        if keyword in text_lower:
            return stage_name
    return None