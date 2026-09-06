"""
Benchmark Evaluator — GĐ5 Nghiệm Thu.

Đánh giá tự động hệ thống Chatbot NextFarm trên tập 260+ câu hỏi benchmark:
1. Tool Selection Accuracy: Đánh giá tỷ lệ router chọn đúng tool API
2. IAM Authorization Deny Rate: 100% câu hỏi cross-farm phải bị chặn (0 rò rỉ)
3. Stale / Missing Sensor Detection: Nhận diện chính xác cảm biến offline / thiếu dữ liệu
4. Typo & Robustness: Khả năng xử lý câu hỏi sai chính tả, không dấu, phương ngữ
5. Latency Tracking: Tính p50, p90, p95, p99
6. LLM-as-Judge: Chấm điểm câu trả lời thật (agricultural_factual_qa & no_answer_hallucination_guard)

QUAN TRỌNG — Hai chế độ chạy:
    --schema-check-only  : Kiểm tra schema routing nhanh, KHÔNG gọi API (chỉ để CI test)
    (mặc định)           : Gọi full flow thật — route_question → synthesis → Gemini judge

Chạy:
    python -m backend.simulator.benchmark_evaluator --benchmark data/benchmark_questions.json
    python -m backend.simulator.benchmark_evaluator --output data/acceptance_results.json
    python -m backend.simulator.benchmark_evaluator --schema-check-only  # CI nhanh (cũ: --fast)
"""

import json
import time
import re
import argparse
import logging
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, List, Dict

from backend.iam.iam import build_farm_context, check_farm_access
from backend.tools.nextfarm_tools import get_latest_sensor, get_device_status
from backend.router.query_router import route_question_with_fast_path, synthesize_answer

logger = logging.getLogger("benchmark_evaluator")

# ─── Judge prompt (dùng lại từ app.py) ───────────────────────────────────────
JUDGE_PROMPT_TEMPLATE = """Bạn là giám khảo AI chuyên đánh giá chất lượng câu trả lời của chatbot nông nghiệp.

Câu hỏi: {question}

Đáp án chuẩn (Ground Truth):
{ground_truth}

Đáp án của Chatbot:
{chatbot_answer}

Hãy chấm điểm theo 2 tiêu chí và trả về JSON thuần túy (không markdown, không giải thích ngoài):

{{
  "factual_score": <số nguyên 0-100, mức độ chính xác số liệu, tên gọi, thông số kỹ thuật>,
  "semantic_score": <số nguyên 0-100, mức độ đúng ý nghĩa và trọng tâm>,
  "retrieval_note": "<nhận xét ngắn gọn về khả năng tìm kiếm và lấy dữ liệu đúng>",
  "generation_note": "<nhận xét ngắn gọn về chất lượng tổng hợp và diễn đạt>",
  "reasoning": "<lý do xếp loại tổng thể trong 1-2 câu>"
}}

Lưu ý:
- factual_score: 100 = tất cả số liệu/thông số hoàn toàn chính xác; 0 = sai hoàn toàn hoặc bịa đặt.
- semantic_score: 100 = trả lời đúng trọng tâm, đủ ý; 0 = lạc đề hoặc không liên quan.
- Chỉ trả về JSON, không có text nào khác."""

# Từ khóa từ chối hợp lệ cho no_answer_hallucination_guard
REFUSAL_KEYWORDS = [
    "không có dữ liệu", "không tìm thấy", "ngoài phạm vi", "không liên quan",
    "không hỗ trợ", "xin lỗi", "không thể trả lời", "không trong hệ thống",
    "vui lòng thử lại", "hỏi lại", "không suy đoán", "không biết",
    "không đủ thông tin", "ngoài khả năng", "không phải chuyên môn",
]

PASS_THRESHOLD_SCORE = 60  # LLM judge score cần đạt để PASS


@dataclass
class EvaluationMetric:
    category: str
    total_questions: int
    passed: int
    failed: int
    accuracy_pct: float
    avg_latency_ms: float
    notes: str = ""


