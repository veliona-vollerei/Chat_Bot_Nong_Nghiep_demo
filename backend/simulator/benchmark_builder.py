"""
Benchmark Builder — GĐ3.

Xây dựng ≥260 câu hỏi benchmark có oracle answer từ dataset giả lập.

Cơ cấu câu hỏi theo GĐ3 roadmap:
  30  — Latest sensor reading
  20  — Device state
  20  — Irrigation history
  20  — Irrigation schedule
  20  — Missing/stale sensor (no-data, sensor offline)
  20  — Unauthorized/cross-farm (IAM test)
  50  — Agricultural factual QA (từ facts DB)
  30  — No-answer/hallucination guard
  30  — Vietnamese typo/local/no-accent (robustness)
  20  — Multi-turn/context (follow-up questions)
  ----
  260+

Oracle answer:
  - Tool-based: đáp án lấy từ dataset (chính xác)
  - RAG-based: đáp án lấy từ fact store
  - No-answer: expected = {"answer": null, "reason": "no_data" | "unauthorized"}

Output: benchmark_questions.json (định dạng chuẩn cho evaluator)
"""
import json
import random
import argparse
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

SEED = 42

# ─── Question Schema ──────────────────────────────────────────────────────

@dataclass
class BenchmarkQuestion:
    q_id: str
    category: str
    question: str
    lang: str = "vi"        # "vi" | "vi_typo" | "vi_no_accent"
    farm_id: Optional[str] = None
    zone_id: Optional[str] = None
    sensor_type: Optional[str] = None
    device_id: Optional[str] = None
    oracle_answer: Optional[str] = None   # Expected answer (None = no-data/unauthorized)
    oracle_source: Optional[str] = None   # "sensor" | "fact" | "none"
    expected_iam_result: str = "allow"    # "allow" | "deny"
    expected_quality_flag: Optional[str] = None  # "fresh" | "stale" | "missing"
    notes: Optional[str] = None


@dataclass
class BenchmarkDataset:
    questions: list[BenchmarkQuestion]
    total: int
    by_category: dict
    seed: int
    generated_at: str


# ─── Helpers ──────────────────────────────────────────────────────────────

SENSOR_VN_NAMES = {
    "soil_moisture": ["độ ẩm đất", "ẩm đất", "độ ẩm"],
    "temperature":   ["nhiệt độ", "nhiệt độ không khí"],
    "humidity":      ["độ ẩm không khí", "độ ẩm tương đối"],
    "rainfall":      ["lượng mưa", "mưa"],
    "ph":            ["pH đất", "độ pH", "pH"],
    "ec":            ["độ dẫn điện", "EC"],
}

DEVICE_VN_NAMES = {
    "valve": ["van tưới", "van nước", "van"],
    "pump":  ["máy bơm", "bơm nước", "bơm"],
    "sensor_node": ["cảm biến", "node cảm biến"],
    "weather_station": ["trạm thời tiết"],
}

TYPO_MAP = {
    "độ ẩm": ["do am", "dộ âm", "đo ẩm"],
    "nhiệt độ": ["nhiet do", "nhiêt dộ"],
    "lượng mưa": ["luong mua", "lương mưa"],
    "van tưới": ["van tưới", "van tuoi", "van tuới"],
    "giai đoạn": ["giai doan", "giai đoạn sinh trưởng"],
    "phân bón": ["phan bon", "phân bon"],
}

CROPS_VN = ["lúa", "cà phê", "hồ tiêu", "cao su", "sầu riêng", "xoài", "thanh long"]
SEASONS_VN = ["Đông Xuân", "Hè Thu", "Thu Đông"]
SOILS_VN = ["phù sa", "phèn nhẹ", "phèn nặng", "đất đỏ", "cát pha"]


def _typo(text: str, rng: random.Random) -> str:
    """Tạo phiên bản typo của câu hỏi."""
    for word, alts in TYPO_MAP.items():
        if word in text:
            text = text.replace(word, rng.choice(alts), 1)
    return text


