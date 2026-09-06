"""
LLM Router — phân loại câu hỏi và trích xuất thực thể.

Dùng Gemini để:
1. Trích xuất: crop, season, soil_type, growth_stage, question_type
2. Quyết định tầng nào xử lý
3. Hỏi lại nếu câu hỏi quá mơ hồ

question_type ∈ {
    "định_lượng"       → Tầng 1 (số liệu cụ thể: liều lượng, hệ số)
    "phù_hợp/quan_hệ"  → Tầng 2 (giống nào phù hợp, quan hệ giữa các thực thể)
    "diễn_giải"        → Tầng 3 (giải thích kỹ thuật, quy trình)
    "ngoài_phạm_vi"    → Từ chối (cây trồng khác, giá cả, tín dụng...)
    "cần_làm_rõ"       → Hỏi lại (quá mơ hồ)
}

CHANGELOG:
    v1.1.0 (GĐ1 Mục 1): Bỏ crop='lúa' mặc định trong fallback. Thêm growth_stage.
            Khi router không xác định crop → None (không suy diễn).
    v1.2.0 (GĐ3 Router): Thêm fast-path rule-based (Layer 0-4) trước Gemini.
            Học từ RAG-and-Agent: 0 API call cho câu rõ ràng, <5ms fast-path.
            Ghi reason_code/decision_path vào mọi quyết định để audit được.
"""
import json
import logging
from typing import Optional
# pyrefly: ignore [missing-import]
from google import genai
from backend.config import GEMINI_ROUTER_MODEL, GEMINI_SYNTHESIS_MODEL, GEMINI_FALLBACK_MODEL
from backend.utils.gemini_client import call_with_rotation, AllKeysExhaustedError

logger = logging.getLogger(__name__)

ROUTER_PROMPT = """Bạn là hệ thống phân loại câu hỏi nông nghiệp. Phân tích câu hỏi của nông dân và trả về JSON.

{history_context}

CÂU HỎI HIỆN TẠI: {question}

LƯU Ý NGỮ CẢNH:
- Nếu câu hỏi hiện tại là câu hỏi nối tiếp hoặc chứa đại từ thay thế (ví dụ: "thế còn vụ Hè Thu?", "giống này có chịu phèn không?", "liều lượng thế nào?"), hãy dùng LỊCH SỬ HỘI THOẠI ở trên để xác định đầy đủ các thực thể (loại đất, mùa vụ, giống lúa, từ khóa chủ đề).

Phạm vi hệ thống: toàn bộ ngành nông nghiệp, hỗ trợ đa dạng nông sản (lúa, cà phê, dưa hấu, sầu riêng, cam, bưởi, xoài, rau màu, gia súc, kỹ thuật nông nghiệp tổng quát, v.v.).

Phân loại:
- "định_lượng": hỏi về số liệu cụ thể (liều lượng phân bón, năng suất, mật độ, hệ số...)
- "phù_hợp/quan_hệ": hỏi cái gì phù hợp/thích hợp với điều kiện nào, quan hệ nông sản - sâu bệnh - mùa vụ - loại đất
- "diễn_giải": hỏi giải thích khái niệm, quy trình, kỹ thuật canh tác, bảo quản, quản lý nông sản
- "tiền_đề_sai": hỏi về nông nghiệp nhưng gắn với điều kiện, địa danh, thời gian phi thực tế (ví dụ: trồng lúa trên sao Hỏa, sao Kim, năm 2050, v.v.)
- "ngoài_phạm_vi": hoàn toàn không liên quan đến ngành nông nghiệp (bất động sản, du lịch, giải trí...)
- "cần_làm_rõ": quá mơ hồ, không đủ thông tin để tra cứu

QUY TẮC TRÍCH XUẤT crop:
- Chỉ điền khi chắc chắn nhận dạng được từ câu hỏi hoặc lịch sử hội thoại
- Nếu không rõ hoặc câu hỏi mơ hồ → trả về null (TUYỆT ĐỐI không suy đoán)
- Dùng 'nông nghiệp tổng quát' khi câu hỏi áp dụng cho nhiều cây trồng

Trả về JSON (CHỈ JSON, không thêm markdown hay text khác):
{{
  "question_type": "<phân loại>",
  "crop": "<tên cây trồng/nông sản, 'nông nghiệp tổng quát', hoặc null nếu không xác định>",
  "season": "<Đông Xuân | Hè Thu | Mùa | null>",
  "soil_type": "<phù sa | phèn nhẹ | phèn trung bình | phèn nặng | mặn | đất đỏ | null>",
  "growth_stage": "<mạ | đẻ_nhánh | làm_đòng | trổ_bông | chín | null — giai đoạn sinh trưởng nếu câu hỏi định lượng>",
  "variety": "<tên giống nếu có, hoặc null>",
  "topic_keywords": ["<từ khóa chính của câu hỏi>"],
  "confidence": "<high | medium | low>",
  "clarification_question": "<câu hỏi lại nếu question_type là 'cần_làm_rõ' — xưng là 'Tôi', gọi người hỏi là 'Bạn'; ngược lại null>"
}}"""

