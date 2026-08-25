"""
Kết nối và quản lý PostgreSQL.
"""
import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from backend.config import POSTGRES_URL
import logging

logger = logging.getLogger(__name__)


def get_connection():
    """Tạo kết nối PostgreSQL mới."""
    return psycopg2.connect(POSTGRES_URL)


@contextmanager
def get_cursor():
    """Context manager: tự động commit/rollback và đóng kết nối."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"PostgreSQL error: {e}")
        raise
    finally:
        conn.close()


def test_connection() -> bool:
    """Kiểm tra kết nối PostgreSQL và tự động khởi tạo bảng nếu cần."""
    try:
        with get_cursor() as cur:
            cur.execute("SELECT 1")
        init_db()
        logger.info("✅ PostgreSQL: kết nối thành công")
        return True
    except Exception as e:
        logger.error(f"❌ PostgreSQL: kết nối thất bại — {e}")
        return False


def init_db():
    """Tự động khởi tạo DDL schema và seed tài khoản admin nếu chưa có."""
    SQL_INIT = """
    CREATE TABLE IF NOT EXISTS users (
        user_id       SERIAL PRIMARY KEY,
        username      TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role          TEXT NOT NULL DEFAULT 'user',
        is_blocked    BOOLEAN DEFAULT false,
        created_at    TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS chat_sessions (
        session_id  TEXT PRIMARY KEY,
        username    TEXT REFERENCES users(username) ON DELETE CASCADE,
        title       TEXT,
        created_at  TIMESTAMP DEFAULT NOW(),
        updated_at  TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS chat_messages (
        message_id  SERIAL PRIMARY KEY,
        session_id  TEXT NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
        sender      TEXT NOT NULL CHECK (sender IN ('user', 'bot')),
        content     TEXT NOT NULL,
        metadata    JSONB,
        created_at  TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages (session_id, created_at);

    CREATE TABLE IF NOT EXISTS documents (
        document_id       TEXT PRIMARY KEY,
        title             TEXT NOT NULL,
        author            TEXT,
        year_published    INT,
        publisher         TEXT,
        legal_basis       TEXT,
        file_path         TEXT,
        content_hash      VARCHAR(64),
        original_filename TEXT,
        processing_status VARCHAR(20) DEFAULT 'complete',
        updated_at        TIMESTAMP DEFAULT NOW(),
        ingested_at       TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS document_aliases (
        id         SERIAL PRIMARY KEY,
        doc_id     TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
        filename   TEXT NOT NULL,
        linked_at  TIMESTAMP DEFAULT NOW(),
        UNIQUE (doc_id, filename)
    );
    CREATE INDEX IF NOT EXISTS idx_aliases_doc_id ON document_aliases(doc_id);
    CREATE INDEX IF NOT EXISTS idx_aliases_filename ON document_aliases(filename);

    CREATE TABLE IF NOT EXISTS pending_confirmations (
        temp_id      TEXT PRIMARY KEY,
        action_type  TEXT NOT NULL,
        context_json JSONB NOT NULL,
        created_at   TIMESTAMP DEFAULT NOW(),
        expires_at   TIMESTAMP NOT NULL
    );

    CREATE TABLE IF NOT EXISTS facts (
        fact_id            SERIAL PRIMARY KEY,
        crop               TEXT NOT NULL DEFAULT 'nông nghiệp',
        season             TEXT,
        soil_type          TEXT,
        attribute          TEXT NOT NULL,
        value              TEXT NOT NULL,
        unit               TEXT,
        condition_note     TEXT,
        source             TEXT NOT NULL,
        legal_basis        TEXT,
        year_effective     INT,
        confidence         TEXT CHECK (confidence IN ('chính thống','tham khảo')),
        is_quantitative    BOOLEAN DEFAULT true,
        source_chunk_id    TEXT,
        source_document_id TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS kg_triples (
        triple_id          SERIAL PRIMARY KEY,
        entity_a           TEXT NOT NULL,
        entity_a_type      TEXT NOT NULL,
        relationship       TEXT NOT NULL,
        entity_b           TEXT NOT NULL,
        entity_b_type      TEXT NOT NULL,
        source_chunk_id    TEXT,
        year_effective     INT,
        confidence         TEXT CHECK (confidence IN ('chính thống','tham khảo')),
        source_document_id TEXT,
        reviewed           BOOLEAN DEFAULT true,
        created_at         TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS answer_feedback (
        feedback_id SERIAL PRIMARY KEY,
        session_id  TEXT,
        question    TEXT NOT NULL,
        answer      TEXT NOT NULL,
        rating      INT CHECK (rating IN (1, -1)),
        feedback_text TEXT,
        created_at  TIMESTAMP DEFAULT NOW()
    );

    INSERT INTO users (username, password_hash, role, is_blocked)
    VALUES (
        'admin',
        'dac88792c4cce60669316b248955f8ab1af3316c82a968b9bae9a2adc553cff7',
        'admin',
        false
    )
    ON CONFLICT (username) DO UPDATE
    SET password_hash = EXCLUDED.password_hash,
        role = 'admin',
        is_blocked = false;
    """
    # Migrations cho các bảng đã tồn tại từ trước
    SQL_MIGRATIONS = """
    ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS username TEXT REFERENCES users(username) ON DELETE CASCADE;
    ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS title TEXT;

    -- documents: thêm cột nhận diện theo content hash (idempotent)
    ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64);
    ALTER TABLE documents ADD COLUMN IF NOT EXISTS original_filename TEXT;
    ALTER TABLE documents ADD COLUMN IF NOT EXISTS processing_status VARCHAR(20) DEFAULT 'complete';
    ALTER TABLE documents ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();
    CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash);
    CREATE INDEX IF NOT EXISTS idx_documents_filename ON documents(original_filename);

    CREATE TABLE IF NOT EXISTS document_aliases (
        id         SERIAL PRIMARY KEY,
        doc_id     TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
        filename   TEXT NOT NULL,
        linked_at  TIMESTAMP DEFAULT NOW(),
        UNIQUE (doc_id, filename)
    );
    CREATE INDEX IF NOT EXISTS idx_aliases_doc_id ON document_aliases(doc_id);
    CREATE INDEX IF NOT EXISTS idx_aliases_filename ON document_aliases(filename);

    CREATE TABLE IF NOT EXISTS pending_confirmations (
        temp_id      TEXT PRIMARY KEY,
        action_type  TEXT NOT NULL,
        context_json JSONB NOT NULL,
        created_at   TIMESTAMP DEFAULT NOW(),
        expires_at   TIMESTAMP NOT NULL
    );
    """
    try:
        with get_cursor() as cur:
            cur.execute(SQL_INIT)
            cur.execute(SQL_MIGRATIONS)
    except Exception as e:
        logger.error(f"Lỗi khởi tạo DB schema: {e}")



import hashlib

SALT = "nongnghiep_chatbot_salt_2026"


def hash_password(password: str) -> str:
    """Tạo sha256 hash kèm salt cho mật khẩu."""
    return hashlib.sha256((password + SALT).encode('utf-8')).hexdigest()


def create_user(username: str, password: str, role: str = "user") -> dict:
    """Tạo người dùng mới."""
    pwd_hash = hash_password(password)
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO users (username, password_hash, role, is_blocked)
            VALUES (%s, %s, %s, false)
            RETURNING user_id, username, role, is_blocked, created_at
        """, (username, pwd_hash, role))
        return dict(cur.fetchone())


def get_user_by_username(username: str) -> dict:
    """Lấy thông tin người dùng theo username."""
    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT user_id, username, password_hash, role, is_blocked, created_at
                FROM users
                WHERE username = %s
            """, (username,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Error getting user {username}: {e}")
        return None


def get_user_by_id(user_id: int) -> dict:
    """Lấy thông tin người dùng theo user_id."""
    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT user_id, username, role, is_blocked, created_at
                FROM users
                WHERE user_id = %s
            """, (user_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Error getting user id {user_id}: {e}")
        return None


def get_all_users() -> list:
    """Lấy danh sách tất cả người dùng."""
    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT user_id, username, role, is_blocked, created_at
                FROM users
                ORDER BY created_at DESC
            """)
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Error getting all users: {e}")
        return []


def update_user_block_status(user_id: int, is_blocked: bool) -> bool:
    """Cập nhật trạng thái chặn người dùng."""
    try:
        with get_cursor() as cur:
            cur.execute("""
                UPDATE users
                SET is_blocked = %s
                WHERE user_id = %s
            """, (is_blocked, user_id))
            return True
    except Exception as e:
        logger.error(f"Error updating user block status: {e}")
        return False


def delete_user(user_id: int) -> bool:
    """Xoá người dùng theo user_id."""
    try:
        with get_cursor() as cur:
            cur.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
            return True
    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        return False


def save_chat_session(session_id: str, username: str = None, title: str = "Trò chuyện mới"):
    """Tạo hoặc cập nhật phiên trò chuyện gán với username."""
    try:
        with get_cursor() as cur:
            cur.execute("""
                INSERT INTO chat_sessions (session_id, username, title)
                VALUES (%s, %s, %s)
                ON CONFLICT (session_id) DO UPDATE
                SET updated_at = NOW(),
                    username = COALESCE(EXCLUDED.username, chat_sessions.username),
                    title = CASE
                        WHEN chat_sessions.title IS NULL OR chat_sessions.title IN ('Trò chuyện mới', 'Phiên hiện tại', 'Phiên trò chuyện mới', 'Đoạn chat mới')
                        THEN EXCLUDED.title
                        ELSE chat_sessions.title
                    END
            """, (session_id, username, title))
    except Exception as e:
        logger.error(f"Error saving chat session: {e}")


def save_chat_message(session_id: str, sender: str, content: str, metadata: dict = None, username: str = None):
    """Lưu tin nhắn vào lịch sử trò chuyện."""
    try:
        import json
        save_chat_session(session_id, username=username, title=content[:30] if sender == "user" else "Trò chuyện mới")
        with get_cursor() as cur:
            cur.execute("""
                INSERT INTO chat_messages (session_id, sender, content, metadata)
                VALUES (%s, %s, %s, %s)
            """, (session_id, sender, content, json.dumps(metadata or {}, ensure_ascii=False)))
    except Exception as e:
        logger.error(f"Error saving chat message: {e}")


def get_chat_history(session_id: str, username: str = None, limit: int = 50):
    """Lấy danh sách tin nhắn gần nhất trong phiên."""
    try:
        with get_cursor() as cur:
            if username:
                cur.execute("""
                    SELECT m.sender, m.content, m.metadata, m.created_at
                    FROM chat_messages m
                    JOIN chat_sessions s ON m.session_id = s.session_id
                    WHERE m.session_id = %s AND s.username = %s
                    ORDER BY m.created_at ASC
                    LIMIT %s
                """, (session_id, username, limit))
            else:
                cur.execute("""
                    SELECT sender, content, metadata, created_at
                    FROM chat_messages
                    WHERE session_id = %s
                    ORDER BY created_at ASC
                    LIMIT %s
                """, (session_id, limit))
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching chat history: {e}")
        return []


def get_user_sessions(username: str, limit: int = 30):
    """Lấy danh sách các phiên trò chuyện của một username cụ thể."""
    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT s.session_id, s.title, s.updated_at,
                       COUNT(m.message_id) as message_count
                FROM chat_sessions s
                LEFT JOIN chat_messages m ON s.session_id = m.session_id
                WHERE s.username = %s
                GROUP BY s.session_id, s.title, s.updated_at
                ORDER BY s.updated_at DESC
                LIMIT %s
            """, (username, limit))
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching user sessions for {username}: {e}")
        return []


def delete_chat_session(session_id: str, username: str = None) -> bool:
    """Xoá phiên trò chuyện của người dùng."""
    try:
        with get_cursor() as cur:
            if username and username != "admin":
                cur.execute("DELETE FROM chat_sessions WHERE session_id = %s AND (username = %s OR username IS NULL)", (session_id, username))
            else:
                cur.execute("DELETE FROM chat_sessions WHERE session_id = %s", (session_id,))
            return True
    except Exception as e:
        logger.error(f"Error deleting chat session {session_id}: {e}")
        return False


def get_all_sessions(limit: int = 20):
    """Lấy danh sách các phiên trò chuyện gần đây."""
    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT s.session_id, s.username, s.title, s.updated_at,
                       COUNT(m.message_id) as message_count
                FROM chat_sessions s
                LEFT JOIN chat_messages m ON s.session_id = m.session_id
                GROUP BY s.session_id, s.username, s.title, s.updated_at
                ORDER BY s.updated_at DESC
                LIMIT %s
            """, (limit,))
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching sessions: {e}")
        return []


def save_feedback(session_id: str, question: str, answer: str, rating: int, feedback_text: str = None):
    """Lưu đánh giá người dùng."""
    try:
        with get_cursor() as cur:
            cur.execute("""
                INSERT INTO answer_feedback (session_id, question, answer, rating, feedback_text)
                VALUES (%s, %s, %s, %s, %s)
            """, (session_id, question, answer, rating, feedback_text))
            return True
    except Exception as e:
        logger.error(f"Error saving feedback: {e}")
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Document management — nhận diện theo content hash
# ──────────────────────────────────────────────────────────────────────────────

def query_document_by_hash(content_hash: str) -> dict:
    """
    Tìm tài liệu theo content_hash, bỏ qua bản ghi đã bị thay thế (superseded).
    Trả về dict bản ghi hoặc None nếu không tìm thấy.
    """
    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT document_id AS doc_id, title, content_hash, original_filename,
                       processing_status, updated_at, ingested_at
                FROM documents
                WHERE content_hash = %s
                  AND processing_status != 'superseded'
                ORDER BY updated_at DESC
                LIMIT 1
            """, (content_hash,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"query_document_by_hash error: {e}")
        return None


def query_document_by_filename(filename: str) -> dict:
    """
    Tìm tài liệu theo original_filename, bỏ qua bản ghi đã bị thay thế.
    Trả về bản ghi mới nhất hoặc None.
    """
    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT document_id AS doc_id, title, content_hash, original_filename,
                       processing_status, updated_at, ingested_at
                FROM documents
                WHERE original_filename = %s
                  AND processing_status != 'superseded'
                ORDER BY updated_at DESC
                LIMIT 1
            """, (filename,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"query_document_by_filename error: {e}")
        return None


def query_alias(doc_id: str, filename: str) -> bool:
    """Kiểm tra xem filename đã được alias cho doc_id chưa."""
    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT 1 FROM document_aliases
                WHERE doc_id = %s AND filename = %s
                LIMIT 1
            """, (doc_id, filename))
            return cur.fetchone() is not None
    except Exception as e:
        logger.error(f"query_alias error: {e}")
        return False


def get_all_known_filenames(doc_id: str) -> list:
    """
    Trả về danh sách tất cả tên đã biết của tài liệu:
    original_filename (từ bảng documents) + tất cả alias (từ document_aliases).
    Dùng để kiểm tra case 5 (tên đã từng xác nhận, không hỏi lại).
    """
    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT original_filename FROM documents
                WHERE document_id = %s
            """, (doc_id,))
            row = cur.fetchone()
            names = []
            if row and row["original_filename"]:
                names.append(row["original_filename"])

            cur.execute("""
                SELECT filename FROM document_aliases
                WHERE doc_id = %s
            """, (doc_id,))
            for alias_row in cur.fetchall():
                if alias_row["filename"] not in names:
                    names.append(alias_row["filename"])
            return names
    except Exception as e:
        logger.error(f"get_all_known_filenames error: {e}")
        return []


def link_alias_filename(doc_id: str, new_filename: str) -> bool:
    """
    Thêm tên file mới vào danh sách alias của tài liệu.
    Bỏ qua nếu đã tồn tại (ON CONFLICT DO NOTHING).
    """
    try:
        with get_cursor() as cur:
            cur.execute("""
                INSERT INTO document_aliases (doc_id, filename)
                VALUES (%s, %s)
                ON CONFLICT (doc_id, filename) DO NOTHING
            """, (doc_id, new_filename))
        logger.info(f"✅ Đã link alias '{new_filename}' → {doc_id}")
        return True
    except Exception as e:
        logger.error(f"link_alias_filename error: {e}")
        return False


def update_document_status(doc_id: str, status: str) -> bool:
    """
    Cập nhật processing_status của tài liệu.
    status ∈ {'processing', 'partial_failure', 'complete', 'superseded'}
    """
    try:
        with get_cursor() as cur:
            cur.execute("""
                UPDATE documents
                SET processing_status = %s, updated_at = NOW()
                WHERE document_id = %s
            """, (status, doc_id))
        return True
    except Exception as e:
        logger.error(f"update_document_status error: {e}")
        return False


def mark_document_superseded(doc_id: str) -> bool:
    """
    Đánh dấu tài liệu là đã bị thay thế (superseded).
    Dùng cho case 4 khi tài liệu mới đã ingest thành công hoàn toàn.
    Không xoá bản ghi — giữ lại để audit.
    """
    return update_document_status(doc_id, "superseded")


# ──────────────────────────────────────────────────────────────────────────────
# Pending confirmations — quản lý xác nhận từ admin
# ──────────────────────────────────────────────────────────────────────────────

def save_pending_confirmation(temp_id: str, action_type: str, context_json: dict, expires_at) -> bool:
    """
    Lưu context chờ admin xác nhận (case 3, 4).
    expires_at: datetime object, thường là NOW() + 24h.
    """
    import json as _json
    try:
        with get_cursor() as cur:
            cur.execute("""
                INSERT INTO pending_confirmations (temp_id, action_type, context_json, expires_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (temp_id) DO UPDATE
                SET action_type = EXCLUDED.action_type,
                    context_json = EXCLUDED.context_json,
                    expires_at = EXCLUDED.expires_at
            """, (temp_id, action_type, _json.dumps(context_json, ensure_ascii=False, default=str), expires_at))
        return True
    except Exception as e:
        logger.error(f"save_pending_confirmation error: {e}")
        return False


def get_pending_confirmation(temp_id: str) -> dict:
    """Đọc context pending confirmation theo temp_id. Trả None nếu không tìm thấy hoặc đã hết hạn."""
    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT temp_id, action_type, context_json, created_at, expires_at
                FROM pending_confirmations
                WHERE temp_id = %s AND expires_at > NOW()
            """, (temp_id,))
            row = cur.fetchone()
            if not row:
                return None
            # context_json đã được psycopg2 parse thành dict (JSONB)
            return dict(row)
    except Exception as e:
        logger.error(f"get_pending_confirmation error: {e}")
        return None


def delete_pending_confirmation(temp_id: str) -> bool:
    """Xoá một pending confirmation sau khi đã xử lý."""
    try:
        with get_cursor() as cur:
            cur.execute("DELETE FROM pending_confirmations WHERE temp_id = %s", (temp_id,))
        return True
    except Exception as e:
        logger.error(f"delete_pending_confirmation error: {e}")
        return False


def cleanup_expired_pending(pending_uploads_dir=None) -> int:
    """
    Dọn dẹp các pending_confirmations đã hết hạn (expires_at < NOW()).
    Đồng thời xoá file tạm tương ứng trong pending_uploads_dir nếu được cung cấp.
    Trả về số lượng bản ghi đã xoá.
    """
    import pathlib
    deleted = 0
    try:
        with get_cursor() as cur:
            # Lấy danh sách temp_id sắp xoá để dọn file tạm
            cur.execute("""
                SELECT temp_id, context_json FROM pending_confirmations
                WHERE expires_at < NOW()
            """)
            expired_rows = cur.fetchall()

            if pending_uploads_dir and expired_rows:
                for row in expired_rows:
                    ctx = row["context_json"]
                    temp_file_path = ctx.get("temp_file_path") if isinstance(ctx, dict) else None
                    if temp_file_path:
                        p = pathlib.Path(temp_file_path)
                        if p.exists():
                            try:
                                p.unlink()
                                logger.info(f"🗑️ Dọn file tạm hết hạn: {p.name}")
                            except Exception as fe:
                                logger.warning(f"Không xoá được file tạm {p}: {fe}")

            # Xoá bản ghi hết hạn
            cur.execute("DELETE FROM pending_confirmations WHERE expires_at < NOW()")
            deleted = len(expired_rows)

        if deleted > 0:
            logger.info(f"🧹 Đã dọn {deleted} pending_confirmations hết hạn")
        return deleted
    except Exception as e:
        logger.error(f"cleanup_expired_pending error: {e}")
        return 0
