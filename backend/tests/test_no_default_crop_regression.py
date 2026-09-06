"""
Test bảo vệ nguyên tắc: "crop=None phải được giữ nguyên, không bao giờ được
âm thầm thay bằng 1 loại cây cụ thể (vd 'lúa') hoặc giá trị sentinel không nhất
quán". Đây là lớp bảo vệ dài hạn — quét source code để bắt lỗi TÁI DIỄN, không
chỉ kiểm tra hành vi runtime của 1 vài hàm cụ thể.

Bối cảnh: lỗi "crop or 'lúa'" từng xuất hiện độc lập ở 3 nơi khác nhau
(layer3_docs.py, retrieval_plan.py, benchmark_evaluator.py) dù đã sửa 1 lần —
chứng tỏ cần 1 test tự động thay vì chỉ trông chờ code review.
"""
import re
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent  # backend/

# Các pattern coi là vi phạm: ép crop/season/soil_type/growth_stage về 1 giá trị
# cụ thể (hoặc sentinel rỗng) khi giá trị gốc là None/falsy.
FORBIDDEN_PATTERNS = [
    re.compile(r'crop\s+or\s+["\']'),          # crop or "lúa" / crop or ""
    re.compile(r'crop\s*:\s*str\s*=\s*["\']\w'),  # def f(crop: str = "lúa")  (không phải Optional)
]

# File được phép chứa "lúa" như 1 giá trị dữ liệu thật (không phải default/fallback):
# - farm_generator.py, water_balance.py: dữ liệu tham chiếu tĩnh (danh sách cây trồng theo vùng)
# - threshold_calibration.py: câu hỏi test mẫu
# - test_*.py: test tự viết crop="lúa" là hợp lệ (test case cụ thể, không phải default ngầm)
ALLOWLIST_SUBSTRINGS = [
    "farm_generator.py",
    "water_balance.py",
    "threshold_calibration.py",
    "benchmark_builder.py",  # CROPS_VN list, growth stage map — dữ liệu tham chiếu
    "fast_path_router.py",   # từ điển alias "gạo" -> "lúa" — ánh xạ từ đồng nghĩa, không phải default
    "/tests/",
    "\\tests\\",
]


class TestNoDefaultCropAntiPattern(unittest.TestCase):
    """
    Quét toàn bộ backend/**/*.py, cấm pattern 'crop or "<literal>"' và
    'crop: str = "<literal>"' — bất kể xuất hiện ở file nào trong tương lai.
    """

    def test_no_crop_or_literal_fallback_anywhere(self):
        violations = []
        for path in BACKEND_DIR.rglob("*.py"):
            path_str = str(path)
            if any(allow in path_str for allow in ALLOWLIST_SUBSTRINGS):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            for pattern in FORBIDDEN_PATTERNS:
                for m in pattern.finditer(text):
                    line_no = text[: m.start()].count("\n") + 1
                    violations.append(f"{path_str}:{line_no}: {m.group(0)}")

        self.assertEqual(
            violations, [],
            "Phát hiện default/fallback crop về 1 giá trị cụ thể — vi phạm "
            "nguyên tắc 'crop=None phải giữ nguyên None, không suy đoán'. "
            "Chi tiết:\n" + "\n".join(violations)
        )

    def test_semantic_search_default_crop_is_none(self):
        """semantic_search() không được có default crop cụ thể."""
        from backend.layers.layer3_docs import semantic_search
        import inspect
        sig = inspect.signature(semantic_search)
        default = sig.parameters["crop"].default
        self.assertIn(
            default, (None, inspect.Parameter.empty),
            f"semantic_search có default crop={default!r} — phải là None."
        )

    def test_hybrid_search_default_crop_is_none(self):
        """hybrid_search() không được có default crop cụ thể (kể cả '')."""
        from backend.layers.layer3_docs import hybrid_search
        import inspect
        sig = inspect.signature(hybrid_search)
        default = sig.parameters["crop"].default
        self.assertIn(
            default, (None, inspect.Parameter.empty),
            f"hybrid_search có default crop={default!r} — phải là None."
        )


if __name__ == "__main__":
    unittest.main()