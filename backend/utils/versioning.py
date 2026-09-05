"""
Versioning toàn hệ thống — Mục 13 GĐ1.

Gắn version vào mọi log lỗi để phục vụ debug và rollback.
Bao gồm:
- SYSTEM_VERSION: phiên bản chatbot
- TOOL_API_CONTRACT_VERSION: schema Tool/API giữa chatbot và NextFarm IoT Service
- ROUTER_PROMPT_VERSION: version logic router/prompt
- RAG_CORPUS_VERSION: version corpus RAG (tài liệu đã duyệt)
"""
from datetime import datetime, timezone

# ─── Version constants ──────────────────────────────────────────────────────
SYSTEM_VERSION = "2.2.0"

# Version của Tool/API contract giữa chatbot và IoT Service NextFarm
# Tăng khi schema response thay đổi — tránh lỗi âm thầm
TOOL_API_CONTRACT_VERSION = "1.0.0"

# Version của router/prompt logic — truy vết lỗi phát sinh từ bản nào
ROUTER_PROMPT_VERSION = "1.1.0"  # v1.1.0: bỏ crop='lúa' mặc định, thêm growth_stage

# Version của RAG document corpus — biết tài liệu nào đã duyệt ở version nào
RAG_CORPUS_VERSION = "1.0.0"

# Thời điểm khởi động hệ thống (UTC)
SYSTEM_START_TIME = datetime.now(timezone.utc).isoformat()


def get_version_context() -> dict:
    """
    Trả về dict version đầy đủ để gắn vào log.
    Gọi trong mọi request log để phục vụ debug/rollback.
    """
    return {
        "system_version": SYSTEM_VERSION,
        "tool_api_contract": TOOL_API_CONTRACT_VERSION,
        "router_prompt": ROUTER_PROMPT_VERSION,
        "rag_corpus": RAG_CORPUS_VERSION,
    }


def version_log_prefix() -> str:
    """
    Trả về prefix ngắn gọn để đính kèm trong log line.
    Ví dụ: "[sys=2.2.0 router=1.1.0 corpus=1.0.0]"
    """
    return (
        f"[sys={SYSTEM_VERSION} router={ROUTER_PROMPT_VERSION} "
        f"corpus={RAG_CORPUS_VERSION} tool_api={TOOL_API_CONTRACT_VERSION}]"
    )
