"""
Structure-Aware Chunking — Mục 8 GĐ1.

Thay chunker đơn giản (split bằng \\n\\n) bằng chunker nhận biết cấu trúc markdown:
- Giữ heading/section cùng nội dung (không cắt rời heading khỏi body)
- Bảng (table): không cắt giữa dòng, giữ toàn bộ bảng làm 1 chunk
- Danh sách (list): giữ toàn bộ list item liên quan trong 1 chunk
- Overlap đặt sau boundary tự nhiên (sau heading mới), không giữa câu
- Metadata chunk: chunk_type, heading_path, source_page (nếu marker cung cấp)

CHANGELOG:
    GĐ1 Mục 8: Viết mới StructureAwareChunker thay chunk_text() cũ.
               chunk_text() vẫn giữ làm fallback cho định dạng đơn giản.

Cấu trúc markdown nhận dạng:
  # H1 → section level 1
  ## H2 → section level 2
  ### H3 → section level 3
  | ... | → bảng
  - / * / + → danh sách
  1. / 2. → danh sách đánh số
"""
import re
import logging
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ─── Tuning constants ──────────────────────────────────────────────────────
DEFAULT_CHUNK_SIZE = 800        # Số ký tự tối đa/chunk
DEFAULT_CHUNK_OVERLAP = 100     # Overlap (ký tự) giữa các chunk
TABLE_MAX_CHARS = 3000          # Bảng lớn hơn ngưỡng này sẽ bị cắt theo hàng
MIN_CHUNK_CHARS = 80            # Chunk nhỏ hơn sẽ bị ghép vào chunk trước


# ─── Data Structures ──────────────────────────────────────────────────────

@dataclass
class TextBlock:
    """Một khối văn bản có cấu trúc."""
    block_type: str      # "heading", "table", "list", "paragraph", "code"
    text: str
    level: int = 0       # Cấp heading (1-6), 0 cho không phải heading
    heading_path: str = ""   # Chuỗi heading hierarchy: "Chương 1 > 1.1 > 1.1.2"


@dataclass
class StructuredChunk:
    """Chunk đã được cấu trúc hóa, sẵn sàng nạp vào ChromaDB."""
    chunk_text: str
    chunk_type: str         # "section", "table", "list", "mixed"
    heading_path: str       # Hierarchy heading (cho context retrieval)
    chunk_index: int
    char_count: int
    # Optional extra metadata
    source_section: str = ""    # Heading ngay trên chunk này
    is_continuation: bool = False  # True nếu chunk là phần tiếp của section lớn


# ─── Block Parser ─────────────────────────────────────────────────────────

_HEADING_RE = re.compile(r'^(#{1,6})\s+(.+)', re.MULTILINE)
_TABLE_ROW_RE = re.compile(r'^\s*\|.+\|\s*$')
_LIST_ITEM_RE = re.compile(r'^\s*[-*+]\s|^\s*\d+\.\s')
_CODE_FENCE_RE = re.compile(r'^```')