def _no_accent(text: str) -> str:
    """Bỏ dấu (đơn giản hóa cho test)."""
    replacements = {
        'à': 'a', 'á': 'a', 'ả': 'a', 'ã': 'a', 'ạ': 'a',
        'ă': 'a', 'ắ': 'a', 'ằ': 'a', 'ẳ': 'a', 'ẵ': 'a', 'ặ': 'a',
        'â': 'a', 'ấ': 'a', 'ầ': 'a', 'ẩ': 'a', 'ẫ': 'a', 'ậ': 'a',
        'è': 'e', 'é': 'e', 'ẻ': 'e', 'ẽ': 'e', 'ẹ': 'e',
        'ê': 'e', 'ế': 'e', 'ề': 'e', 'ể': 'e', 'ễ': 'e', 'ệ': 'e',
        'ì': 'i', 'í': 'i', 'ỉ': 'i', 'ĩ': 'i', 'ị': 'i',
        'ò': 'o', 'ó': 'o', 'ỏ': 'o', 'õ': 'o', 'ọ': 'o',
        'ô': 'o', 'ố': 'o', 'ồ': 'o', 'ổ': 'o', 'ỗ': 'o', 'ộ': 'o',
        'ơ': 'o', 'ớ': 'o', 'ờ': 'o', 'ở': 'o', 'ỡ': 'o', 'ợ': 'o',
        'ù': 'u', 'ú': 'u', 'ủ': 'u', 'ũ': 'u', 'ụ': 'u',
        'ư': 'u', 'ứ': 'u', 'ừ': 'u', 'ử': 'u', 'ữ': 'u', 'ự': 'u',
        'ỳ': 'y', 'ý': 'y', 'ỷ': 'y', 'ỹ': 'y', 'ỵ': 'y',
        'đ': 'd', 'Đ': 'D',
    }
    return "".join(replacements.get(c, c) for c in text)


# ─── Category Builders ────────────────────────────────────────────────────

def _build_sensor_questions(farms: list, rng: random.Random, n: int = 30) -> list[BenchmarkQuestion]:
    """30 câu: đọc sensor mới nhất."""
    qs = []
    for i in range(n):
        farm = rng.choice(farms)
        zone = rng.choice(farm["zones"])
        sensors = zone.get("sensors", ["soil_moisture"])
        st = rng.choice(sensors)
        vn_name = rng.choice(SENSOR_VN_NAMES.get(st, [st]))
        q = f"Cho biết {vn_name} hiện tại tại {zone['name']} của {farm['name']}?"
        qs.append(BenchmarkQuestion(
            q_id=f"sensor_{i+1:03d}",
            category="latest_sensor",
            question=q,
            farm_id=farm["farm_id"],
            zone_id=zone["zone_id"],
            sensor_type=st,
            oracle_source="sensor",
            expected_iam_result="allow",
        ))
    return qs


def _build_device_questions(farms: list, rng: random.Random, n: int = 20) -> list[BenchmarkQuestion]:
    """20 câu: trạng thái thiết bị."""
    qs = []
    device_types = ["valve", "pump"]
    for i in range(n):
        farm = rng.choice(farms)
        zone = rng.choice(farm["zones"])
        dtype = rng.choice(device_types)
        vn_name = rng.choice(DEVICE_VN_NAMES.get(dtype, [dtype]))
        device_id = f"{zone['zone_id']}_{dtype}_01"
        q = f"Trạng thái của {vn_name} {device_id} tại {zone['name']} hiện tại thế nào?"
        qs.append(BenchmarkQuestion(
            q_id=f"device_{i+1:03d}",
            category="device_state",
            question=q,
            farm_id=farm["farm_id"],
            zone_id=zone["zone_id"],
            device_id=device_id,
            oracle_source="sensor",
            expected_iam_result="allow",
        ))
    return qs


def _build_irrigation_questions(farms: list, rng: random.Random, n: int = 20) -> list[BenchmarkQuestion]:
    """20 câu: lịch sử tưới."""
    qs = []
    for i in range(n):
        farm = rng.choice(farms)
        zone = rng.choice(farm["zones"])
        days = rng.choice([3, 7, 14])
        q = f"Khu vực {zone['name']} của {farm['name']} đã được tưới bao nhiêu lần trong {days} ngày qua?"
        qs.append(BenchmarkQuestion(
            q_id=f"irrigation_hist_{i+1:03d}",
            category="irrigation_history",
            question=q,
            farm_id=farm["farm_id"],
            zone_id=zone["zone_id"],
            oracle_source="sensor",
            expected_iam_result="allow",
            notes=f"last_{days}_days",
        ))
    return qs


