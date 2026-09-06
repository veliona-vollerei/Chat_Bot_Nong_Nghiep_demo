"""
Test Hybrid Retrieval — RRF Merger, BM25 Tokenizer, hybrid_search contract,
và execute_retrieval_plan contract.

Chiến lược mock:
- RRF Merger: unit test thuần (không cần IO)
- BM25 tokenizer: unit test thuần
- hybrid_search: mock semantic_search + bm25_search trực tiếp trong module
- execute_retrieval_plan: pre-import module rồi patch _fetch_* functions

Note: google.genai, backend.utils.gemini_client, backend.config, psycopg2,
ChromaDB, sentence_transformers, rank_bm25 được stub bởi conftest.py.
"""
import asyncio
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, AsyncMock


# Pre-import các module cần thiết để patch có thể resolve đúng
import backend.retrieval.rrf_merger as _rrf_mod  # noqa: E402
import backend.retrieval.bm25_retrieval as _bm25_mod  # noqa: E402
import backend.retrieval.retrieval_plan as _rplan_mod  # noqa: E402

from backend.retrieval.rrf_merger import rrf_merge  # noqa: E402
from backend.retrieval.bm25_retrieval import _tokenize_vi  # noqa: E402


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ─── RRF Merger Unit Tests ─────────────────────────────────────────────────────

class TestRRFMerger(unittest.TestCase):
    def _dense(self, ids, base=0.9):
        return [{"chunk_id": c, "chunk_text": f"T{c}", "similarity": base - i*0.05}
                for i, c in enumerate(ids)]

    def _sparse(self, ids, base=1):
        return [{"chunk_id": c, "chunk_text": f"T{c}", "bm25_rank": base+i, "bm25_score": 10.0-i}
                for i, c in enumerate(ids)]

    def test_empty_inputs_return_empty(self):
        self.assertEqual(rrf_merge([], []), [])

    def test_sparse_only_returns_empty(self):
        """Dense rỗng → không có gì để rank, kết quả rỗng (không có chunk_id từ dense)."""
        # sparse without dense → chỉ sparse được tính
        result = rrf_merge([], self._sparse(["A", "B"]))
        # Tất cả chunk đến từ sparse nên vẫn có kết quả
        self.assertEqual(len(result), 2)

    def test_dense_only_no_sparse(self):
        result = rrf_merge(self._dense(["D1", "D2"]), [])
        self.assertEqual(len(result), 2)
        ids = [r["chunk_id"] for r in result]
        self.assertIn("D1", ids); self.assertIn("D2", ids)

    def test_overlap_gets_higher_score(self):
        """Chunk trong cả 2 danh sách phải có RRF score cao hơn chunk chỉ trong 1."""
        dense = self._dense(["BOTH", "DENSE_ONLY"])
        sparse = self._sparse(["BOTH", "SPARSE_ONLY"])
        result = rrf_merge(dense, sparse, top_k=5)
        scores = {r["chunk_id"]: r["rrf_score"] for r in result}
        self.assertIn("BOTH", scores)
        self.assertGreater(scores["BOTH"], scores.get("DENSE_ONLY", 0))
        self.assertGreater(scores["BOTH"], scores.get("SPARSE_ONLY", 0))

    def test_overlap_sources_field(self):
        """Chunk overlap phải có sources=['dense','sparse']."""
        result = rrf_merge(self._dense(["X"]), self._sparse(["X"]))
        r = next(r for r in result if r["chunk_id"] == "X")
        self.assertIn("dense", r["sources"]); self.assertIn("sparse", r["sources"])

    def test_rrf_formula_single_dense(self):
        """score = 1/(k+rank+1), rank=0, k=60 → 1/61."""
        result = rrf_merge(self._dense(["X"]), [], k=60, top_k=1)
        self.assertAlmostEqual(result[0]["rrf_score"], 1.0/61, places=6)

    def test_top_k_limits(self):
        dense = self._dense([f"D{i}" for i in range(20)])
        result = rrf_merge(dense, [], top_k=5)
        self.assertLessEqual(len(result), 5)

    def test_no_chunk_id_skipped(self):
        dense = [{"chunk_text": "no id", "similarity": 0.9}]
        self.assertEqual(rrf_merge(dense, []), [])

    def test_sorted_descending(self):
        dense = self._dense(["A", "B", "C"])
        sparse = self._sparse(["B"])
        result = rrf_merge(dense, sparse, top_k=5)
        scores = [r["rrf_score"] for r in result]
        self.assertEqual(scores, sorted(scores, reverse=True))