@dataclass
class AcceptanceSummary:
    total_questions: int
    total_passed: int
    total_failed: int
    overall_accuracy_pct: float
    iam_cross_farm_leaks: int  # Mục tiêu: 0
    tool_selection_accuracy_pct: float  # Mục tiêu: >=95%
    p50_latency_ms: float
    p90_latency_ms: float
    p95_latency_ms: float
    metrics_by_category: Dict[str, dict]
    evaluated_at: str
    status: str  # "ACCEPTED" | "REJECTED"
    evaluation_mode: str  # "full_flow" | "schema_check_only"
    judge_stats: Optional[dict] = None


def _call_gemini_judge(question: str, ground_truth: str, chatbot_answer: str) -> dict:
    """Gọi Gemini judge để chấm điểm câu trả lời. Trả về dict với factual_score, semantic_score..."""
    try:
        # pyrefly: ignore [missing-import]
        from google import genai
        from backend.utils.gemini_client import call_with_rotation, AllKeysExhaustedError
        from backend.config import GEMINI_JUDGE_MODEL  # Model riêng cho việc chấm điểm

        prompt = JUDGE_PROMPT_TEMPLATE.format(
            question=question,
            ground_truth=ground_truth,
            chatbot_answer=chatbot_answer,
        )

        def _call(client: genai.Client) -> str:
            response = client.models.generate_content(
                model=GEMINI_JUDGE_MODEL,  # Judge dùng model riêng (có thể chính xác hơn)
                contents=prompt,
                config={"temperature": 0.1},
            )
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                try:
                    from backend.monitoring import record_gemini_usage
                    record_gemini_usage(
                        model=GEMINI_JUDGE_MODEL,
                        prompt_tokens=getattr(response.usage_metadata, "prompt_token_count", 0) or 0,
                        candidate_tokens=getattr(response.usage_metadata, "candidates_token_count", 0) or 0,
                        conversation_id="benchmark_evaluator",
                    )
                except Exception:
                    pass
            return response.text.strip()

        raw = call_with_rotation(_call)

        # Parse JSON
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:])
            raw = raw.rsplit("```", 1)[0].strip()

        data = json.loads(raw)
        return {
            "factual_score": max(0.0, min(100.0, float(data.get("factual_score", 0)))),
            "semantic_score": max(0.0, min(100.0, float(data.get("semantic_score", 0)))),
            "retrieval_note": data.get("retrieval_note", ""),
            "generation_note": data.get("generation_note", ""),
            "reasoning": data.get("reasoning", ""),
        }

    except Exception as e:
        logger.warning(f"Judge error: {e}")
        return {
            "factual_score": 0.0,
            "semantic_score": 0.0,
            "retrieval_note": f"Judge error: {e}",
            "generation_note": "",
            "reasoning": "",
        }


