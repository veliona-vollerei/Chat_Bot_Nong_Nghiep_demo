# Việc Cần Làm — Schema Fact & Ground Truth Benchmark

---

## PHẦN 1 — Bổ Sung Trường Còn Thiếu Cho Bảng `facts`

### Vị trí sửa: `backend/db/postgres.py`, ngay sau khối `ALTER TABLE facts` hiện có (dòng ~236)

```python
# ─── Bổ sung theo Review_v1: variety, applicability có cấu trúc, value range, nguồn, hiệu lực ───
ALTER TABLE facts ADD COLUMN IF NOT EXISTS variety TEXT;                    -- giống cây trồng (VD: "OM5451", "Nhị ưu 838")
ALTER TABLE facts ADD COLUMN IF NOT EXISTS cultivation_method TEXT;         -- "hữu cơ" | "thâm canh" | "tưới nhỏ giọt" | "tưới tràn" ...
ALTER TABLE facts ADD COLUMN IF NOT EXISTS applicability JSONB;             -- điều kiện áp dụng có cấu trúc, VD: {"canh_tac": "huu_co", "vung": ["dong_bang_song_cuu_long"]}

ALTER TABLE facts ADD COLUMN IF NOT EXISTS value_min FLOAT;                 -- giá trị nhỏ nhất của khoảng khuyến cáo
ALTER TABLE facts ADD COLUMN IF NOT EXISTS value_max FLOAT;                 -- giá trị lớn nhất
ALTER TABLE facts ADD COLUMN IF NOT EXISTS tolerance FLOAT;                 -- sai số chấp nhận được (VD: ±5%)

ALTER TABLE facts ADD COLUMN IF NOT EXISTS source_page INT;                 -- số trang trong tài liệu gốc
ALTER TABLE facts ADD COLUMN IF NOT EXISTS source_section TEXT;             -- mục/chương trong tài liệu gốc (VD: "3.2")
ALTER TABLE facts ADD COLUMN IF NOT EXISTS publication_date DATE;           -- ngày tài liệu gốc được xuất bản (khác effective_date)

ALTER TABLE facts ADD COLUMN IF NOT EXISTS effective_to DATE;               -- ngày hết hiệu lực (NULL = còn hiệu lực)
ALTER TABLE facts ADD COLUMN IF NOT EXISTS supersedes INT REFERENCES facts(fact_id);  -- fact_id của bản ghi bị thay thế bởi bản ghi này

CREATE INDEX IF NOT EXISTS idx_facts_variety ON facts(variety);
CREATE INDEX IF NOT EXISTS idx_facts_effective_to ON facts(effective_to);
CREATE INDEX IF NOT EXISTS idx_facts_supersedes ON facts(supersedes);
```

> Dùng `JSONB` cho `applicability` (không phải text) để có thể query có cấu trúc, ví dụ: `WHERE applicability->>'canh_tac' = 'huu_co'`.
> Dùng `value_min`/`value_max` dạng FLOAT riêng, **giữ nguyên cột `value` TEXT cũ** để không phá dữ liệu hiện có — `value` vẫn dùng để hiển thị câu trả lời dạng người đọc (VD: "90-120"), còn `value_min`/`value_max` dùng để máy so sánh/validate.

### Việc cần làm sau khi thêm cột

1. **Chạy migration** — khởi động lại app 1 lần để các `ALTER TABLE` chạy (đã có cơ chế `IF NOT EXISTS` nên an toàn, không lỗi nếu chạy nhiều lần).
2. **Cập nhật code ingestion** (`backend/ingestion/`) để khi trích xuất Fact mới từ tài liệu, có điền `variety`, `cultivation_method`, `value_min`/`value_max`, `source_page`, `source_section`, `publication_date` — không chỉ để trống các cột mới.
3. **Cập nhật dữ liệu Fact hiện có** (nếu có ý nghĩa) — với các bản ghi cũ, có thể chạy 1 script điền `value_min`/`value_max` bằng cách parse chuỗi `value` cũ (VD: `"90-120"` → `value_min=90, value_max=120`) để không mất dữ liệu lịch sử.
4. **Xử lý `supersedes`** — khi ingest 1 tài liệu mới thay thế tài liệu cũ, cần logic tìm Fact cũ cùng `crop`+`attribute`+`region`, đặt `effective_to` cho bản cũ và `supersedes` cho bản mới trỏ về `fact_id` cũ.

