"""
Unit Tests — GĐ1 Mục 1: Router Fallback Policy
Kiểm tra các case: không có crop, crop mơ hồ, crop sai chính tả.

Chạy: pytest backend/tests/test_router.py -v
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

# pyrefly: ignore [missing-import]
import pytest
from unittest.mock import patch, MagicMock


# ─── Fixtures ──────────────────────────────────────────────────────────────

VALID_ROUTER_RESPONSE_NO_CROP = {
    "question_type": "diễn_giải",
    "crop": None,
    "season": None,
    "soil_type": None,
    "growth_stage": None,
    "variety": None,
    "topic_keywords": ["biến đổi khí hậu"],
    "confidence": "high",
    "clarification_question": None,
    "error": None,
}

VALID_ROUTER_RESPONSE_WITH_CROP = {
    "question_type": "định_lượng",
    "crop": "lúa",
    "season": "Đông Xuân",
    "soil_type": "phèn nhẹ",
    "growth_stage": "đẻ_nhánh",
    "variety": None,
    "topic_keywords": ["liều lượng phân bón"],
    "confidence": "high",
    "clarification_question": None,
    "error": None,
}

VALID_ROUTER_RESPONSE_AMBIGUOUS = {
    "question_type": "cần_làm_rõ",
    "crop": None,
    "season": None,
    "soil_type": None,
    "growth_stage": None,
    "variety": None,
    "topic_keywords": [],
    "confidence": "low",
    "clarification_question": "Bạn đang hỏi về loại cây trồng nào? (lúa, cà phê, dưa hấu...)",
    "error": None,
}


# ─── Test: Không có crop ──────────────────────────────────────────────────

class TestRouterNoCrop:
    """GĐ1 Mục 1: Router không được mặc định crop='lúa'."""

    def test_fallback_no_crop_returns_none(self):
        """Khi API lỗi, crop phải là None, không phải 'lúa'."""
        from backend.router.query_router import route_question
        from backend.utils.gemini_client import AllKeysExhaustedError

        with patch('backend.router.query_router.call_with_rotation',
                   side_effect=AllKeysExhaustedError("All keys exhausted")):
            result = route_question("biến đổi khí hậu ảnh hưởng thế nào")

        assert result["crop"] is None, (
            f"FAIL: crop phải là None khi API lỗi, nhưng nhận được '{result['crop']}'. "
            f"GĐ1 Mục 1: Không được hardcode crop='lúa'"
        )
        assert result["error"] is not None, "Phải có error message khi API lỗi"
        assert result["growth_stage"] is None, "growth_stage phải có trong response"

    def test_json_parse_error_returns_none_crop(self):
        """Khi JSON parse lỗi, crop phải là None."""
        from backend.router.query_router import route_question

        with patch('backend.router.query_router.call_with_rotation',
                   return_value="invalid json {"):
            result = route_question("câu hỏi test")

        assert result["crop"] is None, (
            f"FAIL: crop phải là None khi JSON parse lỗi, nhưng nhận được '{result['crop']}'"
        )

    def test_general_exception_returns_none_crop(self):
        """Khi exception bất kỳ, crop phải là None."""
        from backend.router.query_router import route_question

        with patch('backend.router.query_router.call_with_rotation',
                   side_effect=RuntimeError("Unexpected error")):
            result = route_question("câu hỏi test")

        assert result["crop"] is None, (
            f"FAIL: crop phải là None khi exception xảy ra"
        )

    def test_router_response_with_null_crop(self):
        """Khi Gemini trả về crop=null, hệ thống phải giữ nguyên None."""
        from backend.router.query_router import route_question
        import json

        mock_response = json.dumps({
            "question_type": "diễn_giải",
            "crop": None,
            "season": None,
            "soil_type": None,
            "growth_stage": None,
            "variety": None,
            "topic_keywords": ["biến đổi khí hậu"],
            "confidence": "high",
            "clarification_question": None,
        })

        with patch('backend.router.query_router.call_with_rotation',
                   return_value=mock_response):
            result = route_question("biến đổi khí hậu là gì")

        assert result["crop"] is None, "crop=None từ Gemini phải được preserve"
        assert result["error"] is None

    def test_router_response_with_empty_crop(self):
        """Khi Gemini trả về crop='', hệ thống phải convert sang None."""
        from backend.router.query_router import route_question
        import json

        mock_response = json.dumps({
            "question_type": "diễn_giải",
            "crop": "",
            "season": None,
            "soil_type": None,
            "growth_stage": None,
            "variety": None,
            "topic_keywords": [],
            "confidence": "medium",
            "clarification_question": None,
        })

        with patch('backend.router.query_router.call_with_rotation',
                   return_value=mock_response):
            result = route_question("kỹ thuật tưới nước")

        assert result["crop"] is None, (
            "crop='' phải được convert sang None (GĐ1 Mục 1)"
        )


# ─── Test: Crop mơ hồ ────────────────────────────────────────────────────

class TestRouterAmbiguousCrop:
    """GĐ1 Mục 1: Crop mơ hồ phải trả về cần_làm_rõ."""

    def test_ambiguous_question_triggers_clarification(self):
        """Câu hỏi mơ hồ phải trả về question_type='cần_làm_rõ'."""
        from backend.router.query_router import route_question
        import json

        mock_response = json.dumps(VALID_ROUTER_RESPONSE_AMBIGUOUS)
        with patch('backend.router.query_router.call_with_rotation',
                   return_value=mock_response):
            result = route_question("nên tưới bao nhiêu")

        assert result["question_type"] == "cần_làm_rõ"
        assert result["clarification_question"] is not None, (
            "Phải có clarification_question khi cần_làm_rõ"
        )
        assert result["crop"] is None

    def test_specific_crop_identified(self):
        """Khi câu hỏi rõ ràng, router phải xác định đúng crop."""
        from backend.router.query_router import route_question
        import json

        mock_response = json.dumps(VALID_ROUTER_RESPONSE_WITH_CROP)
        with patch('backend.router.query_router.call_with_rotation',
                   return_value=mock_response):
            result = route_question("liều lượng phân bón cho lúa Đông Xuân đất phèn nhẹ")

        assert result["crop"] == "lúa"
        assert result["season"] == "Đông Xuân"
        assert result["soil_type"] == "phèn nhẹ"
        assert result["growth_stage"] == "đẻ_nhánh"


# ─── Test: Growth Stage ────────────────────────────────────────────────────

class TestRouterGrowthStage:
    """GĐ1 Mục 1: growth_stage phải luôn có trong response."""

    def test_growth_stage_in_all_responses(self):
        """Tất cả response từ router phải có key growth_stage."""
        from backend.router.query_router import route_question
        from backend.utils.gemini_client import AllKeysExhaustedError

        # Test fallback response
        with patch('backend.router.query_router.call_with_rotation',
                   side_effect=AllKeysExhaustedError("test")):
            result = route_question("test question")

        assert "growth_stage" in result, "growth_stage phải luôn có trong response"

    def test_backward_compat_no_growth_stage_from_gemini(self):
        """Nếu Gemini cũ không trả growth_stage, hệ thống phải set None."""
        from backend.router.query_router import route_question
        import json

        # Response không có growth_stage (Gemini cũ)
        old_response = json.dumps({
            "question_type": "định_lượng",
            "crop": "cà phê",
            "season": None,
            "soil_type": "đất đỏ",
            "variety": None,
            "topic_keywords": ["tưới"],
            "confidence": "high",
            "clarification_question": None,
        })
        with patch('backend.router.query_router.call_with_rotation',
                   return_value=old_response):
            result = route_question("lượng nước tưới cà phê trên đất đỏ")

        assert "growth_stage" in result, "Backward compat: phải thêm growth_stage=None"
        assert result["growth_stage"] is None


# ─── Test: IAM Authorization ─────────────────────────────────────────────

class TestIAMAuthorization:
    """GĐ1 Mục 2: Kiểm tra IAM/Farm authorization."""

    def test_cross_farm_access_denied(self):
        """User không được truy cập farm ngoài phạm vi."""
        from backend.iam.iam import build_farm_context, check_farm_access

        ctx = build_farm_context("farmer_a", "1", "user")
        # farmer_a chỉ có farm_001, thử truy cập farm_003
        result = check_farm_access(ctx, "farm_003", "get_latest_sensor")
        assert result.allowed is False, "Cross-farm access phải bị từ chối"
        assert "không có quyền" in result.reason.lower() or "deny" in result.reason.lower()

    def test_authorized_farm_access_allowed(self):
        """User được truy cập farm trong phạm vi."""
        from backend.iam.iam import build_farm_context, check_farm_access

        ctx = build_farm_context("farmer_a", "1", "user")
        result = check_farm_access(ctx, "farm_001", "get_latest_sensor")
        assert result.allowed is True, "Authorized farm access phải được chấp nhận"

    def test_admin_can_access_any_farm(self):
        """Admin có quyền truy cập mọi farm."""
        from backend.iam.iam import build_farm_context, check_farm_access

        ctx = build_farm_context("admin", "0", "admin")
        result = check_farm_access(ctx, "farm_999", "get_latest_sensor")
        assert result.allowed is True, "Admin phải có quyền truy cập mọi farm"

    def test_empty_farm_id_denied(self):
        """farm_id rỗng phải bị từ chối — LLM không được tự sinh farm_id."""
        from backend.iam.iam import build_farm_context, check_farm_access

        ctx = build_farm_context("farmer_a", "1", "user")
        result = check_farm_access(ctx, "", "get_latest_sensor")
        assert result.allowed is False, "farm_id rỗng phải bị từ chối"

    def test_require_farm_access_raises_on_deny(self):
        """require_farm_access phải raise PermissionError khi bị từ chối."""
        from backend.iam.iam import build_farm_context, require_farm_access

        ctx = build_farm_context("farmer_a", "1", "user")
        with pytest.raises(PermissionError):
            require_farm_access(ctx, "farm_999", "get_latest_sensor")


# ─── Test: Fail-Closed Numeric Match ────────────────────────────────────

class TestFailClosedNumericMatch:
    """GĐ1 Mục 4: Fail-closed cho dữ liệu rủi ro."""

    def test_high_risk_attribute_without_condition_denied(self):
        """Dữ liệu rủi ro thiếu điều kiện phải trả requires_clarification=True."""
        from backend.layers.layer1_facts import get_fact

        # "liều lượng phân bón" là dữ liệu rủi ro, không có season/soil/growth_stage
        result = get_fact(
            attribute="liều lượng phân bón",
            crop="lúa",
            season=None,
            soil_type=None,
            growth_stage=None,
        )
        assert result.get("requires_clarification") is True, (
            "Dữ liệu rủi ro thiếu điều kiện phải trả requires_clarification=True"
        )
        assert result["found"] is False
        assert result["warning"] is not None

    def test_normal_attribute_allows_partial_match(self):
        """Dữ liệu không rủi ro vẫn cho phép partial match."""
        from backend.layers.layer1_facts import get_fact

        # Mock DB trả về partial result
        with patch('backend.layers.layer1_facts._query_facts') as mock_q:
            # strict=True trả về [], strict=False trả về 1 kết quả
            mock_q.side_effect = lambda attr, crop, season, soil_type, growth_stage, strict: (
                [] if strict else [{"attribute": "năng suất", "value": "5", "unit": "tấn/ha",
                                    "condition_note": "", "source_document_id": "doc_001"}]
            )
            result = get_fact(
                attribute="năng suất",
                crop="lúa",
                season="Đông Xuân",
                soil_type=None,
                growth_stage=None,
            )

        assert result.get("requires_clarification") is not True, (
            "Dữ liệu không rủi ro phải cho phép partial match"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