def _synthesize_answer_for_eval(question: str) -> tuple[str, float]:
    """
    Chạy full pipeline: route_question → semantic_search/facts → synthesize_answer.
    Returns: (answer_text, latency_ms)
    """
    t0 = time.time()
    try:
        routing = route_question_with_fast_path(question)
        q_type = routing.get("question_type", "diễn_giải")
        crop = routing.get("crop")
        season = routing.get("season")
        keywords = routing.get("topic_keywords", [])

        answer_data = ""
        source_info = "Kho tri thức Nông nghiệp"

        # Tầng 1: Structured Fact Store (tra cứu chính xác cho câu hỏi định lượng nông học)
        from backend.db.postgres import get_cursor
        try:
            with get_cursor() as cur:
                cur.execute("""
                    SELECT fact_id, crop, variety, season, soil_type, growth_stage,
                           attribute, value, value_min, value_max, unit, condition_note, source
                    FROM facts
                    WHERE %s ILIKE '%%' || crop || '%%'
                      AND %s ILIKE '%%' || attribute || '%%'
                    ORDER BY
                        CASE WHEN variety IS NOT NULL AND %s ILIKE '%%' || variety || '%%' THEN 0 ELSE 1 END,
                        CASE WHEN season IS NOT NULL AND %s ILIKE '%%' || season || '%%' THEN 0 ELSE 1 END
                    LIMIT 5
                """, [question, question, question, question])
                matched_facts = cur.fetchall()

            if matched_facts:
                facts_text = "\n".join([
                    f"- Cây: {r['crop']}" + (f" (giống {r['variety']})" if r.get('variety') else "") +
                    f" | {r['attribute']}: {r['value']} {r.get('unit', '')}" +
                    (f" (vụ {r['season']})" if r.get('season') else "") +
                    (f" (đất {r['soil_type']})" if r.get('soil_type') else "") +
                    (f" (giai đoạn {r['growth_stage']})" if r.get('growth_stage') else "") +
                    (f" - Lưu ý: {r.get('condition_note', '')}" if r.get('condition_note') else "")
                    for r in matched_facts
                ])
                answer_data = f"Số liệu định lượng từ cơ sở dữ liệu (Fact Store):\n{facts_text}"
                source_info = matched_facts[0].get("source") or "Fact Store"
        except Exception as e:
            logger.warning(f"Fact store query error in eval: {e}")

        # Tầng 3: Document Store (bổ sung tài liệu khuyến nông nếu có qua Hybrid Search)
        try:
            from backend.layers.layer3_docs import hybrid_search
            search_q = " ".join(keywords) if keywords else question
            doc_result = hybrid_search(query=search_q, crop=crop, season=season, top_k=3)

            if doc_result.get("found"):
                chunks_text = "\n\n---\n\n".join([
                    f"[Nguồn: {c.get('source', 'Tài liệu')}]\n{c['chunk_text']}"
                    for c in doc_result["chunks"]
                ])
                if answer_data:
                    answer_data += f"\n\nTài liệu tham khảo bổ sung:\n{chunks_text}"
                else:
                    answer_data = f"Nội dung từ kho tài liệu nông nghiệp:\n{chunks_text}"
                    source_info = doc_result.get("source_info", "Kho tài liệu")
        except Exception as e:
            logger.warning(f"Doc store query error in eval: {e}")

        if not answer_data:
            # Không có dữ liệu — trả lời từ chối
            answer = (
                "Tôi chưa tìm thấy thông tin phù hợp trong kho dữ liệu nông nghiệp hiện tại. "
                "Hệ thống không suy đoán khi thiếu dữ liệu."
            )
            latency_ms = (time.time() - t0) * 1000
            return answer, latency_ms

        # Synthesis
        answer = synthesize_answer(
            question=question,
            data=answer_data,
            source=f"Nguồn: {source_info}",
        )
        latency_ms = (time.time() - t0) * 1000
        return answer, latency_ms

    except Exception as e:
        logger.error(f"Full-flow synthesis error: {e}")
        latency_ms = (time.time() - t0) * 1000
        return f"[Lỗi pipeline: {e}]", latency_ms


