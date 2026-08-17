"""
ChromaDB client — thay thế Neo4j Vector.

ChromaDB chạy hoàn toàn local, lưu file vào thư mục chroma_db/,
không cần cài server hay tạo tài khoản.
"""
# pyrefly: ignore [missing-import]
import chromadb
# pyrefly: ignore [missing-import]
from chromadb.config import Settings
from backend.config import CHROMA_PERSIST_DIR, CHROMA_COLLECTION_NAME
import logging

logger = logging.getLogger(__name__)

_client = None
_collection = None


def get_client() -> chromadb.PersistentClient:
    """Singleton ChromaDB client."""
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=CHROMA_PERSIST_DIR,
            settings=Settings(anonymized_telemetry=False)
        )
        logger.info(f"ChromaDB client khởi tạo tại: {CHROMA_PERSIST_DIR}")
    return _client


def get_collection():
    """Lấy hoặc tạo collection chunks."""
    global _collection
    if _collection is None:
        client = get_client()
        _collection = client.get_or_create_collection(
            name=CHROMA_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )
        logger.info(f"Collection '{CHROMA_COLLECTION_NAME}': {_collection.count()} chunks")
    return _collection


def test_connection() -> bool:
    try:
        col = get_collection()
        count = col.count()
        logger.info(f"✅ ChromaDB: OK — {count} chunks")
        return True
    except Exception as e:
        logger.error(f"❌ ChromaDB: {e}")
        return False
