"""
Similarity Threshold Calibration — Mục 7 GĐ1.

Tool để đo và hiệu chỉnh ngưỡng similarity trong ChromaDB retrieval:
- Baseline ngưỡng hiện tại: SIMILARITY_THRESHOLD trong config
- Chạy test queries và đo Precision@K, Recall@K
- Vẽ Precision-Recall curve theo từng ngưỡng (0.3 → 0.9)
- Xuất recommendation ngưỡng tối ưu

Tại sao cần:
- Ngưỡng quá thấp → trả về chunk không liên quan (noise)
- Ngưỡng quá cao → bỏ sót chunk đúng (miss)
- Cần hiệu chỉnh theo corpus thực tế của hệ thống

Chạy:
    python -m backend.retrieval.threshold_calibration
    python -m backend.retrieval.threshold_calibration --threshold 0.7

Output:
    - Bảng Precision/Recall theo từng ngưỡng
    - Recommendation ngưỡng F1-optimal
    - File calibration_results.json
"""
import json
import time
import logging
import argparse
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# Ngưỡng mặc định hiện tại của hệ thống
CURRENT_SIMILARITY_THRESHOLD = 0.6

# Dải thử nghiệm
THRESHOLD_RANGE = [0.30, 0.40, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]

# Top-K để đo
TOP_K = [1, 3, 5, 10]

# File lưu kết quả calibration
CALIBRATION_FILE = Path(__file__).parent.parent.parent / "calibration_results.json"


# ─── Test Query Set (ground truth) ────────────────────────────────────────