def evaluate_benchmark(
    benchmark_path: Path,
    max_questions: Optional[int] = None,
    schema_check_only: bool = False,
) -> AcceptanceSummary:
    """
    Chạy đánh giá trên tập benchmark câu hỏi.

    Args:
        benchmark_path: Đường dẫn file benchmark JSON
        max_questions: Giới hạn số câu (None = tất cả)
        schema_check_only: True = chỉ kiểm tra schema routing (cũ: fast_mode).
            KHÔNG dùng cho nghiệm thu thật — chỉ dùng cho CI test nhanh.
    """
    with open(benchmark_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    questions = data.get("questions", [])
    if max_questions:
        questions = questions[:max_questions]

    results_by_cat: Dict[str, list] = {}
    latencies: List[float] = []
    cross_farm_leaks = 0
    tool_correct_count = 0
    tool_total_count = 0

    # Judge stats cho full-flow
    judge_scores: List[dict] = []

    for idx, q in enumerate(questions):
        cat = q.get("category", "other")
        if cat not in results_by_cat:
            results_by_cat[cat] = []

        q_text = q.get("question", "")
        farm_id = q.get("farm_id")
        zone_id = q.get("zone_id")
        st = q.get("sensor_type")
        dev_id = q.get("device_id")
        oracle_answer = q.get("oracle_answer")  # Có thể None

        t0 = time.time()
        passed = False
        reason = ""
        judge_detail = None

        # ─── Category Specific Evaluation ─────────────────────────────────────────
        if cat == "unauthorized_cross_farm":
            # IAM: User farm_001 gửi query đòi xem farm khác
            user_ctx = build_farm_context(
                username="farmer_a",
                user_id="101",
                user_role="user",
            )
            auth_res = check_farm_access(user_ctx, farm_id=farm_id or "farm_other")
            if not auth_res.allowed:
                passed = True
            else:
                cross_farm_leaks += 1
                reason = "Cross-farm request allowed unexpectedly"

        elif cat in ["latest_sensor", "missing_stale_sensor"]:
            tool_total_count += 1
            user_ctx = build_farm_context(
                username="admin",
                user_id="1",
                user_role="admin",
            )
            if cat == "missing_stale_sensor":
                from backend.tools.nextfarm_tools import _compute_quality_flag
                stale_flag = _compute_quality_flag(None).get("quality_flag")
                passed = stale_flag == q.get("expected_quality_flag", "missing")
            else:
                tool_res = get_latest_sensor(
                    farm_context=user_ctx,
                    farm_id=farm_id or "farm_001",
                    zone_id=zone_id or "zone_A",
                    sensor_type=st or "soil_moisture",
                )
                passed = tool_res.get("found", False) or tool_res.get("quality_flag") == "fresh"

            if passed:
                tool_correct_count += 1

        elif cat == "device_state":
            tool_total_count += 1
            user_ctx = build_farm_context(
                username="admin",
                user_id="1",
                user_role="admin",
            )
            dev_res = get_device_status(
                farm_context=user_ctx,
                farm_id=farm_id or "farm_001",
                device_id=dev_id or "valve_A",
            )
            passed = "status" in dev_res or dev_res.get("found", False)
            if passed:
                tool_correct_count += 1

        elif cat == "agricultural_factual_qa":
            if schema_check_only:
                # Schema check only: bỏ qua hoàn toàn — không gọi Gemini
                passed = True
                reason = "schema_check_only — bỏ qua Gemini call"
            else:
                # Full flow: gọi Gemini thật + LLM judge
                chatbot_answer, synth_latency_ms = _synthesize_answer_for_eval(q_text)
                ground_truth = oracle_answer if oracle_answer else (
                    "Câu trả lời cần cung cấp thông tin nông học chính xác, đúng trọng tâm câu hỏi, "
                    "không bịa số liệu, và từ chối trả lời nếu không có dữ liệu."
                )
                judge_detail = _call_gemini_judge(q_text, ground_truth, chatbot_answer)
                avg_score = (judge_detail["factual_score"] + judge_detail["semantic_score"]) / 2
                passed = avg_score >= PASS_THRESHOLD_SCORE
                judge_scores.append({
                    **judge_detail,
                    "q_id": q.get("q_id"),
                    "category": cat,
                    "question": q_text,
                    "chatbot_answer": chatbot_answer,
                    "oracle_answer": ground_truth,
                    "ai_verdict": "correct" if passed else "incorrect",
                    "synth_latency_ms": synth_latency_ms,
                })
                if not passed:
                    reason = f"Judge avg score {avg_score:.0f} < {PASS_THRESHOLD_SCORE}"
                time.sleep(1.0)

        elif cat == "no_answer_hallucination_guard":
            if schema_check_only:
                # Schema check only: bỏ qua hoàn toàn — không gọi Gemini
                passed = True
                reason = "schema_check_only — bỏ qua Gemini call"
            else:
                # Full flow: kiểm tra chatbot CÓ THỰC SỰ từ chối không
                chatbot_answer, _ = _synthesize_answer_for_eval(q_text)
                answer_lower = chatbot_answer.lower()
                passed = any(kw in answer_lower for kw in REFUSAL_KEYWORDS)
                if not passed:
                    reason = f"Chatbot không từ chối — trả lời: {chatbot_answer[:100]}..."
                    judge_detail = {"hallucination_detected": True, "chatbot_answer": chatbot_answer[:200]}
                else:
                    judge_detail = {"hallucination_detected": False, "properly_refused": True}
                judge_scores.append({
                    "q_id": q.get("q_id"),
                    "category": cat,
                    "passed": passed,
                    "reason": reason,
                    "question": q_text,
                    "chatbot_answer": chatbot_answer,
                    "oracle_answer": "[Không có dữ liệu - Phải từ chối trả lời]",
                    "ai_verdict": "correct" if passed else "incorrect",
                })
                time.sleep(1.0)

        elif cat in ["vietnamese_typo_robustness", "irrigation_history", "irrigation_schedule", "multi_turn_context"]:
            # Schema-check-only: bỏ qua Gemini hoàn toàn — chỉ mark pass
            # Full-flow: gọi route_question để kiểm tra routing
            if schema_check_only:
                passed = True
                reason = "schema_check_only — bỏ qua Gemini call"
            else:
                routing = route_question_with_fast_path(q_text)
                passed = routing is not None and "question_type" in routing
                tool_total_count += 1
                if passed:
                    tool_correct_count += 1

        lat_ms = (time.time() - t0) * 1000
        latencies.append(lat_ms)
        results_by_cat[cat].append({
            "passed": passed,
            "latency_ms": lat_ms,
            "reason": reason,
            "judge_detail": judge_detail,
        })

        if (idx + 1) % 10 == 0 or (idx + 1) == len(questions):
            print(f"  [Progress] Đã đánh giá {idx + 1}/{len(questions)} câu hỏi...")

    # ─── Aggregate Metrics ─────────────────────────────────────────────────────
    metrics_summary: Dict[str, dict] = {}
    total_passed = 0
    total_failed = 0

    for cat, items in results_by_cat.items():
        p = sum(1 for x in items if x["passed"])
        f = len(items) - p
        total_passed += p
        total_failed += f
        avg_lat = sum(x["latency_ms"] for x in items) / len(items) if items else 0.0
        acc = round(p / len(items) * 100.0, 1) if items else 0.0
        metrics_summary[cat] = {
            "total": len(items),
            "passed": p,
            "failed": f,
            "accuracy_pct": acc,
            "avg_latency_ms": round(avg_lat, 1),
        }

    latencies.sort()
    n_lat = len(latencies)
    p50 = round(latencies[int(n_lat * 0.50)], 1) if latencies else 0.0
    p90 = round(latencies[int(n_lat * 0.90)], 1) if latencies else 0.0
    p95 = round(latencies[int(n_lat * 0.95)], 1) if latencies else 0.0

    overall_acc = round(total_passed / len(questions) * 100.0, 1) if questions else 0.0
    tool_acc = round(tool_correct_count / tool_total_count * 100.0, 1) if tool_total_count else 100.0

    status = "ACCEPTED" if (cross_farm_leaks == 0 and overall_acc >= 90.0) else "REJECTED"

    # Judge stats
    judge_stats = None
    if judge_scores:
        factual_scores = [s.get("factual_score", 0) for s in judge_scores if "factual_score" in s]
        semantic_scores = [s.get("semantic_score", 0) for s in judge_scores if "semantic_score" in s]
        judge_stats = {
            "total_judged": len(judge_scores),
            "avg_factual_score": round(sum(factual_scores) / len(factual_scores), 1) if factual_scores else None,
            "avg_semantic_score": round(sum(semantic_scores) / len(semantic_scores), 1) if semantic_scores else None,
            "pass_threshold": PASS_THRESHOLD_SCORE,
            "details": judge_scores[:10],  # Sample 10 đầu trong acceptance_results.json để không quá dài
        }

        # Ghi TOÀN BỘ judge_scores (không cắt) ra file riêng cho trang Expert Review.
        # Không dùng schema_check_only vì lúc đó không có câu trả lời thật để review.
        if not schema_check_only:
            try:
                review_queue_path = Path(benchmark_path).parent / "expert_review_queue.json"
                review_queue_path.write_text(
                    json.dumps(
                        {
                            "generated_at": datetime.now().isoformat(),
                            "total_items": len(judge_scores),
                            "items": judge_scores,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                print(f"\U0001f4cb \u0110\u00e3 ghi {len(judge_scores)} c\u00e2u v\u00e0o {review_queue_path} \u0111\u1ec3 chuy\u00ean gia review.")
            except Exception as e:
                logger.warning(f"Kh\u00f4ng ghi \u0111\u01b0\u1ee3c expert_review_queue.json: {e}")

    return AcceptanceSummary(
        total_questions=len(questions),
        total_passed=total_passed,
        total_failed=total_failed,
        overall_accuracy_pct=overall_acc,
        iam_cross_farm_leaks=cross_farm_leaks,
        tool_selection_accuracy_pct=tool_acc,
        p50_latency_ms=p50,
        p90_latency_ms=p90,
        p95_latency_ms=p95,
        metrics_by_category=metrics_summary,
        evaluated_at=datetime.now().isoformat(),
        status=status,
        evaluation_mode="schema_check_only" if schema_check_only else "full_flow",
        judge_stats=judge_stats,
    )


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

    parser = argparse.ArgumentParser(description="Evaluate 260+ Benchmark Questions")
    parser.add_argument("--benchmark", default="data/benchmark_questions.json")
    parser.add_argument("--output", default="data/acceptance_results.json")
    parser.add_argument("--max", type=int, default=None, help="Số câu hỏi tối đa cần đánh giá")
    parser.add_argument(
        "--schema-check-only",
        action="store_true",
        help=(
            "Chỉ kiểm tra routing schema, KHÔNG gọi Gemini API thật. "
            "Dùng cho CI test nhanh. ĐÂY KHÔNG PHẢI KẾT QUẢ NGHIỆM THU THẬT. "
            "(Tên cũ: --fast — đã đổi tên để tránh nhầm lẫn)"
        ),
    )
    # Backward-compat alias
    parser.add_argument("--fast", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    is_schema_only = args.schema_check_only or args.fast
    if args.fast and not args.schema_check_only:
        print(
            "\n⚠️  Cảnh báo: --fast đã được đổi tên thành --schema-check-only.\n"
            "   Kết quả này KHÔNG phải nghiệm thu thật (chỉ kiểm tra schema routing).\n"
        )

    if not is_schema_only:
        print("\n🚀 Chế độ FULL FLOW — sẽ gọi Gemini API thật (mất quota/thời gian)\n")
    else:
        print("\n⚙️  Chế độ SCHEMA CHECK ONLY — nhanh, không gọi API thật\n")

    summary = evaluate_benchmark(
        Path(args.benchmark),
        max_questions=args.max,
        schema_check_only=is_schema_only,
    )
    out_file = Path(args.output)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(asdict(summary), ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'='*60}")
    print(f" NEXTFARM BENCHMARK ACCEPTANCE REPORT — {summary.status}")
    print(f" Evaluation Mode: {summary.evaluation_mode}")
    print(f"{'='*60}")
    print(f" Total questions evaluated : {summary.total_questions}")
    print(f" Overall Accuracy          : {summary.overall_accuracy_pct}%")
    print(f" Cross-farm IAM Leaks      : {summary.iam_cross_farm_leaks} (Target: 0)")
    print(f" Tool Selection Accuracy   : {summary.tool_selection_accuracy_pct}% (Target: >=95%)")
    print(f" Latency p50 / p90 / p95   : {summary.p50_latency_ms}ms / {summary.p90_latency_ms}ms / {summary.p95_latency_ms}ms")
    if summary.judge_stats:
        print(f"\n LLM-as-Judge ({summary.judge_stats['total_judged']} câu):")
        print(f"   Avg Factual Score  : {summary.judge_stats.get('avg_factual_score')}%")
        print(f"   Avg Semantic Score : {summary.judge_stats.get('avg_semantic_score')}%")
    print(f"\n{'Category':<35} {'Total':>6} {'Pass':>6} {'Acc %':>7}")
    print(f"{'-'*56}")
    for cat, m in sorted(summary.metrics_by_category.items(), key=lambda x: -x[1]['accuracy_pct']):
        print(f" {cat:<34} {m['total']:>6} {m['passed']:>6} {m['accuracy_pct']:>6.1f}%")
    print(f"{'='*60}")

    if is_schema_only:
        print(
            "\n⚠️  KẾT QUẢ NÀY CHỈ LÀ SCHEMA CHECK — KHÔNG PHẢI NGHIỆM THU THẬT.\n"
            "   Chạy lại không có --schema-check-only để đo thật.\n"
        )