---

## PHẦN 2 — Sửa Ground Truth Cho 50 Câu `agricultural_factual_qa`

### Nguyên tắc: Sinh câu hỏi TỪ Fact thật trong DB, không sinh ngẫu nhiên rồi hy vọng có Fact khớp

### Vị trí sửa: `backend/simulator/benchmark_builder.py`, hàm `_build_factual_questions` (dòng 278)

**Code hiện tại (vấn đề):**
```python
def _build_factual_questions(rng: random.Random, n: int = 50) -> list[BenchmarkQuestion]:
    templates = [...]
    qs = []
    for i in range(n):
        crop = rng.choice(CROPS_VN)      # ngẫu nhiên, không tra DB
        season = rng.choice(SEASONS_VN)
        soil = rng.choice(SOILS_VN)
        q = tmpl.format(crop=crop, season=season, soil=soil)
        qs.append(BenchmarkQuestion(..., oracle_source="fact"))  # không có oracle_answer
    return qs
```

**Code cần thay thế:**
```python
from backend.db.postgres import get_cursor

def _build_factual_questions(rng: random.Random, n: int = 50) -> list[BenchmarkQuestion]:
    """
    50 câu: sinh TỪ Fact thật trong database, không sinh ngẫu nhiên.
    Mỗi câu có oracle_answer lấy trực tiếp từ bản ghi Fact tương ứng.
    """
    # Bước 1: Lấy toàn bộ Fact có is_quantitative=true (đủ điều kiện làm câu hỏi định lượng)
    with get_cursor() as cur:
        cur.execute("""
            SELECT fact_id, crop, variety, season, soil_type, growth_stage,
                   attribute, value, value_min, value_max, unit, condition_note
            FROM facts
            WHERE is_quantitative = true
              AND (effective_to IS NULL OR effective_to > NOW())   -- chỉ lấy Fact còn hiệu lực
            ORDER BY RANDOM()
        """)
        rows = cur.fetchall()

    if not rows:
        logger.warning(
            "⚠️ Không có Fact nào trong DB để sinh câu hỏi thật — "
            "fallback sang câu hỏi KHÔNG có oracle_answer (chỉ nên dùng tạm khi DB rỗng)."
        )
        return _build_factual_questions_fallback_no_oracle(rng, n)

    # Bước 2: Map mỗi Fact -> 1 template câu hỏi phù hợp với attribute của nó
    attribute_to_template = {
        "phân đạm":  "Lượng phân đạm khuyến cáo cho {crop} vụ {season} trên đất {soil} là bao nhiêu?",
        "năng suất": "Năng suất trung bình của {crop} trên đất {soil} là bao nhiêu tấn/ha?",
        "phân kali": "Phân kali cần bón cho {crop} vụ {season} là bao nhiêu?",
        "pH":        "pH đất phù hợp cho {crop} là bao nhiêu?",
        "lượng nước tưới": "Lượng nước tưới cho {crop} giai đoạn {stage} là bao nhiêu?",
        # thêm map cho các attribute khác có trong DB thật của bạn
    }
    default_template = "{attribute} khuyến cáo cho {crop} là bao nhiêu?"

    qs = []
    for i, row in enumerate(rows[:n]):
        (fact_id, crop, variety, season, soil, growth_stage,
         attribute, value, value_min, value_max, unit, condition_note) = row

        tmpl = attribute_to_template.get(attribute, default_template)
        q = tmpl.format(
            crop=crop, season=season or "", soil=soil or "",
            stage=growth_stage or "", attribute=attribute,
        )

        # Oracle answer LẤY THẲNG từ Fact — không phải rubric chung chung
        if value_min is not None and value_max is not None:
            oracle_answer = f"{value_min}-{value_max} {unit or ''}".strip()
        else:
            oracle_answer = f"{value} {unit or ''}".strip()

        qs.append(BenchmarkQuestion(
            q_id=f"factual_{i+1:03d}",
            category="agricultural_factual_qa",
            question=q,
            oracle_source="fact",
            oracle_answer=oracle_answer,          # ← THẬT, lấy từ DB
            oracle_fact_id=fact_id,                # ← lưu lại để truy vết/debug
            expected_iam_result="allow",
            notes=f"crop={crop}, variety={variety}, condition={condition_note}",
        ))

    if len(qs) < n:
        logger.warning(f"Chỉ có {len(qs)}/{n} Fact đủ điều kiện — cần bổ sung thêm Fact vào DB.")

    return qs
```

