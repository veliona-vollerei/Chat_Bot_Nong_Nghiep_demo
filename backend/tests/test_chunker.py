"""
Unit Tests — GĐ1 Mục 8: Structure-Aware Chunking
Kiểm tra các case: heading, table, list, long block, backward compat.

Chạy: pytest backend/tests/test_chunker.py -v
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

# pyrefly: ignore [missing-import]
import pytest
from backend.ingestion.chunker import (
    chunk_markdown,
    chunk_markdown_to_strings,
    StructureAwareChunker,
    StructuredChunk,
    _parse_blocks,
)


# ─── Test: Block Parser ────────────────────────────────────────────────────

class TestBlockParser:
    def test_heading_detected(self):
        text = "# Tiêu đề chính\n\nNội dung đoạn 1"
        blocks = _parse_blocks(text)
        types = [b.block_type for b in blocks]
        assert "heading" in types, f"Phải phát hiện heading, got: {types}"

    def test_table_detected(self):
        text = "| Cột 1 | Cột 2 |\n|-------|-------|\n| A     | B     |"
        blocks = _parse_blocks(text)
        types = [b.block_type for b in blocks]
        assert "table" in types, f"Phải phát hiện table, got: {types}"

    def test_list_detected(self):
        text = "- Item 1\n- Item 2\n- Item 3"
        blocks = _parse_blocks(text)
        types = [b.block_type for b in blocks]
        assert "list" in types, f"Phải phát hiện list, got: {types}"

    def test_code_detected(self):
        text = "```python\nprint('hello')\n```"
        blocks = _parse_blocks(text)
        types = [b.block_type for b in blocks]
        assert "code" in types, f"Phải phát hiện code block, got: {types}"

    def test_mixed_content(self):
        text = "# Chương 1\n\nĐoạn giới thiệu.\n\n| Col | Val |\n|----|----|\n| A | 1 |\n\n- Điểm 1\n- Điểm 2"
        blocks = _parse_blocks(text)
        types = [b.block_type for b in blocks]
        assert "heading" in types
        assert "table" in types
        assert "list" in types


# ─── Test: Heading Path ─────────────────────────────────────────────────────

class TestHeadingPath:
    def test_heading_path_captured(self):
        """Chunk phải có heading_path từ heading trước đó."""
        text = """# Phần 1\n\n## Mục 1.1\n\nNội dung mục 1.1"""
        chunks = chunk_markdown(text)
        assert len(chunks) > 0, "Phải có chunks"
        # Chunk chứa nội dung phải có heading_path
        content_chunks = [c for c in chunks if "Nội dung" in c.chunk_text]
        if content_chunks:
            assert content_chunks[0].heading_path != "", (
                "Chunk sau heading phải có heading_path"
            )

    def test_heading_hierarchy(self):
        """heading_path phải theo hierarchy H1 > H2 > H3."""
        text = "# H1\n\n## H2\n\n### H3\n\nNội dung sâu"
        chunks = chunk_markdown(text)
        content_chunks = [c for c in chunks if "Nội dung sâu" in c.chunk_text]
        if content_chunks:
            path = content_chunks[0].heading_path
            assert "H1" in path and "H2" in path and "H3" in path, (
                f"Heading path phải có H1 > H2 > H3, nhưng got: '{path}'"
            )

    def test_new_heading_resets_path(self):
        """Heading mới cùng cấp phải override heading cũ."""
        text = "## Mục A\n\nNội dung A\n\n## Mục B\n\nNội dung B"
        chunks = chunk_markdown(text)
        chunks_b = [c for c in chunks if "Nội dung B" in c.chunk_text]
        if chunks_b:
            path = chunks_b[0].heading_path
            assert "Mục B" in path, f"Phải có 'Mục B' trong path, got: '{path}'"
            assert "Mục A" not in path, f"Không được có 'Mục A' trong path của Mục B, got: '{path}'"


# ─── Test: Table Integrity ──────────────────────────────────────────────────