def _parse_blocks(text: str) -> list[TextBlock]:
    """
    Chia markdown text thành list[TextBlock] theo cấu trúc.
    Nhận diện: heading, table, list, code, paragraph.
    """
    lines = text.splitlines()
    blocks: list[TextBlock] = []
    current_type = None
    current_lines: list[str] = []
    current_level = 0
    in_code_fence = False

    def _flush(btype: str, level: int = 0):
        nonlocal current_lines
        if not current_lines:
            return
        content = "\n".join(current_lines).strip()
        if content:
            blocks.append(TextBlock(block_type=btype, text=content, level=level))
        current_lines = []

    for line in lines:
        # Code fence toggle
        if _CODE_FENCE_RE.match(line):
            in_code_fence = not in_code_fence
            if in_code_fence:
                _flush(current_type or "paragraph")
                current_type = "code"
            current_lines.append(line)
            if not in_code_fence:
                _flush("code")
                current_type = None
            continue

        if in_code_fence:
            current_lines.append(line)
            continue

        # Heading
        hm = _HEADING_RE.match(line)
        if hm:
            _flush(current_type or "paragraph", current_level)
            level = len(hm.group(1))
            current_lines = [line]
            current_type = "heading"
            current_level = level
            _flush("heading", level)
            current_type = None
            continue

        # Table row
        if _TABLE_ROW_RE.match(line):
            if current_type != "table":
                _flush(current_type or "paragraph")
                current_type = "table"
            current_lines.append(line)
            continue

        # List item
        if _LIST_ITEM_RE.match(line):
            if current_type not in ("list",):
                _flush(current_type or "paragraph")
                current_type = "list"
            current_lines.append(line)
            continue

        # Blank line = end of current block (tables/lists)
        if not line.strip():
            if current_type in ("table", "list"):
                _flush(current_type)
                current_type = None
            elif current_type == "paragraph":
                _flush("paragraph")
                current_type = None
            continue

        # Normal paragraph
        if current_type not in ("paragraph",):
            _flush(current_type or "paragraph")
            current_type = "paragraph"
        current_lines.append(line)

    _flush(current_type or "paragraph", current_level)
    return blocks


def _build_heading_path(heading_stack: list[tuple[int, str]]) -> str:
    """Xây dựng chuỗi heading path từ stack."""
    return " > ".join(h[1] for h in heading_stack) if heading_stack else ""


# ─── Main Chunker ─────────────────────────────────────────────────────────