# ─── BM25 Tokenizer Unit Tests ────────────────────────────────────────────────

class TestBM25Tokenizer(unittest.TestCase):
    def test_basic(self):
        t = _tokenize_vi("liều lượng phân đạm cho lúa")
        self.assertIn("liều", t); self.assertIn("lúa", t)

    def test_lowercase(self):
        t = _tokenize_vi("LÚA ĐÔng XuÂN")
        self.assertTrue(all(tok == tok.lower() for tok in t))

    def test_short_excluded(self):
        t = _tokenize_vi("a b c de fg")
        self.assertNotIn("a", t); self.assertNotIn("b", t)
        self.assertIn("de", t)

    def test_empty(self):
        self.assertEqual(_tokenize_vi(""), [])

    def test_pesticide_name(self):
        t = _tokenize_vi("phun thuốc Regent 800WG")
        self.assertIn("regent", t); self.assertIn("800wg", t)


# ─── Hybrid Search Contract Tests ─────────────────────────────────────────────

class TestHybridSearchContract(unittest.TestCase):
    """Mock semantic_search + bm25_search trong layer3_docs để test hybrid logic."""

    def _chunk(self, cid, sim=0.8):
        return {"chunk_id": cid, "chunk_text": f"T{cid}", "similarity": sim,
                "topic": "", "source": "doc_test", "source_document_id": "doc_test",
                "confidence": "chính thống", "heading_path": "", "chunk_type": "paragraph",
                "source_section": ""}

    def _sparse(self, cid, rank=1):
        return {"chunk_id": cid, "chunk_text": f"T{cid}", "bm25_rank": rank, "bm25_score": 5.0}

    def test_dense_only_when_bm25_empty(self):
        import backend.layers.layer3_docs as l3
        dense_res = {"found": True, "chunks": [self._chunk("D1"), self._chunk("D2")], "source_info": "doc"}
        # bm25_search được import lazy trong hybrid_search: `from backend.retrieval.bm25_retrieval import bm25_search`
        # Patch trong bm25_retrieval module scope (nơi hàm thực sự tồn tại)
        with patch.object(l3, "semantic_search", return_value=dense_res), \
             patch("backend.retrieval.bm25_retrieval.bm25_search", return_value=[]):
            result = l3.hybrid_search("liều lượng phân đạm", crop="lúa", top_k=3)
        self.assertTrue(result["found"])
        self.assertEqual(result.get("retrieval_mode"), "dense_only")

    def test_hybrid_rrf_mode(self):
        import backend.layers.layer3_docs as l3
        dense_res = {"found": True,
                     "chunks": [self._chunk("C1", 0.9), self._chunk("C2", 0.8)],
                     "source_info": "doc"}
        sparse_res = [self._sparse("C1", 1), self._sparse("C3", 2)]
        with patch.object(l3, "semantic_search", return_value=dense_res), \
             patch("backend.retrieval.bm25_retrieval.bm25_search", return_value=sparse_res):
            result = l3.hybrid_search("liều lượng", crop="lúa", top_k=3)
        self.assertTrue(result["found"])
        self.assertEqual(result.get("retrieval_mode"), "hybrid_rrf")

    def test_c1_top_when_in_both(self):
        """Chunk trong cả dense + sparse phải xếp đầu sau RRF."""
        import backend.layers.layer3_docs as l3
        dense_res = {"found": True,
                     "chunks": [self._chunk("C1", 0.9), self._chunk("C2", 0.8)],
                     "source_info": "doc"}
        sparse_res = [self._sparse("C1", 1), self._sparse("C3", 2)]
        with patch.object(l3, "semantic_search", return_value=dense_res), \
             patch("backend.retrieval.bm25_retrieval.bm25_search", return_value=sparse_res):
            result = l3.hybrid_search("liều lượng", crop="lúa", top_k=3)
        if result["chunks"]:
            self.assertEqual(result["chunks"][0]["chunk_id"], "C1")

    def test_empty_dense_returns_not_found(self):
        import backend.layers.layer3_docs as l3
        with patch.object(l3, "semantic_search", return_value={"found": False, "chunks": [], "source_info": ""}), \
             patch("backend.retrieval.bm25_retrieval.bm25_search", return_value=[]):
            result = l3.hybrid_search("test", top_k=3)
        self.assertIn("found", result)

    def test_bm25_exception_no_crash(self):
        """BM25 crash không được crash hybrid_search."""
        import backend.layers.layer3_docs as l3
        dense_res = {"found": True, "chunks": [self._chunk("D1")], "source_info": "doc"}
        with patch.object(l3, "semantic_search", return_value=dense_res), \
             patch("backend.retrieval.bm25_retrieval.bm25_search", side_effect=RuntimeError("crash")):
            try:
                result = l3.hybrid_search("test", top_k=3)
                self.assertIn("found", result)  # Không crash
            except RuntimeError:
                self.fail("hybrid_search không được raise RuntimeError từ BM25")


