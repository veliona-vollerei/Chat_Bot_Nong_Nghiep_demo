"""
conftest.py — Setup môi trường test cho toàn bộ backend/tests/.

Stub các module nặng (google.genai, psycopg2, ChromaDB, ML) TRƯỚC khi
bất kỳ test module nào được import. Điều này đảm bảo test isolation
dù pytest chạy các file theo bất kỳ thứ tự nào.

Quy tắc:
- Chỉ stub những module thực sự không có sẵn trong test environment
- Không mock business logic — mock chỉ ở tầng infrastructure
"""
import sys
import types
from unittest.mock import MagicMock


def _register_if_absent(module_name: str, module: types.ModuleType):
    if module_name not in sys.modules:
        sys.modules[module_name] = module


# ─── google.genai ─────────────────────────────────────────────────────────────
_google = types.ModuleType("google")
_genai = types.ModuleType("google.genai")
_genai.Client = MagicMock
_google.genai = _genai
_register_if_absent("google", _google)
_register_if_absent("google.genai", _genai)

# ─── backend.utils.gemini_client ─────────────────────────────────────────────
# QUAN TRỌNG: AllKeysExhaustedError phải là class THẬT (subclass của Exception)
# để validator.py catch được. Dùng chung 1 class duy nhất cho toàn suite.
if "backend.utils.gemini_client" not in sys.modules:
    _gclient = types.ModuleType("backend.utils.gemini_client")

    class AllKeysExhaustedError(Exception):
        """Stub: tất cả Gemini API keys đã hết quota."""
        pass

    _gclient.AllKeysExhaustedError = AllKeysExhaustedError
    _gclient.call_with_rotation = MagicMock(return_value="{}")
    _gclient.key_manager = None
    sys.modules["backend.utils.gemini_client"] = _gclient

# ─── backend.config ───────────────────────────────────────────────────────────
if "backend.config" not in sys.modules:
    _cfg = types.ModuleType("backend.config")
    _cfg.GEMINI_FALLBACK_MODEL = "gemini-test"
    _cfg.GEMINI_ROUTER_MODEL = "gemini-test"
    _cfg.GEMINI_SYNTHESIS_MODEL = "gemini-test"
    _cfg.EMBEDDING_MODEL = "test-model"
    _cfg.MODEL_CACHE_DIR = "/tmp"
    sys.modules["backend.config"] = _cfg

# ─── psycopg2 ─────────────────────────────────────────────────────────────────
_register_if_absent("psycopg2", types.ModuleType("psycopg2"))

# ─── backend.db.postgres ──────────────────────────────────────────────────────
if "backend.db.postgres" not in sys.modules:
    _pg = types.ModuleType("backend.db.postgres")
    _pg.get_cursor = MagicMock()
    sys.modules["backend.db.postgres"] = _pg

# ─── backend.db.chroma_db ─────────────────────────────────────────────────────
if "backend.db.chroma_db" not in sys.modules:
    _chroma = types.ModuleType("backend.db.chroma_db")
    _mock_col = MagicMock()
    _mock_col.count.return_value = 0
    _chroma.get_collection = MagicMock(return_value=_mock_col)
    sys.modules["backend.db.chroma_db"] = _chroma

# ─── sentence_transformers ────────────────────────────────────────────────────
if "sentence_transformers" not in sys.modules:
    _st = types.ModuleType("sentence_transformers")
    _st.SentenceTransformer = MagicMock
    sys.modules["sentence_transformers"] = _st

# ─── rank_bm25 ────────────────────────────────────────────────────────────────
if "rank_bm25" not in sys.modules:
    _bm25 = types.ModuleType("rank_bm25")
    _bm25.BM25Okapi = MagicMock
    sys.modules["rank_bm25"] = _bm25