def _build_irrigation_schedule_questions(farms: list, rng: random.Random, n: int = 20) -> list[BenchmarkQuestion]:
    """20 câu: lịch tưới kế tiếp / cấu hình lịch tưới tự động."""
    qs = []
    for i in range(n):
        farm = rng.choice(farms)
        zone = rng.choice(farm["zones"])
        q_templates = [
            f"Lịch tưới tự động tiếp theo của {zone['name']} thuộc {farm['name']} là khi nào?",
            f"Khi nào thì van tưới tại khu vực {zone['name']} ({farm['name']}) sẽ mở lần tới?",
            f"Cho tôi biết thông tin lịch tưới đã cài đặt cho {zone['name']} của nông trại {farm['name']}.",
        ]
        q = rng.choice(q_templates)
        qs.append(BenchmarkQuestion(
            q_id=f"irrigation_sched_{i+1:03d}",
            category="irrigation_schedule",
            question=q,
            farm_id=farm["farm_id"],
            zone_id=zone["zone_id"],
            oracle_source="sensor",
            expected_iam_result="allow",
            notes="next_irrigation_schedule",
        ))
    return qs



def _build_stale_questions(farms: list, rng: random.Random, n: int = 20) -> list[BenchmarkQuestion]:
    """20 câu: sensor offline/stale — expected no-data."""
    qs = []
    for i in range(n):
        farm = rng.choice(farms)
        zone = rng.choice(farm["zones"])
        sensors = zone.get("sensors", ["soil_moisture"])
        st = rng.choice(sensors)
        vn_name = rng.choice(SENSOR_VN_NAMES.get(st, [st]))
        q = f"{vn_name} tại {zone['name']} hiện tại là bao nhiêu?" + (
            " (Cảm biến có thể đang offline)" if i % 3 == 0 else ""
        )
        qs.append(BenchmarkQuestion(
            q_id=f"stale_{i+1:03d}",
            category="missing_stale_sensor",
            question=q,
            farm_id=farm["farm_id"],
            zone_id=zone["zone_id"],
            sensor_type=st,
            oracle_answer=None,
            oracle_source="none",
            expected_iam_result="allow",
            expected_quality_flag="missing",
            notes="sensor_offline_fault_injected",
        ))
    return qs


def _build_iam_questions(farms: list, rng: random.Random, n: int = 20) -> list[BenchmarkQuestion]:
    """20 câu: cross-farm unauthorized — expected deny."""
    qs = []
    all_farm_ids = [f["farm_id"] for f in farms]
    for i in range(n):
        # User thuộc farm_id A nhưng hỏi về farm_id B
        farm_a = rng.choice(farms)
        # Chọn farm_b khác farm_a
        other_ids = [fid for fid in all_farm_ids if fid != farm_a["farm_id"]]
        farm_b_id = rng.choice(other_ids)
        farm_b = next(f for f in farms if f["farm_id"] == farm_b_id)
        zone_b = rng.choice(farm_b["zones"])
        st = rng.choice(["soil_moisture", "temperature"])
        vn_name = rng.choice(SENSOR_VN_NAMES.get(st, [st]))
        q = f"Cho tôi biết {vn_name} tại {zone_b['name']} của {farm_b['name']}?"
        qs.append(BenchmarkQuestion(
            q_id=f"iam_{i+1:03d}",
            category="unauthorized_cross_farm",
            question=q,
            farm_id=farm_b_id,            # user thuộc farm_a nhưng request farm_b
            zone_id=zone_b["zone_id"],
            sensor_type=st,
            oracle_answer=None,
            oracle_source="none",
            expected_iam_result="deny",
            notes=f"user_from={farm_a['farm_id']} requested={farm_b_id}",
        ))
    return qs