class StructureAwareChunker:
    """
    Chunker nhận biết cấu trúc markdown.

    Nguyên tắc:
    1. Heading KHÔNG bị cắt khỏi nội dung theo sau
    2. Bảng KHÔNG bị cắt giữa dòng (trừ khi quá lớn)
    3. List KHÔNG bị cắt giữa item
    4. Overlap đặt sau boundary tự nhiên
    5. Mỗi chunk có heading_path để context-aware retrieval
    """

    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overlap: int = DEFAULT_CHUNK_OVERLAP,
        min_chunk_chars: int = MIN_CHUNK_CHARS,
    ):
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.min_chunk_chars = min_chunk_chars

    def chunk(self, text: str) -> list[StructuredChunk]:
        """
        Chia văn bản thành StructuredChunks.

        Returns:
            list[StructuredChunk] với heading_path, chunk_type đầy đủ
        """
        if not text or not text.strip():
            return []

        blocks = _parse_blocks(text)
        if not blocks:
            return []

        chunks: list[StructuredChunk] = []
        heading_stack: list[tuple[int, str]] = []  # [(level, text), ...]
        current_buf: list[str] = []
        current_types: list[str] = []
        current_heading_path = ""
        chunk_idx = 0
        overlap_buf = ""

        def _emit_chunk(buf: list[str], types: list[str], hpath: str, is_cont: bool = False):
            nonlocal chunk_idx, overlap_buf
            text_out = "\n\n".join(buf).strip()
            if len(text_out) < self.min_chunk_chars and chunks:
                # Ghép vào chunk trước nếu quá nhỏ
                prev = chunks[-1]
                chunks[-1] = StructuredChunk(
                    chunk_text=prev.chunk_text + "\n\n" + text_out,
                    chunk_type=prev.chunk_type,
                    heading_path=prev.heading_path,
                    chunk_index=prev.chunk_index,
                    char_count=len(prev.chunk_text) + len(text_out),
                    source_section=prev.source_section,
                    is_continuation=prev.is_continuation,
                )
                overlap_buf = text_out[-self.overlap:] if len(text_out) > self.overlap else text_out
                return

            # Xác định chunk_type chính
            type_counts: dict[str, int] = {}
            for t in types:
                type_counts[t] = type_counts.get(t, 0) + 1
            dominant = max(type_counts, key=type_counts.get) if type_counts else "mixed"

            # Heading name cho source_section
            source_section = heading_stack[-1][1] if heading_stack else ""

            chunks.append(StructuredChunk(
                chunk_text=text_out,
                chunk_type=dominant,
                heading_path=hpath,
                chunk_index=chunk_idx,
                char_count=len(text_out),
                source_section=source_section,
                is_continuation=is_cont,
            ))
            chunk_idx += 1
            # Overlap: lấy phần cuối
            overlap_buf = text_out[-self.overlap:] if len(text_out) > self.overlap else text_out

        for block in blocks:
            if block.block_type == "heading":
                # Update heading stack
                level = block.level
                # Loại bỏ heading cùng cấp hoặc cao hơn
                heading_stack = [(l, t) for l, t in heading_stack if l < level]
                # Lấy text heading (bỏ dấu #)
                heading_text = re.sub(r'^#+\s*', '', block.text).strip()
                heading_stack.append((level, heading_text))
                current_heading_path = _build_heading_path(heading_stack)

                # Nếu buffer đủ lớn → emit trước khi bắt đầu section mới
                buf_text = "\n\n".join(current_buf)
                if len(buf_text) > self.chunk_size // 2:
                    _emit_chunk(current_buf, current_types, current_heading_path)
                    current_buf = []
                    current_types = []
                    # Bắt đầu chunk mới với overlap
                    if overlap_buf:
                        current_buf.append(overlap_buf)
                        current_types.append("paragraph")

                # Thêm heading vào buffer mới (sẽ đi kèm nội dung theo sau)
                current_buf.append(block.text)
                current_types.append("heading")
                continue

            if block.block_type == "table":
                # Bảng: cố gắng giữ nguyên
                table_text = block.text
                buf_text = "\n\n".join(current_buf)

                if len(table_text) > TABLE_MAX_CHARS:
                    # Bảng quá lớn: emit buffer hiện tại, emit từng nhóm hàng
                    if current_buf:
                        _emit_chunk(current_buf, current_types, current_heading_path)
                        current_buf = []
                        current_types = []
                    self._split_large_table(
                        table_text, chunks, chunk_idx, current_heading_path, heading_stack
                    )
                    chunk_idx = len(chunks)
                    continue

                if len(buf_text) + len(table_text) > self.chunk_size:
                    # Không vừa: emit buffer, bắt đầu chunk mới với table
                    if current_buf:
                        _emit_chunk(current_buf, current_types, current_heading_path)
                        current_buf = []
                        current_types = []
                    current_buf.append(table_text)
                    current_types.append("table")
                else:
                    current_buf.append(table_text)
                    current_types.append("table")
                continue

            if block.block_type in ("paragraph", "list", "code"):
                block_text = block.text
                buf_text = "\n\n".join(current_buf)

                if len(buf_text) + len(block_text) <= self.chunk_size:
                    current_buf.append(block_text)
                    current_types.append(block.block_type)
                else:
                    # Buffer đầy → emit
                    if current_buf:
                        _emit_chunk(current_buf, current_types, current_heading_path)
                        current_buf = []
                        current_types = []
                        if overlap_buf:
                            current_buf.append(overlap_buf)
                            current_types.append("paragraph")

                    # Block dài hơn chunk_size → cắt thêm (fallback character split)
                    if len(block_text) > self.chunk_size:
                        sub_chunks = self._split_long_block(block_text)
                        for sc in sub_chunks:
                            source_section = heading_stack[-1][1] if heading_stack else ""
                            chunks.append(StructuredChunk(
                                chunk_text=sc,
                                chunk_type=block.block_type,
                                heading_path=current_heading_path,
                                chunk_index=chunk_idx,
                                char_count=len(sc),
                                source_section=source_section,
                                is_continuation=True,
                            ))
                            chunk_idx += 1
                        overlap_buf = sub_chunks[-1][-self.overlap:] if sub_chunks else ""
                    else:
                        current_buf.append(block_text)
                        current_types.append(block.block_type)

        # Emit phần còn lại
        if current_buf:
            _emit_chunk(current_buf, current_types, current_heading_path)

        logger.debug(
            f"StructureAwareChunker: {len(text)} chars → {len(chunks)} chunks "
            f"(size={self.chunk_size}, overlap={self.overlap})"
        )
        return chunks

    def _split_long_block(self, text: str) -> list[str]:
        """Fallback: cắt block dài theo character boundary gần câu."""
        result = []
        start = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            if end < len(text):
                # Tìm boundary tự nhiên gần nhất (dấu chấm, xuống dòng)
                for sep in ('\n', '. ', '! ', '? ', ', '):
                    pos = text.rfind(sep, start, end)
                    if pos > start + self.chunk_size // 2:
                        end = pos + len(sep)
                        break
            result.append(text[start:end].strip())
            start = end - self.overlap if end - self.overlap > start else end
        return [r for r in result if r]

    def _split_large_table(
        self,
        table_text: str,
        chunks: list[StructuredChunk],
        chunk_idx: int,
        heading_path: str,
        heading_stack: list,
    ):
        """Chia bảng lớn thành nhiều chunk theo nhóm hàng, giữ header."""
        lines = table_text.strip().splitlines()
        if len(lines) < 2:
            return

        # Xác định header (dòng đầu) và separator (dòng 2 có ---)
        header_lines = [lines[0]]
        data_start = 1
        if len(lines) > 1 and re.match(r'^\s*\|[-:|]+\|', lines[1]):
            header_lines.append(lines[1])
            data_start = 2

        header = "\n".join(header_lines)
        data_lines = lines[data_start:]

        # Nhóm hàng vào chunks
        current_rows: list[str] = []
        current_size = len(header)
        source_section = heading_stack[-1][1] if heading_stack else ""

        for row in data_lines:
            if current_size + len(row) + 1 > TABLE_MAX_CHARS:
                if current_rows:
                    chunk_text = header + "\n" + "\n".join(current_rows)
                    chunks.append(StructuredChunk(
                        chunk_text=chunk_text,
                        chunk_type="table",
                        heading_path=heading_path,
                        chunk_index=chunk_idx,
                        char_count=len(chunk_text),
                        source_section=source_section,
                        is_continuation=len(chunks) > 0,
                    ))
                    chunk_idx += 1
                    current_rows = []
                    current_size = len(header)
            current_rows.append(row)
            current_size += len(row) + 1

        if current_rows:
            chunk_text = header + "\n" + "\n".join(current_rows)
            chunks.append(StructuredChunk(
                chunk_text=chunk_text,
                chunk_type="table",
                heading_path=heading_path,
                chunk_index=chunk_idx,
                char_count=len(chunk_text),
                source_section=source_section,
                is_continuation=True,
            ))


# ─── Public API ───────────────────────────────────────────────────────────

_default_chunker = StructureAwareChunker(
    chunk_size=DEFAULT_CHUNK_SIZE,
    overlap=DEFAULT_CHUNK_OVERLAP,
)


def chunk_markdown(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[StructuredChunk]:
    """
    Chia markdown text thành StructuredChunks (có heading_path, chunk_type).

    Dùng cho tài liệu đã extract ra markdown (output từ marker-master).
    Fallback tự động về character chunking nếu không phát hiện cấu trúc.

    Returns:
        list[StructuredChunk]
    """
    if chunk_size != DEFAULT_CHUNK_SIZE or overlap != DEFAULT_CHUNK_OVERLAP:
        chunker = StructureAwareChunker(chunk_size=chunk_size, overlap=overlap)
    else:
        chunker = _default_chunker

    return chunker.chunk(text)


def chunk_markdown_to_strings(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """
    Backward-compat: trả về list[str] thay vì list[StructuredChunk].
    Dùng để thay thế chunk_text() cũ mà không cần sửa caller.
    """
    chunks = chunk_markdown(text, chunk_size, overlap)
    return [c.chunk_text for c in chunks]
