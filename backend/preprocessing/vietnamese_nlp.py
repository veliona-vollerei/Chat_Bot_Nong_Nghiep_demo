"""
Xử lý tiếng Việt nông nghiệp.

Pipeline: raw_input → chuẩn hóa không dấu → tra từ điển → normalized_input
"""
import re
import logging
from typing import Optional
from backend.db.postgres import get_cursor

logger = logging.getLogger(__name__)

# Cache từ điển (load 1 lần từ DB)
_term_dict: dict = {}
_term_dict_loaded = False


def load_term_dict():
    """Load từ điển chuẩn hóa từ PostgreSQL vào memory."""
    global _term_dict, _term_dict_loaded
    if _term_dict_loaded:
        return
    try:
        with get_cursor() as cur:
            cur.execute("SELECT raw_term, normalized_term FROM term_normalization")
            rows = cur.fetchall()
            _term_dict = {r["raw_term"].lower(): r["normalized_term"] for r in rows}
        _term_dict_loaded = True
        logger.info(f"Loaded {len(_term_dict)} terms from DB")
    except Exception as e:
        logger.warning(f"Không load được từ điển từ DB, dùng fallback: {e}")
        _term_dict = _FALLBACK_TERM_DICT
        _term_dict_loaded = True


def normalize_input(text: str) -> dict:
    """
    Chuẩn hóa câu hỏi đầu vào.
    
    Returns:
        {
            "original": str,
            "normalized": str,       # Sau khi chuẩn hóa
            "detected_terms": list,  # Thuật ngữ đã nhận dạng
        }
    """
    load_term_dict()
    
    original = text.strip()
    normalized = text.strip().lower()
    
    # Bước 1: Normalize whitespace
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    
    # Bước 2: Tra từ điển (từ dài nhất trước)
    detected_terms = []
    sorted_terms = sorted(_term_dict.keys(), key=len, reverse=True)
    
    working_text = normalized
    for raw_term in sorted_terms:
        if raw_term in working_text:
            canonical = _term_dict[raw_term]
            if canonical not in detected_terms:
                detected_terms.append(canonical)
            # Thay thế trong text
            working_text = working_text.replace(raw_term, canonical)
    
    normalized = working_text
    
    return {
        "original": original,
        "normalized": normalized,
        "detected_terms": detected_terms,
    }


def extract_season(text: str) -> Optional[str]:
    """Nhận dạng mùa vụ từ text."""
    text_lower = text.lower()
    if any(k in text_lower for k in ["đông xuân", "dong xuan", " dx ", "chiêm", "chiem", "vụ xuân", "vu xuan"]):
        return "Đông Xuân"
    if any(k in text_lower for k in ["hè thu", "he thu", "vụ hè", "vu he"]):
        return "Hè Thu"
    if any(k in text_lower for k in ["vụ mùa", "vu mua", "mùa lũ", "mua lu"]):
        return "Mùa"
    return None


def extract_soil_type(text: str) -> Optional[str]:
    """Nhận dạng loại đất từ text."""
    text_lower = text.lower()
    if any(k in text_lower for k in ["phèn nặng", "phen nang"]):
        return "phèn nặng"
    if any(k in text_lower for k in ["phèn trung", "phen trung", "phèn vừa"]):
        return "phèn trung bình"
    if any(k in text_lower for k in ["phèn nhẹ", "phen nhe"]):
        return "phèn nhẹ"
    if any(k in text_lower for k in ["phù sa", "phu sa", "đất phù"]):
        return "phù sa"
    if any(k in text_lower for k in ["mặn", "man"]):
        return "mặn"
    return None


def extract_variety_name(text: str) -> Optional[str]:
    """Nhận dạng tên giống lúa từ text."""
    text_upper = text.upper()
    known_varieties = ["OM380", "IR50404", "OM34", "P6"]
    for v in known_varieties:
        if v in text_upper:
            return v
    return None


# === Fallback dictionary (khi DB chưa sẵn sàng) ===
_FALLBACK_TERM_DICT = {
    "awd": "tưới ướt khô xen kẽ (AWD)",
    "dam": "phân đạm",
    "ure": "phân đạm (urê)",
    "phan dam": "phân đạm",
    "kali": "phân kali",
    "lan": "phân lân",
    "dao on": "bệnh đạo ôn",
    "ray nau": "rầy nâu",
    "ray": "rầy nâu",
    "nss": "ngày sau sạ (NSS)",
    "bđkh": "biến đổi khí hậu",
    "knk": "khí nhà kính",
    "ipm": "quản lý dịch hại tổng hợp (IPM)",
    "3 giam 3 tang": "3 giảm 3 tăng",
    "1 phai 5 giam": "1 phải 5 giảm",
}


# === Tập câu hỏi mô phỏng nông dân (50+ câu) ===
SAMPLE_QUESTIONS = [
    # Phân bón (định lượng → Tầng 1)
    "bon phan thuc dot may bao nhieu kg",
    "lua dong xuan dat phu sa bon bao nhieu dam",
    "dat phen bon phan nhu the nao",
    "bao nhieu kg ure tren 1 ha lua",
    "bon phan dot may bon may lan",
    "lua dot bao nhieu kali",
    # AWD / Quản lý nước (diễn giải → Tầng 3)
    "AWD la gi",
    "tuoi uot kho xen ke la sao",
    "rut nuoc giua vu nhu the nao",
    "khi nao thi rut nuoc truoc khi gat",
    "muc nuoc trong ong bao nhieu thi tuoi lai",
    "lua bi kho han phai lam gi",
    # Giống lúa (phù hợp/quan hệ → Tầng 2)
    "giong OM380 co phu hop dat phen khong",
    "dat phen trong giong gi",
    "giong lua nao ngan ngay nhat",
    "IR50404 co de bi benh dao on khong",
    "P6 dot bien trong duoc vu gi",
    "giong OM34 nang suat bao nhieu",
    # Sâu bệnh
    "lua bi vang la phai lam sao",
    "benh dao on xuat hien khi nao",
    "ray nau la gi",
    "lua bi chay ray xu ly nhu the nao",
    "sau duc than lua co trieu chung gi",
    "phong tru sau benh theo IPM",
    # Kỹ thuật canh tác
    "3 giam 3 tang la gi",
    "1 phai 5 giam la gi",
    "sa may ket hop vui phan giam duoc bao nhieu dam",
    "mat do sa lua bao nhieu kg tren ha",
    "lua canh tac theo phuong phap nao giam phat thai",
    "khi nao bon phan dot 1 dot 2 dot 3",
    # Hệ số phát thải (định lượng → Tầng 1)
    "he so SFp la gi",
    "ngap truoc vu thi he so phat thai la bao nhieu",
    "rut nuoc giua vu giam duoc bao nhieu phat thai",
    "AWD giam bao nhieu phan tram khi nha kinh",
    # Ngoài phạm vi (bot từ chối)
    "ca phe trong nhu the nao",
    "trong ca chua o mien bac",
    "gia lua hien nay la bao nhieu",
    "ngan hang cho vay voi khi nao",
]