def _build_factual_questions(rng: random.Random, n: int = 50) -> list[BenchmarkQuestion]:
    """50 câu: câu hỏi thực tế nông nghiệp (từ fact store / doc store)."""
    templates = [
        ("Lượng phân đạm khuyến cáo cho {crop} vụ {season} trên đất {soil} là bao nhiêu?", "định_lượng"),
        ("Năng suất trung bình của {crop} trên đất {soil} là bao nhiêu tấn/ha?", "định_lượng"),
        ("Giống {crop} nào phù hợp với đất {soil} vụ {season}?", "phù_hợp/quan_hệ"),
        ("{crop} cần tưới bao nhiêu lần trong giai đoạn {stage}?", "định_lượng"),
        ("Cách phòng trừ sâu bệnh chính trên {crop} là gì?", "diễn_giải"),
        ("Thời điểm thu hoạch {crop} vụ {season} thường vào tháng mấy?", "diễn_giải"),
        ("pH đất phù hợp cho {crop} là bao nhiêu?", "định_lượng"),
        ("Lượng nước tưới cho {crop} giai đoạn {stage} là bao nhiêu?", "định_lượng"),
        ("Kỹ thuật làm đất cho {crop} trên đất {soil} như thế nào?", "diễn_giải"),
        ("Phân kali cần bón cho {crop} vụ {season} là bao nhiêu?", "định_lượng"),
    ]

    qs = []
    for i in range(n):
        tmpl, qtype = templates[i % len(templates)]
        crop = rng.choice(CROPS_VN)
        season = rng.choice(SEASONS_VN)
        soil = rng.choice(SOILS_VN)
        stages = ["đẻ nhánh", "làm đòng", "trỗ bông", "chín"] if crop == "lúa" else ["sinh trưởng", "ra hoa", "thu hoạch"]
        stage = rng.choice(stages)

        q = tmpl.format(crop=crop, season=season, soil=soil, stage=stage)
        qs.append(BenchmarkQuestion(
            q_id=f"factual_{i+1:03d}",
            category="agricultural_factual_qa",
            question=q,
            oracle_source="fact",
            expected_iam_result="allow",
            notes=f"type={qtype}",
        ))
    return qs


def _build_noanswer_questions(rng: random.Random, n: int = 30) -> list[BenchmarkQuestion]:
    """30 câu: không có dữ liệu / ngoài phạm vi — expected null answer."""
    oob_templates = [
        "Giá chứng khoán VNM hôm nay là bao nhiêu?",
        "Tỷ giá USD/VND hiện tại?",
        "Cách đầu tư bất động sản ở Hà Nội?",
        "Hướng dẫn lập trình Python cho người mới?",
        "Chỉ số VN-Index tuần này?",
        "Công thức nấu phở bò Hà Nội?",
    ]
    no_data_templates = [
        "Độ ẩm đất tại farm ảo xyz_999 là bao nhiêu?",
        "Lịch tưới của zone không tồn tại trong hệ thống?",
        "Trạng thái thiết bị sensor_99999?",
        "Năng suất lúa tại sao Hỏa năm 2050?",
        "Tình trạng cà phê trên sao Kim?",
    ]
    qs = []
    templates = oob_templates + no_data_templates
    for i in range(n):
        q = templates[i % len(templates)]
        if i >= len(oob_templates):
            q += f" (test {i+1})"
        qs.append(BenchmarkQuestion(
            q_id=f"noanswer_{i+1:03d}",
            category="no_answer_hallucination_guard",
            question=q,
            oracle_answer=None,
            oracle_source="none",
            expected_iam_result="allow",
            notes="expect_null_or_outofscope",
        ))
    return qs


def _build_typo_questions(base_qs: list[BenchmarkQuestion], rng: random.Random, n: int = 30) -> list[BenchmarkQuestion]:
    """30 câu: phiên bản typo/no-accent của câu hỏi gốc."""
    qs = []
    pool = [q for q in base_qs if q.category in ("latest_sensor", "agricultural_factual_qa")]
    rng.shuffle(pool)

    for i, orig in enumerate(pool[:n]):
        if i % 2 == 0:
            text = _typo(orig.question, rng)
            lang = "vi_typo"
        else:
            text = _no_accent(orig.question)
            lang = "vi_no_accent"

        import dataclasses
        q_copy = dataclasses.replace(orig,
            q_id=f"typo_{i+1:03d}",
            category="vietnamese_typo_robustness",
            question=text,
            lang=lang,
        )
        qs.append(q_copy)
    return qs


