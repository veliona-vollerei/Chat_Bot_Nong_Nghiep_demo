"""
Cấu hình tập trung — phiên bản KHÔNG có Neo4j.
Dùng ChromaDB (vector store) + PostgreSQL (facts + KG triples).
"""
import os
from pathlib import Path
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env")

# === Gemini ===
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")  # Phải điền vào .env
GEMINI_ROUTER_MODEL = os.getenv("GEMINI_ROUTER_MODEL", "gemini-3.1-flash-lite")
GEMINI_SYNTHESIS_MODEL = os.getenv("GEMINI_SYNTHESIS_MODEL", "gemini-3.5-flash")

# === PostgreSQL (Tầng 1 + Tầng 2 KG) ===
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "chatbot_nongnghiep")
POSTGRES_URL = (
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

# === ChromaDB (Tầng 3 - thay Neo4j Vector) ===
# Lưu dữ liệu local, không cần server
CHROMA_PERSIST_DIR = str(BASE_DIR / "chroma_db")
CHROMA_COLLECTION_NAME = "nongnghiep_chunks"

# === Embedding ===
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-large")
EMBEDDING_DIMENSION = 1024  # dimension của multilingual-e5-large

# === App ===
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
DEBUG = os.getenv("DEBUG", "true").lower() == "true"

# === Paths ===
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
CHUNKS_FILE = BASE_DIR / "chunks_clean.json"
ENRICHED_CHUNKS_FILE = DATA_DIR / "chunks_enriched.json"

# === Model Cache ===
MODEL_CACHE_DIR = BASE_DIR / ".model_cache"
MODEL_CACHE_DIR.mkdir(exist_ok=True)


def validate_config():
    errors = []
    if not GEMINI_API_KEY or "your_" in GEMINI_API_KEY:
        errors.append("GEMINI_API_KEY chưa được điền vào .env")
    if not POSTGRES_PASSWORD or "your_" in POSTGRES_PASSWORD:
        errors.append("POSTGRES_PASSWORD chưa được điền vào .env")
    return errors


if __name__ == "__main__":
    errors = validate_config()
    if errors:
        print("❌ Lỗi cấu hình:")
        for e in errors:
            print(f"  - {e}")
    else:
        print("✅ Cấu hình OK!")
        print(f"  Postgres : {POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}")
        print(f"  ChromaDB : {CHROMA_PERSIST_DIR}")
        print(f"  Embedding: {EMBEDDING_MODEL}")