# Mỗi test case: {query, expected_keywords, min_expected_matches}
# expected_keywords: từ nào PHẢI xuất hiện trong kết quả tốt
DEFAULT_TEST_QUERIES = [
    # ─── Nhóm Lúa (8 câu) ─────────────────────────────────────────────────────
    {
        "query": "lượng phân đạm cho lúa đông xuân",
        "expected_keywords": ["phân đạm", "đạm", "lúa", "đông xuân", "urê"],
        "min_expected_matches": 1,
        "category": "định_lượng",
    },
    {
        "query": "giống lúa phù hợp đất phèn nhẹ vùng đồng bằng sông cửu long",
        "expected_keywords": ["phèn", "giống", "đồng bằng", "IR64", "OM"],
        "min_expected_matches": 1,
        "category": "phù_hợp/quan_hệ",
    },
    {
        "query": "cách xử lý rầy nâu hại lúa",
        "expected_keywords": ["rầy nâu", "thuốc", "phòng trừ", "thiên địch"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    {
        "query": "lịch bón phân cho lúa hè thu miền nam",
        "expected_keywords": ["hè thu", "bón phân", "lúa", "đạm", "kali"],
        "min_expected_matches": 1,
        "category": "định_lượng",
    },
    {
        "query": "kỹ thuật sạ cụm lúa giảm giống",
        "expected_keywords": ["sạ cụm", "giống", "lúa", "mật độ"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    {
        "query": "cách phòng bệnh đạo ôn trên lúa",
        "expected_keywords": ["đạo ôn", "bệnh", "lúa", "thuốc", "phun"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    {
        "query": "lượng nước tưới cho lúa giai đoạn đẻ nhánh",
        "expected_keywords": ["tưới", "lúa", "đẻ nhánh", "nước"],
        "min_expected_matches": 1,
        "category": "định_lượng",
    },
    {
        "query": "năng suất lúa OM5451 vụ đông xuân đồng bằng sông cửu long",
        "expected_keywords": ["OM5451", "năng suất", "lúa", "đông xuân"],
        "min_expected_matches": 1,
        "category": "định_lượng",
    },
    # ─── Nhóm Sầu Riêng (5 câu) ───────────────────────────────────────────────
    {
        "query": "kỹ thuật xử lý ra hoa sầu riêng mùa nghịch",
        "expected_keywords": ["sầu riêng", "ra hoa", "xử lý", "mùa nghịch"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    {
        "query": "liều lượng phân bón NPK cho sầu riêng giai đoạn nuôi trái",
        "expected_keywords": ["sầu riêng", "phân bón", "NPK", "nuôi trái"],
        "min_expected_matches": 1,
        "category": "định_lượng",
    },
    {
        "query": "cách phòng trừ bệnh thối rễ sầu riêng",
        "expected_keywords": ["sầu riêng", "thối rễ", "bệnh", "phun", "thuốc"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    {
        "query": "giống sầu riêng Ri6 hay Monthong phù hợp Đắk Lắk",
        "expected_keywords": ["sầu riêng", "Ri6", "Monthong", "giống"],
        "min_expected_matches": 1,
        "category": "phù_hợp/quan_hệ",
    },
    {
        "query": "kỹ thuật tỉa cành tạo tán sầu riêng năm đầu",
        "expected_keywords": ["sầu riêng", "tỉa cành", "tạo tán"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    # ─── Nhóm Cà Phê / Tiêu / Điều (4 câu) ───────────────────────────────────
    {
        "query": "quy trình canh tác cà phê robusta",
        "expected_keywords": ["cà phê", "robusta", "canh tác"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    {
        "query": "bón phân cho cà phê vối giai đoạn kinh doanh",
        "expected_keywords": ["cà phê", "bón phân", "kinh doanh", "đạm"],
        "min_expected_matches": 1,
        "category": "định_lượng",
    },
    {
        "query": "phòng trừ bệnh chết nhanh chết chậm trên hồ tiêu",
        "expected_keywords": ["hồ tiêu", "chết nhanh", "bệnh", "nấm", "phòng trừ"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    {
        "query": "kỹ thuật trồng và chăm sóc điều năng suất cao",
        "expected_keywords": ["điều", "trồng", "chăm sóc", "năng suất"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    # ─── Nhóm Rau Màu / Dưa Hấu / Ngô (5 câu) ────────────────────────────────
    {
        "query": "kỹ thuật bón phân cho dưa hấu",
        "expected_keywords": ["dưa hấu", "phân bón", "NPK"],
        "min_expected_matches": 1,
        "category": "định_lượng",
    },
    {
        "query": "cách phòng bệnh sương mai trên cà chua",
        "expected_keywords": ["cà chua", "sương mai", "bệnh", "thuốc"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    {
        "query": "lịch tưới nước cho rau cải xanh mùa khô",
        "expected_keywords": ["rau cải", "tưới nước", "mùa khô"],
        "min_expected_matches": 1,
        "category": "định_lượng",
    },
    {
        "query": "bón phân urê cho ngô giai đoạn xoáy nõn",
        "expected_keywords": ["ngô", "urê", "xoáy nõn", "bón phân"],
        "min_expected_matches": 1,
        "category": "định_lượng",
    },
    {
        "query": "mật độ trồng dưa hấu trên đất cát ven biển",
        "expected_keywords": ["dưa hấu", "mật độ", "trồng", "đất cát"],
        "min_expected_matches": 1,
        "category": "định_lượng",
    },
    # ─── Nhóm Phòng Trừ Sâu Bệnh Chung (5 câu) ───────────────────────────────
    {
        "query": "ngưỡng phun thuốc trừ sâu cuốn lá nhỏ trên lúa",
        "expected_keywords": ["sâu cuốn lá", "ngưỡng", "phun thuốc", "lúa"],
        "min_expected_matches": 1,
        "category": "định_lượng",
    },
    {
        "query": "cách sử dụng bẫy dính vàng để quản lý bọ trĩ",
        "expected_keywords": ["bọ trĩ", "bẫy dính", "quản lý"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    {
        "query": "thuốc trừ nấm gốc đồng phòng bệnh phytophthora trên cây có múi",
        "expected_keywords": ["đồng", "nấm", "phytophthora", "cây có múi", "thuốc"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    {
        "query": "thời điểm phun thuốc trừ sâu tốt nhất trong ngày",
        "expected_keywords": ["phun thuốc", "thời điểm", "sáng sớm", "chiều mát"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    {
        "query": "liều lượng dung dịch boron bổ sung cho cây ăn trái ra hoa",
        "expected_keywords": ["boron", "ra hoa", "cây ăn trái", "phun"],
        "min_expected_matches": 1,
        "category": "định_lượng",
    },
    # ─── Negative test cases — không nên trả về kết quả nông nghiệp (4 câu) ───
    {
        "query": "hướng dẫn đầu tư chứng khoán",
        "expected_keywords": [],
        "min_expected_matches": 0,
        "category": "negative",
        "is_negative": True,
    },
    {
        "query": "cách sửa điện thoại samsung bị vỡ màn hình",
        "expected_keywords": [],
        "min_expected_matches": 0,
        "category": "negative",
        "is_negative": True,
    },
    {
        "query": "công thức toán học tích phân bất định",
        "expected_keywords": [],
        "min_expected_matches": 0,
        "category": "negative",
        "is_negative": True,
    },
    {
        "query": "hướng dẫn nấu phở bò truyền thống hà nội",
        "expected_keywords": [],
        "min_expected_matches": 0,
        "category": "negative",
        "is_negative": True,
    },
    # ─────────────────────────────────────────────────────────────────────────
    # MỞ RỘNG v2 — thêm ~42 câu đưa tổng từ 31 → 73 câu (Mục 8)
    # ─────────────────────────────────────────────────────────────────────────

    # ─── Sầu Riêng bổ sung (8 câu) ───────────────────────────────────────────
    {
        "query": "lượng phân kali bón cho sầu riêng trước thu hoạch",
        "expected_keywords": ["sầu riêng", "kali", "bón phân", "thu hoạch"],
        "min_expected_matches": 1,
        "category": "định_lượng",
    },
    {
        "query": "kỹ thuật tưới nước cho sầu riêng mùa khô tây nguyên",
        "expected_keywords": ["sầu riêng", "tưới nước", "mùa khô", "Tây Nguyên"],
        "min_expected_matches": 1,
        "category": "định_lượng",
    },
    {
        "query": "cách phòng trị sâu đục trái sầu riêng",
        "expected_keywords": ["sầu riêng", "sâu đục trái", "phòng trị", "thuốc"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    {
        "query": "biểu hiện bệnh xì mủ thân cành sầu riêng và cách xử lý",
        "expected_keywords": ["sầu riêng", "xì mủ", "bệnh", "xử lý"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    {
        "query": "thời gian từ ra hoa đến thu hoạch sầu riêng Monthong",
        "expected_keywords": ["sầu riêng", "Monthong", "ra hoa", "thu hoạch"],
        "min_expected_matches": 1,
        "category": "định_lượng",
    },
    {
        "query": "mật độ trồng sầu riêng trên đất đỏ bazan",
        "expected_keywords": ["sầu riêng", "mật độ", "trồng", "đất đỏ", "bazan"],
        "min_expected_matches": 1,
        "category": "định_lượng",
    },
    {
        "query": "cách xử lý sầu riêng ra hoa đồng loạt bằng kali chlorate",
        "expected_keywords": ["sầu riêng", "kali chlorate", "ra hoa", "xử lý"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    {
        "query": "triệu chứng thiếu canxi magiê trên sầu riêng",
        "expected_keywords": ["sầu riêng", "canxi", "magiê", "thiếu", "lá"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    # ─── Cà Phê bổ sung (6 câu) ───────────────────────────────────────────────
    {
        "query": "lượng phân đạm bón cho cà phê giai đoạn nuôi trái",
        "expected_keywords": ["cà phê", "đạm", "bón phân", "nuôi trái"],
        "min_expected_matches": 1,
        "category": "định_lượng",
    },
    {
        "query": "cách phòng trừ bệnh gỉ sắt trên cà phê",
        "expected_keywords": ["cà phê", "gỉ sắt", "bệnh", "thuốc", "phun"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    {
        "query": "giống cà phê arabica phù hợp trồng ở độ cao bao nhiêu",
        "expected_keywords": ["cà phê", "arabica", "độ cao", "giống"],
        "min_expected_matches": 1,
        "category": "phù_hợp/quan_hệ",
    },
    {
        "query": "kỹ thuật tạo bóng mát cho vườn cà phê",
        "expected_keywords": ["cà phê", "bóng mát", "cây che bóng", "tạo bóng"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    {
        "query": "lịch tưới nước cho cà phê mùa khô tại Đắk Lắk",
        "expected_keywords": ["cà phê", "tưới nước", "mùa khô", "Đắk Lắk"],
        "min_expected_matches": 1,
        "category": "định_lượng",
    },
    {
        "query": "cà phê robusta hay arabica phù hợp đất bazan Tây Nguyên",
        "expected_keywords": ["cà phê", "robusta", "arabica", "bazan", "Tây Nguyên"],
        "min_expected_matches": 1,
        "category": "phù_hợp/quan_hệ",
    },
    # ─── Hồ Tiêu bổ sung (5 câu) ──────────────────────────────────────────────
    {
        "query": "liều lượng phân hữu cơ bón cho tiêu kinh doanh",
        "expected_keywords": ["tiêu", "hồ tiêu", "phân hữu cơ", "bón", "kinh doanh"],
        "min_expected_matches": 1,
        "category": "định_lượng",
    },
    {
        "query": "cách nhận biết và trị bệnh tuyến trùng hại rễ tiêu",
        "expected_keywords": ["hồ tiêu", "tiêu", "tuyến trùng", "rễ", "bệnh"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    {
        "query": "kỹ thuật trồng tiêu trụ sống tiết kiệm chi phí",
        "expected_keywords": ["tiêu", "hồ tiêu", "trụ sống", "trồng", "kỹ thuật"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    {
        "query": "mật độ trồng hồ tiêu leo trụ gỗ",
        "expected_keywords": ["hồ tiêu", "tiêu", "mật độ", "trụ gỗ"],
        "min_expected_matches": 1,
        "category": "định_lượng",
    },
    {
        "query": "phun thuốc gì để phòng ngừa nấm Phytophthora trên tiêu",
        "expected_keywords": ["tiêu", "hồ tiêu", "Phytophthora", "nấm", "phun thuốc"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    # ─── Điều bổ sung (4 câu) ─────────────────────────────────────────────────
    {
        "query": "lượng phân NPK bón cho điều kinh doanh mỗi năm",
        "expected_keywords": ["điều", "NPK", "bón phân", "kinh doanh"],
        "min_expected_matches": 1,
        "category": "định_lượng",
    },
    {
        "query": "phòng trừ bọ xít muỗi hại điều",
        "expected_keywords": ["điều", "bọ xít muỗi", "phòng trừ", "thuốc"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    {
        "query": "giống điều năng suất cao phù hợp Bình Phước",
        "expected_keywords": ["điều", "giống", "năng suất", "Bình Phước"],
        "min_expected_matches": 1,
        "category": "phù_hợp/quan_hệ",
    },
    {
        "query": "kỹ thuật ghép cải tạo vườn điều già cỗi",
        "expected_keywords": ["điều", "ghép", "cải tạo", "già cỗi"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    # ─── Rau màu / Dưa hấu / Ngô bổ sung (6 câu) ─────────────────────────────
    {
        "query": "lượng phân bón cho dưa hấu giai đoạn phình trái",
        "expected_keywords": ["dưa hấu", "phân bón", "phình trái"],
        "min_expected_matches": 1,
        "category": "định_lượng",
    },
    {
        "query": "cách quản lý bệnh héo xanh vi khuẩn trên ớt",
        "expected_keywords": ["ớt", "héo xanh", "vi khuẩn", "bệnh"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    {
        "query": "mật độ gieo ngô lai trên đất thịt nhẹ",
        "expected_keywords": ["ngô", "mật độ", "gieo", "đất thịt"],
        "min_expected_matches": 1,
        "category": "định_lượng",
    },
    {
        "query": "kỹ thuật trồng rau muống nước ao",
        "expected_keywords": ["rau muống", "nước", "trồng", "ao"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    {
        "query": "phòng bệnh đốm lá trên bắp cải",
        "expected_keywords": ["bắp cải", "đốm lá", "bệnh", "phòng"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    {
        "query": "khoảng cách hàng và cây khi trồng ngô ngọt",
        "expected_keywords": ["ngô ngọt", "khoảng cách", "trồng", "hàng"],
        "min_expected_matches": 1,
        "category": "định_lượng",
    },
    # ─── Câu mơ hồ / dễ lẫn nguồn (8 câu) ────────────────────────────────────
    # Mục tiêu: test RAG không "vơ" nhầm tài liệu lúa khi hỏi về sầu riêng
    {
        "query": "cây bị vàng lá và rụng trái hàng loạt phải làm gì",
        "expected_keywords": ["vàng lá", "rụng trái", "bệnh", "nguyên nhân"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    {
        "query": "phân nào giúp cây ra nhiều bông hơn",
        "expected_keywords": ["phân", "ra hoa", "bông", "kali", "lân"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    {
        "query": "cây ăn trái bị nấm thối gốc xử lý thế nào",
        "expected_keywords": ["nấm", "thối gốc", "cây ăn trái", "xử lý", "thuốc"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    {
        "query": "lượng nước tưới cho cây trong mùa khô",
        "expected_keywords": ["tưới", "nước", "mùa khô"],
        "min_expected_matches": 1,
        "category": "định_lượng",
    },
    {
        "query": "cần bón thêm loại phân gì khi đất bị chua",
        "expected_keywords": ["đất chua", "phân", "vôi", "pH"],
        "min_expected_matches": 1,
        "category": "phù_hợp/quan_hệ",
    },
    {
        "query": "sâu nào thường phá hại nhất trong vụ xuân",
        "expected_keywords": ["sâu", "vụ xuân", "phá hại", "phòng trừ"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    {
        "query": "kỹ thuật bón phân sau thu hoạch để phục hồi cây",
        "expected_keywords": ["bón phân", "thu hoạch", "phục hồi"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    {
        "query": "làm sao biết cây đủ dinh dưỡng hay đang thiếu phân",
        "expected_keywords": ["dinh dưỡng", "thiếu phân", "lá", "biểu hiện"],
        "min_expected_matches": 1,
        "category": "diễn_giải",
    },
    # ─── Negative bổ sung — ngoài phạm vi nông nghiệp (5 câu) ────────────────
    {
        "query": "hướng dẫn lập trình python từ cơ bản đến nâng cao",
        "expected_keywords": [],
        "min_expected_matches": 0,
        "category": "negative",
        "is_negative": True,
    },
    {
        "query": "cách đăng ký tài khoản ngân hàng online",
        "expected_keywords": [],
        "min_expected_matches": 0,
        "category": "negative",
        "is_negative": True,
    },
    {
        "query": "lịch thi đấu bóng đá ngoại hạng anh tuần này",
        "expected_keywords": [],
        "min_expected_matches": 0,
        "category": "negative",
        "is_negative": True,
    },
    {
        "query": "cách nấu bún bò huế thơm ngon",
        "expected_keywords": [],
        "min_expected_matches": 0,
        "category": "negative",
        "is_negative": True,
    },
    {
        "query": "hướng dẫn lái xe ô tô cho người mới bắt đầu",
        "expected_keywords": [],
        "min_expected_matches": 0,
        "category": "negative",
        "is_negative": True,
    },
]



# ─── Retrieval & Scoring ──────────────────────────────────────────────────

def _embed_query(query: str) -> Optional[list[float]]:
    """Embed query bằng embedding model hiện tại."""
    try:
        from backend.layers.layer3_docs import _get_embedding_model
        model = _get_embedding_model()
        embedding = model.encode(
            f"query: {query}",
            normalize_embeddings=True,
        ).tolist()
        return embedding
    except Exception as e:
        logger.error(f"Embed error: {e}")
        return None


def _retrieve_with_threshold(
    query_embedding: list[float],
    threshold: float,
    top_k: int = 10,
) -> list[dict]:
    """Retrieve từ ChromaDB với ngưỡng similarity cụ thể."""
    try:
        from backend.db.chroma_db import get_collection
        collection = get_collection()

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        filtered = []
        for doc, meta, dist in zip(docs, metas, distances):
            # ChromaDB dùng cosine distance: similarity = 1 - distance
            similarity = 1.0 - dist
            if similarity >= threshold:
                filtered.append({
                    "text": doc,
                    "meta": meta,
                    "similarity": round(similarity, 4),
                })

        return filtered

    except Exception as e:
        logger.error(f"Retrieve error: {e}")
        return []


def _score_results(
    results: list[dict],
    expected_keywords: list[str],
    is_negative: bool = False,
) -> dict:
    """
    Tính Precision và Recall cho kết quả retrieval.

    Relevant = chunk chứa ít nhất 1 keyword expected.

    Returns:
        {"precision": float, "recall": float, "f1": float, "n_relevant": int}
    """
    if not results:
        return {
            "precision": 1.0 if is_negative else 0.0,  # True negative
            "recall": 0.0,
            "f1": 0.0,
            "n_relevant": 0,
            "n_results": 0,
        }

    if is_negative or not expected_keywords:
        # Với negative test: không mong đợi kết quả nào
        return {
            "precision": 0.0,  # Bất kỳ kết quả nào đều là false positive
            "recall": 0.0,
            "f1": 0.0,
            "n_relevant": 0,
            "n_results": len(results),
        }

    n_relevant = 0
    for r in results:
        text_lower = (r["text"] or "").lower()
        if any(kw.lower() in text_lower for kw in expected_keywords):
            n_relevant += 1

    precision = n_relevant / len(results) if results else 0.0
    recall = min(1.0, n_relevant / max(1, len(expected_keywords)))
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    return {
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "n_relevant": n_relevant,
        "n_results": len(results),
    }


def run_calibration(
    test_queries: Optional[list[dict]] = None,
    thresholds: Optional[list[float]] = None,
    top_k: int = 5,
    save_results: bool = True,
) -> dict:
    """
    Chạy calibration trên toàn bộ test query set.

    Returns:
        {
            "per_threshold": { threshold: { avg_precision, avg_recall, avg_f1, ... } },
            "optimal_threshold": float,
            "optimal_f1": float,
            "recommendation": str
        }
    """
    if test_queries is None:
        test_queries = DEFAULT_TEST_QUERIES
    if thresholds is None:
        thresholds = THRESHOLD_RANGE

    logger.info(f"Calibration: {len(test_queries)} queries × {len(thresholds)} thresholds")

    # Pre-compute embeddings
    print("🔍 Đang tạo embeddings cho test queries...")
    embeddings = []
    for q in test_queries:
        emb = _embed_query(q["query"])
        embeddings.append(emb)
        print(f"  ✓ [{q['category']}] {q['query'][:50]}...")

    per_threshold: dict[str, dict] = {}

    for threshold in thresholds:
        all_precision = []
        all_recall = []
        all_f1 = []
        query_results = []

        for i, (q, emb) in enumerate(zip(test_queries, embeddings)):
            if emb is None:
                continue

            t0 = time.time()
            results = _retrieve_with_threshold(emb, threshold, top_k)
            latency_ms = (time.time() - t0) * 1000

            scores = _score_results(
                results,
                q["expected_keywords"],
                q.get("is_negative", False),
            )

            query_results.append({
                "query": q["query"],
                "category": q["category"],
                "n_results": scores["n_results"],
                "n_relevant": scores["n_relevant"],
                "precision": scores["precision"],
                "recall": scores["recall"],
                "f1": scores["f1"],
                "latency_ms": round(latency_ms, 1),
            })

            if not q.get("is_negative"):
                all_precision.append(scores["precision"])
                all_recall.append(scores["recall"])
                all_f1.append(scores["f1"])

        avg_p = sum(all_precision) / len(all_precision) if all_precision else 0
        avg_r = sum(all_recall) / len(all_recall) if all_recall else 0
        avg_f1 = sum(all_f1) / len(all_f1) if all_f1 else 0

        per_threshold[str(threshold)] = {
            "avg_precision": round(avg_p, 3),
            "avg_recall": round(avg_r, 3),
            "avg_f1": round(avg_f1, 3),
            "queries": query_results,
        }

        print(
            f"  threshold={threshold:.2f}: "
            f"P={avg_p:.3f} R={avg_r:.3f} F1={avg_f1:.3f}"
        )

    # Tìm threshold tối ưu (F1 cao nhất)
    optimal_threshold = max(
        per_threshold.keys(),
        key=lambda t: per_threshold[t]["avg_f1"]
    )
    optimal_f1 = per_threshold[optimal_threshold]["avg_f1"]
    optimal_threshold_float = float(optimal_threshold)

    # Recommendation
    if optimal_threshold_float != CURRENT_SIMILARITY_THRESHOLD:
        diff = optimal_threshold_float - CURRENT_SIMILARITY_THRESHOLD
        direction = "tăng" if diff > 0 else "giảm"
        rec = (
            f"Đề xuất {direction} threshold từ {CURRENT_SIMILARITY_THRESHOLD} "
            f"→ {optimal_threshold_float} (F1 optimal: {optimal_f1:.3f}). "
            f"Cập nhật SIMILARITY_THRESHOLD trong backend/config.py"
        )
    else:
        rec = (
            f"Threshold hiện tại ({CURRENT_SIMILARITY_THRESHOLD}) đã là tối ưu "
            f"(F1={optimal_f1:.3f}). Không cần thay đổi."
        )

    output = {
        "current_threshold": CURRENT_SIMILARITY_THRESHOLD,
        "optimal_threshold": optimal_threshold_float,
        "optimal_f1": optimal_f1,
        "recommendation": rec,
        "per_threshold": per_threshold,
        "top_k_used": top_k,
        "n_test_queries": len(test_queries),
        "generated_at": __import__("datetime").datetime.now().isoformat(),
    }

    if save_results:
        CALIBRATION_FILE.write_text(
            json.dumps(output, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print(f"\n💾 Đã lưu kết quả vào {CALIBRATION_FILE}")

    return output


def print_calibration_summary(results: dict):
    """In tóm tắt kết quả calibration."""
    print(f"\n{'='*60}")
    print("📊 Similarity Threshold Calibration Summary")
    print(f"{'='*60}")
    print(f"  Threshold hiện tại : {results['current_threshold']}")
    print(f"  Threshold tối ưu   : {results['optimal_threshold']}")
    print(f"  F1 tối ưu          : {results['optimal_f1']:.3f}")
    print()
    print(f"  {'Threshold':<12} {'Precision':<12} {'Recall':<12} {'F1':<10}")
    print(f"  {'-'*46}")
    for t, v in sorted(results["per_threshold"].items(), key=lambda x: float(x[0])):
        marker = " ◄ OPTIMAL" if float(t) == results["optimal_threshold"] else ""
        current = " ◄ CURRENT" if float(t) == results["current_threshold"] else ""
        print(
            f"  {float(t):<12.2f} "
            f"{v['avg_precision']:<12.3f} "
            f"{v['avg_recall']:<12.3f} "
            f"{v['avg_f1']:<10.3f}"
            f"{marker}{current}"
        )
    print()
    print(f"🎯 {results['recommendation']}")
    print()


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

    parser = argparse.ArgumentParser(description="Similarity Threshold Calibration")
    parser.add_argument("--threshold", type=float, help="Test single threshold value")
    parser.add_argument("--top_k", type=int, default=5, help="Top-K for retrieval")
    parser.add_argument("--no_save", action="store_true", help="Không lưu kết quả")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)

    if args.threshold:
        thresholds = [args.threshold]
    else:
        thresholds = THRESHOLD_RANGE

    results = run_calibration(
        thresholds=thresholds,
        top_k=args.top_k,
        save_results=not args.no_save,
    )
    print_calibration_summary(results)