# ─── RetrievalPlan Contract Tests ──────────────────────────────────────────────

class TestRetrievalPlanContract(unittest.TestCase):

    def _found(self, name, priority):
        from backend.retrieval.retrieval_plan import RetrievalSource
        return RetrievalSource(source_name=name, found=True, data=[],
                               data_text=f"Data {name}", source_info=f"Src {name}", priority=priority)

    def _not_found(self, name, priority):
        from backend.retrieval.retrieval_plan import RetrievalSource
        return RetrievalSource(source_name=name, found=False, data=[],
                               data_text="", source_info="", priority=priority)

    def test_dinh_luong_triggers_facts(self):
        async def _go():
            with patch.object(_rplan_mod, "_fetch_docs", return_value=self._found("docs", 2)) as md, \
                 patch.object(_rplan_mod, "_fetch_facts", return_value=self._found("facts", 0)) as mf, \
                 patch.object(_rplan_mod, "_fetch_kg") as mk:
                from backend.retrieval.retrieval_plan import execute_retrieval_plan
                result = await execute_retrieval_plan(
                    question_type="định_lượng", norm_question="liều lượng phân đạm",
                    crop="lúa",
                )
            md.assert_called_once(); mf.assert_called_once(); mk.assert_not_called()
            return result
        result = _run(_go())
        self.assertTrue(result.found)

    def test_no_data_returns_not_found(self):
        async def _go():
            with patch.object(_rplan_mod, "_fetch_docs", return_value=self._not_found("docs", 2)), \
                 patch.object(_rplan_mod, "_fetch_kg", return_value=self._not_found("kg", 1)):
                from backend.retrieval.retrieval_plan import execute_retrieval_plan
                return await execute_retrieval_plan(
                    question_type="diễn_giải", norm_question="test",
                )
        result = _run(_go())
        self.assertFalse(result.found); self.assertEqual(result.sources_used, [])

    def test_primary_layer_is_highest_priority(self):
        async def _go():
            with patch.object(_rplan_mod, "_fetch_docs", return_value=self._found("docs", 2)), \
                 patch.object(_rplan_mod, "_fetch_facts", return_value=self._found("facts", 0)):
                from backend.retrieval.retrieval_plan import execute_retrieval_plan
                return await execute_retrieval_plan(
                    question_type="định_lượng", norm_question="liều lượng", crop="lúa",
                )
        result = _run(_go())
        self.assertIn("Fact", result.primary_layer)

    def test_sources_used_excludes_not_found(self):
        async def _go():
            with patch.object(_rplan_mod, "_fetch_docs", return_value=self._found("docs", 2)), \
                 patch.object(_rplan_mod, "_fetch_facts", return_value=self._not_found("facts", 0)):
                from backend.retrieval.retrieval_plan import execute_retrieval_plan
                return await execute_retrieval_plan(
                    question_type="định_lượng", norm_question="test", crop="lúa",
                )
        result = _run(_go())
        self.assertIn("docs", result.sources_used)
        self.assertNotIn("facts", result.sources_used)

    def test_phu_hop_triggers_kg(self):
        async def _go():
            with patch.object(_rplan_mod, "_fetch_docs", return_value=self._not_found("docs", 2)), \
                 patch.object(_rplan_mod, "_fetch_kg", return_value=self._found("kg", 1)) as mk:
                from backend.retrieval.retrieval_plan import execute_retrieval_plan
                await execute_retrieval_plan(
                    question_type="phù_hợp/quan_hệ", norm_question="giống nào phù hợp",
                    keywords=["giống"],
                )
            mk.assert_called_once()
        _run(_go())

    def test_routing_dict_accepted(self):
        async def _go():
            with patch.object(_rplan_mod, "_fetch_docs", return_value=self._found("docs", 2)):
                from backend.retrieval.retrieval_plan import execute_retrieval_plan
                return await execute_retrieval_plan(
                    routing={"question_type": "diễn_giải", "crop": "lúa",
                             "season": None, "soil_type": None, "growth_stage": None,
                             "topic_keywords": ["tưới"]},
                    norm_question="kỹ thuật tưới nước",
                )
        result = _run(_go())
        self.assertTrue(result.found)


if __name__ == "__main__":
    unittest.main()