def _build_multiturn_questions(farms: list, rng: random.Random, n: int = 20) -> list[BenchmarkQuestion]:
    """20 câu: follow-up / context-dependent questions."""
    templates = [
        ("Độ ẩm đất vùng {zone} hiện tại?", "Và khi nào thì cần tưới?"),
        ("Trạng thái van tưới {device} thế nào?", "Nếu van đang đóng thì bật lên được không?"),
        ("Năng suất {crop} vụ {season} là bao nhiêu?", "So với năm ngoái thì cao hay thấp hơn?"),
        ("Lượng phân đạm cho {crop} giai đoạn đẻ nhánh?", "Bón vào buổi sáng hay chiều tốt hơn?"),
        ("Có cảnh báo nào tại farm {farm} không?", "Cảnh báo đó nghĩa là gì?"),
    ]
    qs = []
    for i in range(n):
        farm = rng.choice(farms)
        zone = rng.choice(farm["zones"])
        device_id = f"{zone['zone_id']}_valve_01"
        crop = zone["crop"]
        season = rng.choice(SEASONS_VN)
        tmpl_q1, tmpl_q2 = templates[i % len(templates)]

        q1 = tmpl_q1.format(zone=zone["name"], device=device_id, crop=crop,
                            season=season, farm=farm["name"])
        q2 = tmpl_q2.format(zone=zone["name"], device=device_id, crop=crop,
                            season=season, farm=farm["name"])

        qs.append(BenchmarkQuestion(
            q_id=f"multiturn_{i+1:03d}_q1",
            category="multi_turn_context",
            question=q1,
            farm_id=farm["farm_id"],
            zone_id=zone["zone_id"],
            oracle_source="sensor",
            expected_iam_result="allow",
            notes=f"turn=1 follow_up={q2[:60]}",
        ))
        qs.append(BenchmarkQuestion(
            q_id=f"multiturn_{i+1:03d}_q2",
            category="multi_turn_context",
            question=q2,
            farm_id=farm["farm_id"],
            zone_id=zone["zone_id"],
            oracle_source="none",
            expected_iam_result="allow",
            notes="turn=2 depends_on_q1",
        ))
    return qs[:n]  # Giữ đúng n câu


def build_benchmark(
    farms_path: Optional[Path] = None,
    seed: int = SEED,
) -> BenchmarkDataset:
    """Xây dựng toàn bộ benchmark dataset ≥260 câu."""
    import datetime as _dt

    rng = random.Random(seed)

    # Load hoặc generate farm data
    if farms_path and farms_path.exists():
        with open(farms_path, encoding="utf-8") as f:
            farms_data = json.load(f)["farms"]
    else:
        # Generate inline
        from backend.simulator.farm_generator import generate_farms
        ds = generate_farms(n_farms=35, seed=seed)
        farms_data = [
            {
                "farm_id": f.farm_id,
                "name": f.name,
                "zones": [
                    {
                        "zone_id": z.zone_id,
                        "name": z.name,
                        "crop": z.crop,
                        "sensors": z.sensors,
                    }
                    for z in f.zones
                ],
            }
            for f in ds.farms
        ]

    all_questions: list[BenchmarkQuestion] = []

    # Build theo cơ cấu
    q_sensor = _build_sensor_questions(farms_data, rng, 30)
    q_device = _build_device_questions(farms_data, rng, 20)
    q_irr    = _build_irrigation_questions(farms_data, rng, 20)
    q_sched  = _build_irrigation_schedule_questions(farms_data, rng, 20)
    q_stale  = _build_stale_questions(farms_data, rng, 20)
    q_iam    = _build_iam_questions(farms_data, rng, 20)
    q_fact   = _build_factual_questions(rng, 50)
    q_noans  = _build_noanswer_questions(rng, 30)
    q_typo   = _build_typo_questions(q_sensor + q_fact, rng, 30)
    q_multi  = _build_multiturn_questions(farms_data, rng, 20)

    all_questions = (q_sensor + q_device + q_irr + q_sched + q_stale + q_iam +
                     q_fact + q_noans + q_typo + q_multi)

    # Thống kê theo category
    by_cat: dict[str, int] = {}
    for q in all_questions:
        by_cat[q.category] = by_cat.get(q.category, 0) + 1

    return BenchmarkDataset(
        questions=all_questions,
        total=len(all_questions),
        by_category=by_cat,
        seed=seed,
        generated_at=_dt.datetime.now().isoformat(),
    )


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

    parser = argparse.ArgumentParser(description="Build Benchmark Dataset")
    parser.add_argument("--farms", default=None, help="Path to farms.json")
    parser.add_argument("--output", default="data/benchmark_questions.json")
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()

    dataset = build_benchmark(
        farms_path=Path(args.farms) if args.farms else None,
        seed=args.seed,
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(dataset)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n✅ Benchmark dataset: {dataset.total} câu hỏi → {out_path}")
    print(f"\n{'Category':<35} {'Count':>6}")
    print("-" * 42)
    for cat, cnt in sorted(dataset.by_category.items(), key=lambda x: -x[1]):
        print(f"  {cat:<33} {cnt:>6}")
    print(f"\n  {'TOTAL':<33} {dataset.total:>6}")
