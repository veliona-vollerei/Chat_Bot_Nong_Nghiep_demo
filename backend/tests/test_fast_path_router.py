"""
Test Fast-Path Router — regression tests bắt buộc để chặn tái diễn 2 lỗi nghiêm trọng:

Lỗi #1 (v1.0): Layer 0 (farm_id/IoT) fire trước Layer 2 (định lượng) → gần như mọi
              câu hỏi thật bị ép về question_type="diễn_giải", làm hỏng numeric guardrail.
Lỗi phụ:      Pattern IoT \\bkhu [A-Za-z]\\b khớp nhầm câu định lượng có tên khu (vd "khu A").
"""
import pytest
from backend.router.fast_path_router import try_fast_path


class TestLayer0DoesNotHijackQuantitative:
    def test_quantitative_with_farm_id_returns_dinh_luong(self):
        result = try_fast_path(
            question="liều lượng phân đạm cho lúa là bao nhiêu?",
            farm_id="F001",
        )
        assert result is not None
        assert result["question_type"] == "định_lượng", f"Got: {result['question_type']}"
        assert "Layer2_Quantitative" in result["decision_path"]

    def test_quantitative_with_zone_id_returns_dinh_luong(self):
        result = try_fast_path(
            question="bón bao nhiêu kg/ha phân lân cho lúa đông xuân?",
            zone_id="ZoneA",
        )
        assert result is not None
        assert result["question_type"] == "định_lượng", f"Got: {result['question_type']}"

    def test_quantitative_mentioning_khu_a_not_hijacked_by_iot(self):
        result = try_fast_path(
            question="liều lượng phân đạm cho lúa khu A là bao nhiêu kg/ha?",
            farm_id="F001",
        )
        assert result is not None
        assert result["question_type"] == "định_lượng", (
            f"'khu A' trong câu định lượng không được bị nhận nhầm là IoT. Got: {result['question_type']}"
        )

    def test_quantitative_no_farm_id(self):
        result = try_fast_path("năng suất trung bình của lúa là bao nhiêu tấn/ha?")
        assert result is not None
        assert result["question_type"] == "định_lượng"


class TestIoTPathStillWorks:
    def test_sensor_keyword_routes_to_dien_giai(self):
        result = try_fast_path(
            question="cảm biến độ ẩm khu A đang bao nhiêu?",
            farm_id="F001",
        )
        assert result is not None
        assert result["question_type"] == "diễn_giải"

    def test_bare_farm_context_short_question(self):
        result = try_fast_path("có gì mới không?", farm_id="F001")
        assert result is not None
        assert "FARM_CONTEXT_PRESENT" in result["reason_code"]


class TestOtherLayers:
    def test_relation_with_farm_id(self):
        result = try_fast_path("giống nào phù hợp với đất phèn nhẹ?", farm_id="F001")
        assert result is not None
        assert result["question_type"] == "phù_hợp/quan_hệ"

    def test_out_of_scope(self):
        result = try_fast_path("giá bitcoin hôm nay là bao nhiêu?", farm_id="F001")
        assert result is not None
        assert result["question_type"] == "ngoài_phạm_vi"

    def test_explanation(self):
        result = try_fast_path("tại sao lúa bị vàng lá?")
        assert result is not None
        assert result["question_type"] == "diễn_giải"

    def test_no_match_returns_none(self):
        result = try_fast_path("thế nào là tốt nhất?")
        assert result is None

    def test_very_short_returns_none(self):
        assert try_fast_path("AB") is None
        assert try_fast_path("") is None


class TestAuditTrail:
    def test_audit_fields_present(self):
        cases = [
            ("liều lượng phân đạm cho lúa khu A", "F001"),
            ("giống nào phù hợp với đất mặn?", None),
            ("tại sao lúa bị vàng lá?", None),
            ("bitcoin hôm nay giá bao nhiêu", None),
        ]
        for question, farm_id in cases:
            result = try_fast_path(question, farm_id=farm_id)
            if result is not None:
                assert "decision_path" in result, f"Thiếu decision_path: {question!r}"
                assert "reason_code" in result, f"Thiếu reason_code: {question!r}"
                assert result["confidence"] == "high"
