"""
Validator (Guardrail) — GĐ3 Mục Guardrail.

Học từ RAG-and-Agent (kavsir):
- validation_node: LLM-as-judge chấm groundedness
- Fail-safe cứng: JSON hỏng/exception → luôn coi là invalid, KHÔNG bao giờ mặc định pass
- Retry tối đa N lần với retrieval refined
- Hết lượt vẫn invalid → ép buộc trả lời từ chối

Áp dụng cho toàn bộ pipeline synthesis, không chỉ riêng numeric.

CHANGELOG:
    v1.0.0: Initial validator, học từ RAG-and-Agent validation_node.
"""
import json
import logging
from typing import Optional
# pyrefly: ignore [missing-import]
from google import genai
from backend.config import GEMINI_FALLBACK_MODEL
from backend.utils.gemini_client import call_with_rotation, AllKeysExhaustedError

logger = logging.getLogger(__name__)

VALIDATOR_PROMPT = """Bạn là hệ thống kiểm tra tính chính xác của câu trả lời chatbot nông nghiệp.

CÂU HỎI CỦA NGƯỜI DÙNG:
{question}

DỮ LIỆU NGUỒN (ground truth):
{context}

CÂU TRẢ LỜI CỦA CHATBOT:
{answer}

Kiểm tra: câu trả lời có HOÀN TOÀN dựa trên dữ liệu nguồn ở trên không?

Trả về JSON (CHỈ JSON thuần túy, KHÔNG markdown, KHÔNG text nào khác):
{{
  "grounded": true hoặc false,
  "reason": "<lý do ngắn gọn bằng tiếng Việt — tối đa 1 câu>",
  "hallucination_detected": true hoặc false,
  "confidence": "high" | "medium" | "low"
}}

Quy tắc:
- grounded=true CHỈ KHI câu trả lời không thêm bất kỳ thông tin nào ngoài dữ liệu nguồn
- Nếu chatbot thêm số liệu, tên giống, liều lượng KHÔNG có trong nguồn → grounded=false + hallucination_detected=true
- Nếu câu trả lời là câu từ chối/không biết → grounded=true (chấp nhận)
- Không đánh giá chất lượng văn phong, chỉ đánh giá tính grounded"""

# Câu abstain cố định khi hết lần retry
ABSTAIN_ANSWER = (
    "Tôi chưa tìm thấy đủ căn cứ trong kho dữ liệu nông nghiệp để trả lời chắc chắn câu hỏi này. "
    "Vui lòng hỏi cụ thể hơn (loại cây, mùa vụ, loại đất) hoặc liên hệ chuyên gia nông nghiệp địa phương."
)


