"""
Test Validator (Guardrail) — regression test cho lỗi #2.

Khi hết quota Gemini (AllKeysExhaustedError), validator PHẢI trả valid=False
(fail-closed), không trả valid=True (tắt guardrail lúc hệ thống suy giảm).

Note: google.genai, backend.utils.gemini_client, backend.config được stub
bởi conftest.py — không cần setup lại ở đây.
"""
import sys
import unittest
from unittest.mock import MagicMock


def _get_allkeys_error():
    """Lấy AllKeysExhaustedError từ module đã stub trong conftest."""
    return sys.modules["backend.utils.gemini_client"].AllKeysExhaustedError


class TestValidatorFailClosed(unittest.TestCase):
    """Regression tests cho lỗi #2: AllKeysExhaustedError phải fail-closed."""

    def _fresh_validate(self, patch_call=None, **kwargs):
        """Import validator fresh, optionally patch call_with_rotation trực tiếp."""
        if "backend.validator" in sys.modules:
            del sys.modules["backend.validator"]
        import backend.validator as val
        if patch_call is not None:
            original = val.call_with_rotation
            val.call_with_rotation = patch_call
            try:
                result = val.validate_answer(**kwargs)
            finally:
                val.call_with_rotation = original
            return result
        return val.validate_answer(**kwargs)

    def test_api_exhausted_returns_valid_false(self):
        """
        AllKeysExhaustedError → valid=False (fail-closed).
        Trước khi sửa: trả valid=True — tắt guardrail lúc hệ thống suy giảm.
        """
        AllKeysExhaustedError = _get_allkeys_error()
        mock_call = MagicMock(side_effect=AllKeysExhaustedError("quota"))
        result = self._fresh_validate(
            patch_call=mock_call,
            question="liều lượng phân đạm cho lúa?",
            answer="Bón 100 kg/ha đạm urê.",
            context_data="X" * 100,
        )
        self.assertFalse(
            result["valid"],
            f"AllKeysExhaustedError PHẢI trả valid=False. "
            f"Nhận: valid={result['valid']}, reason={result['reason']}. Lỗi #2 tái diễn!"
        )
        self.assertEqual(result["reason"], "api_exhausted_fail_closed")

    def test_json_parse_error_still_fail_closed(self):
        """JSON hỏng → vẫn fail-closed."""
        mock_call = MagicMock(return_value="{ invalid json }")
        result = self._fresh_validate(
            patch_call=mock_call,
            question="test", answer="test answer", context_data="X" * 100,
        )
        self.assertFalse(result["valid"])
        self.assertIn("json_parse_error", result["reason"])

    def test_generic_exception_fail_closed(self):
        """Exception khác → vẫn fail-closed."""
        mock_call = MagicMock(side_effect=RuntimeError("network error"))
        result = self._fresh_validate(
            patch_call=mock_call,
            question="q", answer="a", context_data="X" * 100,
        )
        self.assertFalse(result["valid"])
        self.assertIn("validator_exception", result["reason"])


class TestValidatorSkipCases(unittest.TestCase):
    """Test các trường hợp skip validation hợp lệ — không cần API call."""

    def _fresh_validate(self, **kwargs):
        if "backend.validator" in sys.modules:
            del sys.modules["backend.validator"]
        from backend.validator import validate_answer
        return validate_answer(**kwargs)

    def test_skip_validation_flag(self):
        """skip_validation=True → valid=True không gọi API."""
        result = self._fresh_validate(
            question="q", answer="a", context_data="ctx", skip_validation=True
        )
        self.assertTrue(result["valid"])
        self.assertEqual(result["reason"], "skipped")

    def test_abstain_answer_accepted(self):
        """Câu trả lời từ chối → accepted mà không gọi LLM judge."""
        result = self._fresh_validate(
            question="test",
            answer="Tôi chưa tìm thấy thông tin phù hợp trong kho dữ liệu.",
            context_data="ctx",
        )
        self.assertTrue(result["valid"])
        self.assertEqual(result["reason"], "abstain_answer_accepted")

    def test_context_too_short_skip(self):
        """Context quá ngắn → skip với confidence=low."""
        result = self._fresh_validate(
            question="q", answer="a", context_data="short ctx"
        )
        self.assertTrue(result["valid"])
        self.assertEqual(result["reason"], "context_too_short_skip")
        self.assertEqual(result["confidence"], "low")


if __name__ == "__main__":
    unittest.main()