> **Cần thêm field `oracle_fact_id: Optional[int] = None`** vào dataclass `BenchmarkQuestion` (đầu file `benchmark_builder.py`) để lưu lại fact_id nguồn, phục vụ truy vết khi review.

### Việc cần làm để chạy code trên

1. **Đảm bảo bảng `facts` có đủ dữ liệu thật đã kiểm duyệt** — nếu DB đang trống hoặc ít Fact, cần nạp thêm dữ liệu nông học đã được chuyên gia duyệt (`verification_status = 'approved'`) trước khi chạy benchmark, nếu không sẽ rơi vào nhánh fallback (không có oracle thật).
2. **Mở rộng `attribute_to_template`** — dictionary trên mới map 5 loại attribute mẫu; cần liệt kê **toàn bộ** giá trị `attribute` thực tế đang có trong bảng `facts` của bạn và viết template câu hỏi tương ứng cho từng loại (để không bị rơi vào `default_template` chung chung, làm giảm chất lượng câu hỏi).
3. **Cân nhắc lọc thêm theo `verification_status = 'approved'`** trong câu SQL — chỉ nên sinh câu hỏi benchmark từ Fact đã qua kiểm duyệt chuyên gia, không dùng Fact còn ở trạng thái `pending`/`synthetic`, để đảm bảo ground truth đáng tin cậy.
4. **Chạy lại benchmark_builder** để sinh `benchmark_questions.json` mới có `oracle_answer` thật:
   ```bash
   python -m backend.simulator.benchmark_builder
   ```
5. **Xác nhận `benchmark_evaluator.py` dùng đúng oracle_answer mới** — code chấm điểm (dòng ~339) đã có sẵn logic `ground_truth = oracle_answer if oracle_answer else (...)`, nên **không cần sửa file này** — chỉ cần `oracle_answer` không còn là `None` nữa là tự động dùng giá trị thật.
6. **Chạy lại benchmark full_flow** để có điểm factual accuracy đáng tin cậy:
   ```bash
   python -m backend.simulator.benchmark_evaluator
   ```
7. So sánh điểm mới với điểm cũ (92%/84%) — nếu **tụt xuống** sau khi có ground truth thật, đó là dấu hiệu chatbot thực sự yếu hơn số liệu cũ thể hiện (vì trước đây chấm theo rubric dễ hơn); nếu **giữ nguyên hoặc tăng**, đó là bằng chứng đáng tin cậy hơn nhiều để báo cáo NextFarm.

---

## Tóm tắt việc cần làm theo thứ tự

- [ ] Chạy `ALTER TABLE` bổ sung 9 cột mới vào bảng `facts`
- [ ] Cập nhật pipeline ingestion để điền các cột mới khi trích xuất Fact
- [ ] (Tùy chọn) Viết script điền `value_min`/`value_max` cho Fact cũ từ chuỗi `value` hiện có
- [ ] Đảm bảo DB có đủ Fact thật, đã qua kiểm duyệt (`verification_status='approved'`)
- [ ] Thêm field `oracle_fact_id` vào `BenchmarkQuestion` dataclass
- [ ] Viết lại `_build_factual_questions()` để tra DB thật thay vì sinh ngẫu nhiên
- [ ] Mở rộng `attribute_to_template` phủ hết các attribute thật trong DB
- [ ] Chạy lại `benchmark_builder.py` rồi `benchmark_evaluator.py`
- [ ] So sánh điểm factual accuracy mới vs cũ, cập nhật báo cáo nghiệm thu với số liệu đáng tin cậy hơn
