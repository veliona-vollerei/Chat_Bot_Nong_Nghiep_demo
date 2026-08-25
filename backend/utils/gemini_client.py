"""
GeminiKeyManager — Quản lý pool Gemini API Keys với xoay vòng & dự phòng tự động.

Tính năng:
- Thread-safe (dùng threading.Lock)
- Xoay vòng Round-Robin qua danh sách key
- Phân loại lỗi: rate_limit / invalid_key / server_error
- Key bị rate-limit → cooldown 10s rồi tự phục hồi
- Key bị invalid → đánh dấu vĩnh viễn, bỏ qua
- Tất cả key exhausted → raise AllKeysExhaustedError
- Logging đầy đủ mỗi lần rotate
"""
import logging
import threading
import time
from contextlib import contextmanager
from typing import Callable, Any, Optional

# pyrefly: ignore [missing-import]
from google import genai

from backend.config import GEMINI_API_KEYS

logger = logging.getLogger(__name__)

# ── Hằng số ────────────────────────────────────────────────────────────────
RATE_LIMIT_COOLDOWN_SECONDS = 10   # Thời gian chờ trước khi thử lại key bị rate-limit

# Từ khóa nhận diện từng loại lỗi
_RATE_LIMIT_KEYWORDS = [
    "429", "RESOURCE_EXHAUSTED", "quota", "rate limit", "rateLimitExceeded",
]
_INVALID_KEY_KEYWORDS = [
    "401", "403", "API_KEY_INVALID", "invalid api key", "permission denied",
    "API key not valid", "UNAUTHENTICATED",
]
_SERVER_ERROR_KEYWORDS = [
    "500", "502", "503", "504", "UNAVAILABLE", "INTERNAL",
]
_NOT_FOUND_KEYWORDS = [
    "404", "not_found", "not found", "is no longer available",
]


# ── Custom Exceptions ───────────────────────────────────────────────────────
class AllKeysExhaustedError(Exception):
    """Tất cả Gemini API keys đều không khả dụng."""
    pass


# ── Error classifier ────────────────────────────────────────────────────────
def _classify_gemini_error(err_str: str) -> str:
    """
    Phân loại lỗi Gemini API.
    Returns: 'rate_limit' | 'invalid_key' | 'server_error' | 'not_found' | 'other'
    """
    err_lower = err_str.lower()
    if any(k.lower() in err_lower for k in _NOT_FOUND_KEYWORDS):
        return "not_found"
    if any(k.lower() in err_lower for k in _RATE_LIMIT_KEYWORDS):
        return "rate_limit"
    if any(k.lower() in err_lower for k in _INVALID_KEY_KEYWORDS):
        return "invalid_key"
    if any(k.lower() in err_lower for k in _SERVER_ERROR_KEYWORDS):
        return "server_error"
    return "other"