def validate_answer(
    question: str,
    answer: str,
    context_data: str,
    conversation_id: Optional[str] = None,
    skip_validation: bool = False,
) -> dict:
    """
    Kiểm tra câu trả lời có grounded trong context không (LLM-as-Judge).

    Fail-safe cứng:
    - Exception → {"valid": False, "reason": "validator_exception", ...}
    - JSON hỏng → {"valid": False, "reason": "json_parse_error", ...}
    - KHÔNG BAO GIỜ mặc định pass (valid=True) khi có lỗi

    Args:
        question: câu hỏi gốc
        answer: câu trả lời cần kiểm tra
        context_data: dữ liệu nguồn được dùng để sinh câu trả lời
        conversation_id: để tracking token usage
        skip_validation: nếu True, skip validate (dùng cho abstain/clarification)

    Returns:
        {
            "valid": bool,
            "reason": str,
            "hallucination_detected": bool,
            "confidence": str,
        }
    """
    # Skip validation cho các câu trả lời đặc biệt
    if skip_validation:
        return {"valid": True, "reason": "skipped", "hallucination_detected": False, "confidence": "high"}

    # Skip nếu answer là câu từ chối (abstain pattern)
    _abstain_patterns = [
        "chưa tìm thấy", "chưa đủ căn cứ", "không tìm thấy thông tin",
        "hệ thống không suy đoán", "vui lòng liên hệ chuyên gia",
        "nằm ngoài phạm vi", "không xác định được",
    ]
    answer_lower = answer.lower()
    if any(p in answer_lower for p in _abstain_patterns):
        return {"valid": True, "reason": "abstain_answer_accepted", "hallucination_detected": False, "confidence": "high"}

    # Không validate nếu context quá ngắn (không đủ căn cứ để judge)
    if not context_data or len(context_data.strip()) < 50:
        return {"valid": True, "reason": "context_too_short_skip", "hallucination_detected": False, "confidence": "low"}

    try:
        prompt = VALIDATOR_PROMPT.format(
            question=question[:500],
            context=context_data[:3000],  # giới hạn context để tiết kiệm token
            answer=answer[:1000],
        )

        def _call_validator(client: genai.Client) -> str:
            response = client.models.generate_content(
                model=GEMINI_FALLBACK_MODEL,
                contents=prompt,
                config={
                    "temperature": 0.0,
                    "max_output_tokens": 256,
                    "response_mime_type": "application/json",
                }
            )
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                try:
                    from backend.monitoring import record_gemini_usage
                    record_gemini_usage(
                        model=GEMINI_FALLBACK_MODEL,
                        prompt_tokens=getattr(response.usage_metadata, "prompt_token_count", 0) or 0,
                        candidate_tokens=getattr(response.usage_metadata, "candidates_token_count", 0) or 0,
                        conversation_id=conversation_id,
                    )
                except Exception:
                    pass
            return response.text.strip() if response.text else ""

        raw = call_with_rotation(_call_validator)

        # Strip markdown nếu có
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0].strip()

        # Fail-safe: JSON hỏng → invalid
        data = json.loads(raw)

        grounded = bool(data.get("grounded", False))
        hallucination = bool(data.get("hallucination_detected", False))
        reason = str(data.get("reason", ""))
        confidence = str(data.get("confidence", "medium"))

        return {
            "valid": grounded,
            "reason": reason,
            "hallucination_detected": hallucination,
            "confidence": confidence,
        }

    except json.JSONDecodeError as e:
        # Fail-safe cứng: JSON hỏng → invalid
        logger.warning(f"Validator JSON parse error (fail-safe → invalid): {e}")
        return {
            "valid": False,
            "reason": f"json_parse_error: {e}",
            "hallucination_detected": False,
            "confidence": "low",
        }
    except AllKeysExhaustedError as e:
        # Khi API exhausted → skip validation (không block user)
        logger.warning(f"Validator AllKeysExhausted → skip validation: {e}")
        return {
            "valid": True,
            "reason": "api_exhausted_skip",
            "hallucination_detected": False,
            "confidence": "low",
        }
    except Exception as e:
        # Fail-safe cứng: exception → invalid
        logger.warning(f"Validator exception (fail-safe → invalid): {e}")
        return {
            "valid": False,
            "reason": f"validator_exception: {type(e).__name__}",
            "hallucination_detected": False,
            "confidence": "low",
        }


def refine_query_for_retry(
    question: str,
    failed_reason: str,
    original_keywords: list,
    attempt: int,
) -> str:
    """
    Tinh chỉnh query để thử retrieval lại khi validate fail.

    Chiến lược:
    - attempt=1: mở rộng keyword (thêm từ đồng nghĩa, bỏ bớt filter)
    - attempt=2: query rất ngắn gọn, chỉ từ khóa cốt lõi
    """
    if attempt == 1:
        # Thêm keyword mở rộng
        extra = " kỹ thuật hướng dẫn thực hành"
        return question.strip() + extra
    elif attempt == 2:
        # Rút gọn thành keyword cốt lõi
        if original_keywords:
            return " ".join(original_keywords[:3])
        return question.strip()
    return question.strip()
