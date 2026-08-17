"""
text_utils.py — Các hàm tiện ích xử lý văn bản tiếng Việt.

Cung cấp normalize_text() để chuẩn hóa văn bản trước khi
embed hoặc lưu vào DB (loại bỏ ký tự thừa, chuẩn hóa khoảng trắng, v.v.)
"""
import re
import unicodedata


def normalize_text(text: str) -> str:
    """
    Chuẩn hóa văn bản tiếng Việt cơ bản:
    - Loại bỏ khoảng trắng thừa
    - Chuẩn hóa Unicode về NFC (tránh ký tự tổ hợp bị lỗi)
    - Loại bỏ ký tự điều khiển
    - Giữ nguyên dấu thanh tiếng Việt

    Args:
        text: Chuỗi văn bản đầu vào

    Returns:
        Chuỗi đã được chuẩn hóa
    """
    if not text:
        return ""

    # Chuẩn hóa Unicode NFC (giữ dấu thanh tiếng Việt dạng precomposed)
    text = unicodedata.normalize("NFC", text)

    # Loại bỏ ký tự điều khiển (giữ lại \n, \t)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

    # Chuẩn hóa khoảng trắng: nhiều space → 1 space, trim đầu/cuối
    text = re.sub(r'[ \t]+', ' ', text)

    # Loại bỏ dòng trắng dư thừa (>2 dòng trắng liên tiếp → 1)
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


def remove_bracket_prefix(text: str) -> str:
    """
    Xóa prefix dạng [Chủ đề: ...] hoặc [Topic: ...] ở đầu chunk.

    Ví dụ:
        "[Chủ đề: Phân bón] Bón phân đợt 1..." → "Bón phân đợt 1..."
    """
    if text.startswith("["):
        bracket_end = text.find("]")
        if bracket_end != -1:
            return text[bracket_end + 1:].strip()
    return text


def truncate_text(text: str, max_chars: int = 800) -> str:
    """
    Cắt văn bản tối đa max_chars ký tự, ưu tiên cắt tại ranh giới câu.

    Args:
        text: Văn bản đầu vào
        max_chars: Số ký tự tối đa

    Returns:
        Văn bản đã cắt (có "..." nếu bị cắt)
    """
    if len(text) <= max_chars:
        return text

    # Tìm ranh giới câu gần nhất trước max_chars
    truncated = text[:max_chars]
    last_period = max(
        truncated.rfind('.'),
        truncated.rfind('!'),
        truncated.rfind('?'),
        truncated.rfind('\n'),
    )
    if last_period > max_chars // 2:
        return truncated[:last_period + 1].strip()

    return truncated.strip() + "..."