# ── GeminiKeyManager ────────────────────────────────────────────────────────
class GeminiKeyManager:
    """
    Singleton quản lý pool Gemini API Keys.

    Mỗi key có trạng thái:
    - 'active'       : Đang hoạt động bình thường
    - 'rate_limited' : Bị giới hạn tốc độ, cooldown đến `cooldown_until`
    - 'invalid'      : Key không hợp lệ hoặc hết quota vĩnh viễn
    """

    def __init__(self, api_keys: list[str], cooldown_seconds: int = RATE_LIMIT_COOLDOWN_SECONDS):
        if not api_keys:
            raise ValueError(
                "Không có Gemini API Key nào. "
                "Vui lòng điền ít nhất 1 key vào GEMINI_API_KEY_1 trong .env"
            )
        self._lock = threading.Lock()
        self._cooldown_seconds = cooldown_seconds
        self._keys: list[dict] = [
            {
                "index": i,
                "key": key,
                "status": "active",        # active | rate_limited | invalid
                "cooldown_until": 0.0,     # timestamp (float) hết cooldown
                "total_calls": 0,
                "total_errors": 0,
                "rotations_caused": 0,     # số lần key này gây ra rotation
            }
            for i, key in enumerate(api_keys)
        ]
        self._current_idx = 0
        self._clients: dict[int, genai.Client] = {}  # cache Client theo index
        key_labels = [f"KEY_{k['index']+1}" for k in self._keys]
        logger.info(
            f"GeminiKeyManager khoi tao voi {len(self._keys)} key(s): {key_labels}"
        )


    def _get_client(self, idx: int) -> genai.Client:
        """Lấy (hoặc tạo) genai.Client cho key tại index idx."""
        if idx not in self._clients:
            self._clients[idx] = genai.Client(api_key=self._keys[idx]["key"])
        return self._clients[idx]

    def _is_key_available(self, key_info: dict) -> bool:
        """Kiểm tra key có khả dụng tại thời điểm hiện tại không."""
        if key_info["status"] == "active":
            return True
        if key_info["status"] == "rate_limited":
            # Kiểm tra cooldown đã hết chưa
            if time.time() >= key_info["cooldown_until"]:
                key_info["status"] = "active"
                key_info["cooldown_until"] = 0.0
                logger.info(
                    f"♻️  KEY_{key_info['index']+1} đã hết cooldown → phục hồi về 'active'"
                )
                return True
        return False  # invalid hoặc vẫn trong cooldown

    def get_current_client(self) -> tuple[genai.Client, int]:
        """
        Lấy client hiện tại đang active.
        Returns: (client, key_index)
        Raises: AllKeysExhaustedError nếu không còn key nào.
        """
        with self._lock:
            n = len(self._keys)
            for _ in range(n):
                key_info = self._keys[self._current_idx]
                if self._is_key_available(key_info):
                    return self._get_client(self._current_idx), self._current_idx
                # Key này không dùng được, thử key tiếp theo
                self._current_idx = (self._current_idx + 1) % n

            raise AllKeysExhaustedError(
                f"Tất cả {n} Gemini API key đều không khả dụng "
                f"(rate_limited / invalid). Vui lòng thêm key mới hoặc chờ."
            )

    def report_error(self, key_index: int, error_type: str) -> Optional[tuple[genai.Client, int]]:
        """
        Báo cáo lỗi cho key tại key_index và rotate sang key tiếp theo nếu cần.

        Args:
            key_index: Index của key gặp lỗi
            error_type: 'rate_limit' | 'invalid_key' | 'server_error' | 'other'

        Returns:
            (new_client, new_index) nếu rotate thành công
            None nếu lỗi là server_error (không cần rotate)
        Raises:
            AllKeysExhaustedError nếu không còn key nào
        """
        with self._lock:
            key_info = self._keys[key_index]
            key_info["total_errors"] += 1
            n = len(self._keys)

            if error_type == "server_error":
                # Lỗi server — KHÔNG đổi key, caller tự retry với backoff
                logger.warning(
                    f"⚠️  KEY_{key_index+1} gặp server_error — giữ nguyên key, "
                    f"caller sẽ retry với backoff."
                )
                return None

            if error_type == "rate_limit":
                key_info["status"] = "rate_limited"
                key_info["cooldown_until"] = time.time() + self._cooldown_seconds
                key_info["rotations_caused"] += 1
                logger.warning(
                    f"🚦 KEY_{key_index+1} bị rate_limit → cooldown {self._cooldown_seconds}s. "
                    f"Đang xoay sang key tiếp theo..."
                )

            elif error_type == "invalid_key":
                key_info["status"] = "invalid"
                key_info["rotations_caused"] += 1
                logger.error(
                    f"❌ KEY_{key_index+1} không hợp lệ / hết quota vĩnh viễn → "
                    f"đánh dấu 'invalid', loại khỏi pool."
                )

            else:
                # Lỗi không xác định — rotate để thử key khác
                key_info["rotations_caused"] += 1
                logger.warning(
                    f"⚠️  KEY_{key_index+1} lỗi không phân loại được "
                    f"→ rotate sang key tiếp theo."
                )

            # Chuyển sang key tiếp theo
            self._current_idx = (key_index + 1) % n

            # Tìm key available tiếp theo
            for _ in range(n):
                candidate = self._keys[self._current_idx]
                if self._is_key_available(candidate):
                    new_client = self._get_client(self._current_idx)
                    logger.info(
                        f"🔄 Đã xoay vòng: KEY_{key_index+1} → KEY_{self._current_idx+1}"
                    )
                    return new_client, self._current_idx
                self._current_idx = (self._current_idx + 1) % n

            raise AllKeysExhaustedError(
                f"Tất cả {n} Gemini API key đều không khả dụng sau khi xoay vòng."
            )

    def record_success(self, key_index: int):
        """Ghi nhận một lần gọi thành công."""
        with self._lock:
            self._keys[key_index]["total_calls"] += 1

    def status(self) -> list[dict]:
        """Trả về danh sách trạng thái tất cả keys (dùng cho /api/admin/key-status)."""
        with self._lock:
            result = []
            now = time.time()
            for k in self._keys:
                # Cập nhật trạng thái cooldown theo thời gian thực
                status = k["status"]
                remaining_cooldown = 0
                if status == "rate_limited":
                    remaining = k["cooldown_until"] - now
                    if remaining <= 0:
                        status = "active"  # đã hết cooldown (chỉ hiển thị, không ghi vào state)
                    else:
                        remaining_cooldown = round(remaining, 1)

                result.append({
                    "key_index": k["index"] + 1,   # hiển thị 1-based (KEY_1, KEY_2...)
                    "key_preview": f"...{k['key'][-6:]}",   # chỉ lộ 6 ký tự cuối
                    "status": status,
                    "cooldown_remaining_seconds": remaining_cooldown,
                    "total_calls": k["total_calls"],
                    "total_errors": k["total_errors"],
                    "rotations_caused": k["rotations_caused"],
                    "is_current": k["index"] == self._current_idx,
                })
            return result