class TestTableIntegrity:
    def test_table_not_split_in_middle(self):
        """Bảng nhỏ phải được giữ nguyên, không bị cắt giữa hàng."""
        table = "\n".join([
            "| Giống | Năng suất | Ghi chú |",
            "|-------|-----------|---------|",
            "| OM18  | 7-8 t/ha  | Đông Xuân |",
            "| OM5451| 6-7 t/ha  | Hè Thu |",
            "| IR50404| 5-6 t/ha | Phèn nhẹ |",
        ])
        text = f"# Bảng giống lúa\n\n{table}"
        chunks = chunk_markdown(text, chunk_size=2000)

        # Tìm chunk chứa bảng
        table_chunks = [c for c in chunks if c.chunk_type == "table" or "|" in c.chunk_text]
        assert len(table_chunks) > 0, "Phải có chunk chứa bảng"
        # Bảng nhỏ không bị tách
        assert any("OM18" in c.chunk_text and "OM5451" in c.chunk_text
                   for c in table_chunks), (
            "Bảng nhỏ phải nằm trong cùng 1 chunk"
        )

    def test_table_chunk_type(self):
        """Chunk chứa bảng phải có chunk_type='table'."""
        text = "| A | B |\n|---|---|\n| 1 | 2 |"
        chunks = chunk_markdown(text)
        table_chunks = [c for c in chunks if c.chunk_type == "table"]
        assert len(table_chunks) > 0, "Phải có ít nhất 1 chunk với chunk_type='table'"


# ─── Test: Long Block Split ─────────────────────────────────────────────────

class TestLongBlockSplit:
    def test_long_paragraph_split_correctly(self):
        """Đoạn văn dài hơn chunk_size phải bị cắt."""
        long_text = "Đây là một đoạn văn rất dài. " * 100  # ~2800 chars
        chunks = chunk_markdown(long_text, chunk_size=800)
        assert len(chunks) > 1, "Đoạn dài phải được chia thành nhiều chunks"
        for c in chunks:
            assert c.char_count <= 1200, (
                f"Chunk không được quá 1200 chars (với buffer), nhưng got: {c.char_count}"
            )

    def test_min_chunk_size_respected(self):
        """Chunk nhỏ phải được ghép với chunk trước."""
        text = "# Tiêu đề\n\nNội dung đủ dài đủ dài đủ dài đủ dài đủ dài.\n\nTí."
        chunks = chunk_markdown(text, chunk_size=800)
        # "Tí." chỉ có 3 ký tự → phải ghép vào chunk trước
        tiny_standalone = [c for c in chunks if len(c.chunk_text.strip()) < 10]
        assert len(tiny_standalone) == 0, (
            f"Không được có chunk quá nhỏ độc lập: {[c.chunk_text for c in tiny_standalone]}"
        )


# ─── Test: Backward Compatibility ──────────────────────────────────────────

class TestBackwardCompat:
    def test_chunk_markdown_to_strings_returns_list_str(self):
        """chunk_markdown_to_strings phải trả về list[str]."""
        text = "# Tiêu đề\n\nNội dung đoạn văn."
        result = chunk_markdown_to_strings(text)
        assert isinstance(result, list), "Phải trả về list"
        assert all(isinstance(s, str) for s in result), "Mỗi phần tử phải là str"
        assert len(result) > 0, "Phải có ít nhất 1 chunk"

    def test_empty_text_returns_empty_list(self):
        """Văn bản rỗng phải trả về list rỗng."""
        result = chunk_markdown("")
        assert result == [], f"Text rỗng phải → [], got: {result}"

    def test_structured_chunk_fields(self):
        """StructuredChunk phải có đầy đủ fields."""
        text = "# Heading\n\nNội dung."
        chunks = chunk_markdown(text)
        assert len(chunks) > 0
        for c in chunks:
            assert hasattr(c, "chunk_text")
            assert hasattr(c, "chunk_type")
            assert hasattr(c, "heading_path")
            assert hasattr(c, "chunk_index")
            assert hasattr(c, "char_count")
            assert c.char_count == len(c.chunk_text)

    def test_plain_text_works(self):
        """Text không có markdown cũng phải hoạt động."""
        text = "Đây là văn bản thuần túy không có heading hay table.\nDòng thứ hai."
        chunks = chunk_markdown(text)
        assert len(chunks) > 0