SYNTHESIS_PROMPT = """Bạn là trợ lý tư vấn nông nghiệp. Tổng hợp câu trả lời từ dữ liệu sau.

CÂU HỎI CỦA NÔNG DÂN: {question}

DỮ LIỆU TỪ HỆ THỐNG (đây là dữ liệu thật, không phải do AI tạo ra):
{data}

NGUỒN: {source}

YÊU CẦU BẮT BUỘC:
1. CHỈ sử dụng thông tin từ "DỮ LIỆU TỪ HỆ THỐNG" ở trên — TUYỆT ĐỐI không thêm thông tin ngoài
2. Không tự tạo ra số liệu mới
3. Viết bằng tiếng Việt dễ hiểu cho nông dân
4. Nếu dữ liệu có cờ cảnh báo → nói rõ là số liệu chung, chưa chính xác cho điều kiện cụ thể
5. Luôn trích dẫn nguồn ở cuối câu trả lời
6. Câu trả lời ngắn gọn, thực tế, không dùng thuật ngữ khó
7. XƯNG HÔ: luôn tự xưng là "Tôi", gọi người hỏi là "Bạn" — TUYỆT ĐỐI không dùng "mình", "em", "bạn ơi" hay bất kỳ cách xưng hô khác

Trả lời:"""


def route_question(
    question: str,
    history: Optional[list] = None,
    conversation_id: Optional[str] = None,
) -> dict:
    """
    Phân loại câu hỏi bằng Gemini Router.

    Returns:
        {
            "question_type": str,
            "crop": str | None,       # None nếu không xác định — KHÔNG mặc định 'lúa'
            "season": str | None,
            "soil_type": str | None,
            "growth_stage": str | None,   # GĐ1 Mục 1: thêm mới
            "variety": str | None,
            "topic_keywords": list,
            "confidence": str,
            "clarification_question": str | None,
            "error": str | None
        }
    """
    try:
        history_context = ""
        if history:
            formatted_h = []
            for msg in history[-4:]:  # lấy tối đa 4 lượt tin nhắn gần nhất
                role = "Nông dân" if msg.get("sender") == "user" or msg.get("role") == "user" else "Trợ lý"
                content = msg.get("content", "")
                formatted_h.append(f"{role}: {content}")
            if formatted_h:
                history_context = "LỊCH SỬ HỘI THOẠI GẦN ĐÂY:\n" + "\n".join(formatted_h)

        prompt = ROUTER_PROMPT.format(question=question, history_context=history_context)

        def _call_router(client: genai.Client) -> str:
            response = client.models.generate_content(
                model=GEMINI_ROUTER_MODEL,
                contents=prompt,
                config={
                    "temperature": 0.1,
                    "max_output_tokens": 512,
                    "response_mime_type": "application/json",
                }
            )
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                try:
                    from backend.monitoring import record_gemini_usage
                    record_gemini_usage(
                        model=GEMINI_ROUTER_MODEL,
                        prompt_tokens=getattr(response.usage_metadata, "prompt_token_count", 0) or 0,
                        candidate_tokens=getattr(response.usage_metadata, "candidates_token_count", 0) or 0,
                        conversation_id=conversation_id,
                    )
                except Exception:
                    pass
            return response.text.strip()

        text = call_with_rotation(_call_router)

        # Parse JSON response
        # Xử lý nếu Gemini wrap trong markdown code block
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]

        result = json.loads(text)
        result["error"] = None

        # GĐ1 Mục 1: Đảm bảo growth_stage luôn có trong kết quả (backward compat)
        if "growth_stage" not in result:
            result["growth_stage"] = None

        # GĐ1 Mục 1: crop=None hoặc chuỗi rỗng → soft retrieval, không lock crop
        if not result.get("crop") or result["crop"].strip() == "":
            result["crop"] = None

        return result

    except AllKeysExhaustedError as e:
        # GĐ1 Mục 1: crop=None thay vì 'lúa' — không suy đoán khi API lỗi
        logger.error(f"Router AllKeysExhausted: {e}")
        return {
            "question_type": "diễn_giải",
            "crop": None,            # KHÔNG mặc định 'lúa'
            "season": None,
            "soil_type": None,
            "growth_stage": None,
            "variety": None,
            "topic_keywords": [question[:50]],
            "confidence": "low",
            "clarification_question": None,
            "error": f"Tất cả Gemini API keys đều không khả dụng: {e}"
        }
    except json.JSONDecodeError as e:
        # GĐ1 Mục 1: crop=None thay vì 'lúa' — không suy đoán khi parse lỗi
        logger.error(f"Router JSON parse error: {e}")
        return {
            "question_type": "diễn_giải",
            "crop": None,            # KHÔNG mặc định 'lúa'
            "season": None,
            "soil_type": None,
            "growth_stage": None,
            "variety": None,
            "topic_keywords": [question[:50]],
            "confidence": "low",
            "clarification_question": None,
            "error": f"Parse error: {e}"
        }
    except Exception as e:
        # GĐ1 Mục 1: crop=None thay vì 'lúa' — không suy đoán khi lỗi bất kỳ
        logger.error(f"Router error: {e}")
        return {
            "question_type": "diễn_giải",
            "crop": None,            # KHÔNG mặc định 'lúa'
            "season": None,
            "soil_type": None,
            "growth_stage": None,
            "variety": None,
            "topic_keywords": [],
            "confidence": "low",
            "clarification_question": None,
            "error": str(e)
        }