# ── Singleton instance ──────────────────────────────────────────────────────
try:
    key_manager = GeminiKeyManager(GEMINI_API_KEYS)
except ValueError as _init_err:
    logger.critical(f"🚨 {_init_err}")
    key_manager = None  # type: ignore


# ── Hàm tiện ích công khai ──────────────────────────────────────────────────

def call_with_rotation(
    model_fn: Callable[..., Any],
    *args,
    max_key_rotations: Optional[int] = None,
    server_error_retries: int = 3,
    server_error_backoff: tuple = (3, 6, 10),
    **kwargs,
) -> Any:
    """
    Gọi một hàm Gemini API với tự động xoay vòng key khi gặp lỗi.

    Args:
        model_fn: Hàm cần gọi. Nhận `client` làm tham số đầu tiên.
                  Signature: model_fn(client: genai.Client, *args, **kwargs) -> Any
        *args, **kwargs: Tham số truyền vào model_fn (sau client)
        max_key_rotations: Số lần rotate tối đa (default: số key trong pool)
        server_error_retries: Số lần retry tối đa cho server_error
        server_error_backoff: Tuple thời gian chờ (giây) cho mỗi lần retry server_error

    Returns:
        Kết quả của model_fn khi thành công

    Raises:
        AllKeysExhaustedError: Khi tất cả keys đều không dùng được
        Exception: Lỗi không phục hồi được (non-retryable)
    """
    if key_manager is None:
        raise AllKeysExhaustedError("GeminiKeyManager chưa được khởi tạo. Kiểm tra .env.")

    n_keys = len(key_manager._keys)
    if max_key_rotations is None:
        max_key_rotations = n_keys

    key_rotation_count = 0

    while key_rotation_count <= max_key_rotations:
        # Lấy client hiện tại
        try:
            client, key_idx = key_manager.get_current_client()
        except AllKeysExhaustedError:
            raise

        # Thử gọi API với key này (có retry cho server_error)
        server_attempt = 0
        while server_attempt <= server_error_retries:
            try:
                result = model_fn(client, *args, **kwargs)
                key_manager.record_success(key_idx)
                return result

            except Exception as e:
                err_str = str(e)
                error_type = _classify_gemini_error(err_str)

                if error_type == "not_found":
                    logger.error(f"❌ Model không tồn tại hoặc đã bị Google gỡ bỏ: {e}")
                    raise e

                if error_type == "server_error":
                    server_attempt += 1
                    if server_attempt > server_error_retries:
                        # Hết retry server_error → rotate key
                        logger.error(
                            f"❌ KEY_{key_idx+1} server_error hết {server_error_retries} "
                            f"lần retry → rotate sang key tiếp theo."
                        )
                        break  # thoát vòng server retry, vào rotate
                    wait = server_error_backoff[min(server_attempt - 1, len(server_error_backoff) - 1)]
                    logger.warning(
                        f"⚠️  KEY_{key_idx+1} server_error (lần {server_attempt}/{server_error_retries}). "
                        f"Chờ {wait}s..."
                    )
                    time.sleep(wait)
                    continue  # retry cùng key

                elif error_type in ("rate_limit", "invalid_key", "other"):
                    # Cần rotate key
                    try:
                        key_manager.report_error(key_idx, error_type)
                    except AllKeysExhaustedError:
                        raise
                    key_rotation_count += 1
                    break  # thoát vòng server retry, vào rotate với key mới

        else:
            # server_attempt vòng lặp kết thúc bình thường (không break) — không xảy ra thường
            break

    # Nếu đến đây nghĩa là hết số lần rotate cho phép
    raise AllKeysExhaustedError(
        f"Đã thử {key_rotation_count} lần xoay key nhưng không thành công."
    )