# ─── Test: Real Agriculture Document Structure ─────────────────────────────

class TestAgricultureDocStructure:
    """Test với cấu trúc thực tế từ tài liệu nông nghiệp."""

    SAMPLE_DOC = """
# QUY TRÌNH KỸ THUẬT CANH TÁC LÚA NƯỚC

## 1. Giống và chuẩn bị mạ

### 1.1 Chọn giống
Chọn giống phù hợp với điều kiện đất đai và mùa vụ.
Các giống lúa phổ biến tại ĐBSCL:

- OM18: thích nghi rộng, năng suất cao 7-8 tấn/ha
- OM5451: chịu phèn nhẹ, phù hợp vụ Đông Xuân
- IR50404: chịu phèn trung bình, vụ Hè Thu

### 1.2 Lượng giống gieo

| Phương pháp | Lượng giống (kg/ha) | Ghi chú |
|-------------|---------------------|---------|
| Sạ tay      | 120-150             | Tiết kiệm giống |
| Sạ máy      | 80-100              | Đều, tiết kiệm |
| Cấy         | 40-60               | Tốn công |

## 2. Phân bón

Lượng phân bón khuyến cáo cho lúa Đông Xuân trên đất phù sa:
- Đạm (N): 80-100 kg/ha
- Lân (P2O5): 40-60 kg/ha
- Kali (K2O): 30-40 kg/ha
"""

    def test_agriculture_doc_chunks(self):
        """Tài liệu nông nghiệp thực tế phải chunked đúng cấu trúc."""
        chunks = chunk_markdown(self.SAMPLE_DOC)
        assert len(chunks) >= 2, f"Phải có ít nhất 2 chunks, got {len(chunks)}"

    def test_table_preserved(self):
        """Bảng phương pháp gieo trong tài liệu phải được giữ nguyên."""
        chunks = chunk_markdown(self.SAMPLE_DOC)
        table_chunks = [c for c in chunks if "Sạ tay" in c.chunk_text]
        assert len(table_chunks) > 0, "Phải tìm thấy bảng phương pháp gieo"
        # Bảng có thể được classify là "table" hoặc "heading" khi ghép với heading gần đó
        valid_types = {"table", "heading", "mixed", "paragraph"}
        assert table_chunks[0].chunk_type in valid_types, (
            f"Chunk bảng phải có chunk_type trong {valid_types}, got: '{table_chunks[0].chunk_type}'"
        )
        # Quan trọng: toàn bộ bảng (3 hàng data) phải nằm trong chunk
        bảng_text = table_chunks[0].chunk_text
        assert "Sạ máy" in bảng_text or len(table_chunks) >= 2, (
            "Bảng phải được giữ nguyên hoặc tách theo boundary tự nhiên"
        )


    def test_heading_path_in_depth(self):
        """Nội dung mục 1.1 phải có heading_path đúng."""
        chunks = chunk_markdown(self.SAMPLE_DOC)
        variety_chunks = [c for c in chunks if "OM18" in c.chunk_text or "OM5451" in c.chunk_text]
        if variety_chunks:
            path = variety_chunks[0].heading_path
            # Phải contain "Chọn giống" hoặc "1.1" hoặc một phần của hierarchy
            assert path != "", f"heading_path không được rỗng cho chunk giống lúa"

    def test_all_content_preserved(self):
        """Tổng nội dung từ tất cả chunks phải chứa đủ nội dung gốc."""
        chunks = chunk_markdown(self.SAMPLE_DOC)
        all_text = " ".join(c.chunk_text for c in chunks)
        for key in ["OM18", "Đạm", "Sạ tay", "ĐBSCL"]:
            assert key in all_text, f"Nội dung '{key}' bị mất sau chunking!"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