def synthesize_answer(
    question: str,
    data: str,
    source: str,
    conversation_id: Optional[str] = None,
) -> str:
    """
    Dùng Gemini để diễn giải lại dữ liệu thành câu trả lời tự nhiên.
    Tự động xoay vòng key khi gặp lỗi rate limit / quota exceeded.
    """
    prompt = SYNTHESIS_PROMPT.format(
        question=question,
        data=data,
        source=source
    )

    def _call_synthesis(client: genai.Client) -> str:
        response = client.models.generate_content(
            model=GEMINI_SYNTHESIS_MODEL,
            contents=prompt,
            config={
                "temperature": 0.2,
            }
        )
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            try:
                from backend.monitoring import record_gemini_usage
                record_gemini_usage(
                    model=GEMINI_SYNTHESIS_MODEL,
                    prompt_tokens=getattr(response.usage_metadata, "prompt_token_count", 0) or 0,
                    candidate_tokens=getattr(response.usage_metadata, "candidates_token_count", 0) or 0,
                    conversation_id=conversation_id,
                )
            except Exception:
                pass
        return response.text.strip()

    try:
        return call_with_rotation(
            _call_synthesis,
            server_error_retries=3,
            server_error_backoff=(3, 6, 10),
        )
    except AllKeysExhaustedError as e:
        logger.error(f"Synthesis AllKeysExhausted: {e}")
        return "Xin lỗi, hệ thống đang bận do hạn mức API. Vui lòng thử lại sau vài giây."
    except Exception as e:
        logger.error(f"Synthesis error: {e}")
        return "Xin lỗi, đã xảy ra lỗi khi xử lý câu trả lời. Vui lòng thử lại."


def route_question_with_fast_path(
    question: str,
    history: Optional[list] = None,
    conversation_id: Optional[str] = None,
    farm_id: Optional[str] = None,
    zone_id: Optional[str] = None,
) -> dict:
    """
    Router đa tầng: thử fast-path rule-based trước, fallback Gemini khi cần.

    Kiến trúc học từ RAG-and-Agent (kavsir):
    - Câu hỏi rõ ràng → fast-path <5ms, 0 Gemini call
    - Câu hỏi mơ hồ → fallback sang Gemini như cũ

    Returns: dict (giống route_question), có thêm:
        "decision_path": str  — audit trail (fast_path/gemini)
        "reason_code": str    — lý do quyết định
    """
    from backend.router.fast_path_router import try_fast_path

    # ─── Thử fast-path trước ──────────────────────────────────────────
    fast_result = try_fast_path(question, history=history, farm_id=farm_id, zone_id=zone_id)
    if fast_result is not None:
        logger.info(
            f"[FastPath] {fast_result.get('decision_path')} | "
            f"type={fast_result.get('question_type')} | "
            f"reason={fast_result.get('reason_code')}"
        )
        return fast_result

    # ─── Fallback: Gemini router ──────────────────────────────────────
    logger.debug(f"[FastPath] No rule matched → calling Gemini router")
    result = route_question(question, history=history, conversation_id=conversation_id)

    # Gắn thêm decision_path và reason_code cho audit
    result.setdefault("decision_path", "gemini_router")
    result.setdefault("reason_code", "NO_FAST_PATH_MATCH")

    return result

