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
        document_id     TEXT PRIMARY KEY,
        title           TEXT NOT NULL,
        author          TEXT,
        year_published  INT,
        publisher       TEXT,
        legal_basis     TEXT,
        file_path       TEXT,
        ingested_at     TIMESTAMP DEFAULT NOW()
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
                    username = COALESCE(EXCLUDED.username, chat_sessions.username)
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

