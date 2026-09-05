"""
Monitoring & Stats Module — NextFarm Chatbot v2.2.

Thu thập và tổng hợp các metric vận hành theo thời gian thực:
- Tool failure rate, timeout, latency từng tool
- Cross-farm access bị chặn (IAM deny log)
- Sensor stale/missing rate
- Recall@K từ calibration_results.json
- Tình trạng benchmark (số câu đã đánh giá từ acceptance_results.json)

Endpoint: GET /api/monitoring/stats
"""
import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("monitoring")

BASE_DIR = Path(__file__).parent.parent

# File tham chiếu
CALIBRATION_FILE = BASE_DIR / "calibration_results.json"
ACCEPTANCE_FILE  = BASE_DIR / "data" / "acceptance_results.json"
BENCHMARK_RESULTS_FILE = BASE_DIR / "data" / "benchmark_results.json"

# ─── In-memory metrics store (reset khi restart) ───────────────────────────────
# Các counter này được cập nhật bởi nextfarm_tools.py qua _record_tool_metric()

_tool_metrics: Dict[str, dict] = defaultdict(lambda: {
    "call_count": 0,
    "success_count": 0,
    "error_count": 0,
    "total_latency_ms": 0.0,
    "latencies": [],         # kept for p95 calculation (max 1000 entries)
    "last_call_at": None,
})

_cross_farm_denies: List[dict] = []   # Log từng lần bị chặn
_iam_total_checks  = 0
_iam_deny_count    = 0

_stale_count  = 0
_fresh_count  = 0
_missing_count = 0


def record_tool_call(tool_name: str, farm_id: str, latency_ms: float, success: bool):
    """
    Ghi nhận một tool call — gọi từ nextfarm_tools._log_tool_call().
    Thread-safe: GIL Python bảo vệ dict + list operations đơn giản.
    """
    m = _tool_metrics[tool_name]
    m["call_count"] += 1
    m["total_latency_ms"] += latency_ms
    m["last_call_at"] = datetime.now().isoformat()
    if success:
        m["success_count"] += 1
    else:
        m["error_count"] += 1

    # Giữ tối đa 1000 latency samples để tính p95
    lats = m["latencies"]
    if len(lats) < 1000:
        lats.append(latency_ms)
    else:
        lats[m["call_count"] % 1000] = latency_ms


def record_iam_check(allowed: bool, farm_id: str, username: str):
    """Ghi nhận một IAM check — gọi từ iam.py."""
    global _iam_total_checks, _iam_deny_count
    _iam_total_checks += 1
    if not allowed:
        _iam_deny_count += 1
        _cross_farm_denies.append({
            "timestamp": datetime.now().isoformat(),
            "farm_id": farm_id,
            "username": username,
        })
        # Giữ tối đa 500 bản ghi gần nhất
        if len(_cross_farm_denies) > 500:
            _cross_farm_denies.pop(0)


def record_sensor_quality(quality_flag: str):
    """Ghi nhận quality_flag của từng sensor read."""
    global _stale_count, _fresh_count, _missing_count
    if quality_flag == "fresh":
        _fresh_count += 1
    elif quality_flag == "stale":
        _stale_count += 1
    elif quality_flag == "missing":
        _missing_count += 1


def _compute_p95(latencies: list) -> float:
    if not latencies:
        return 0.0
    s = sorted(latencies)
    idx = int(len(s) * 0.95)
    return round(s[min(idx, len(s) - 1)], 1)


def _load_json_safe(path: Path) -> Optional[dict]:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Không đọc được {path}: {e}")
    return None


def get_monitoring_stats() -> dict:
    """
    Tổng hợp toàn bộ metric giám sát.
    Returns dict sẵn sàng trả về JSON qua API.
    """
    # ── Tool metrics ───────────────────────────────────────────────────────────
    tool_stats = {}
    for tool, m in _tool_metrics.items():
        total = m["call_count"]
        fail_rate = round(m["error_count"] / total * 100, 1) if total else 0.0
        avg_lat = round(m["total_latency_ms"] / total, 1) if total else 0.0
        p95 = _compute_p95(m["latencies"])
        tool_stats[tool] = {
            "call_count": total,
            "success_count": m["success_count"],
            "error_count": m["error_count"],
            "failure_rate_pct": fail_rate,
            "avg_latency_ms": avg_lat,
            "p95_latency_ms": p95,
            "last_call_at": m["last_call_at"],
        }

    # ── IAM / Cross-farm ──────────────────────────────────────────────────────
    deny_rate = round(_iam_deny_count / _iam_total_checks * 100, 1) if _iam_total_checks else 0.0
    iam_stats = {
        "total_checks": _iam_total_checks,
        "deny_count": _iam_deny_count,
        "deny_rate_pct": deny_rate,
        "recent_denies": _cross_farm_denies[-10:],  # Chỉ 10 gần nhất
    }

    # ── Sensor quality ────────────────────────────────────────────────────────
    sensor_total = _fresh_count + _stale_count + _missing_count
    sensor_stats = {
        "total_reads": sensor_total,
        "fresh_count": _fresh_count,
        "stale_count": _stale_count,
        "missing_count": _missing_count,
        "stale_rate_pct": round(_stale_count / sensor_total * 100, 1) if sensor_total else 0.0,
        "missing_rate_pct": round(_missing_count / sensor_total * 100, 1) if sensor_total else 0.0,
    }

    # ── Calibration (từ file) ─────────────────────────────────────────────────
    calib_data = _load_json_safe(CALIBRATION_FILE)
    calibration_stats = None
    if calib_data:
        calibration_stats = {
            "current_threshold": calib_data.get("current_threshold"),
            "optimal_threshold": calib_data.get("optimal_threshold"),
            "optimal_f1": calib_data.get("optimal_f1"),
            "recommendation": calib_data.get("recommendation"),
            "calibrated_at": calib_data.get("calibrated_at"),
        }

    # ── Acceptance benchmark (từ file) ────────────────────────────────────────
    acceptance_data = _load_json_safe(ACCEPTANCE_FILE)
    acceptance_stats = None
    if acceptance_data:
        acceptance_stats = {
            "total_questions": acceptance_data.get("total_questions"),
            "overall_accuracy_pct": acceptance_data.get("overall_accuracy_pct"),
            "iam_cross_farm_leaks": acceptance_data.get("iam_cross_farm_leaks"),
            "p50_latency_ms": acceptance_data.get("p50_latency_ms"),
            "p95_latency_ms": acceptance_data.get("p95_latency_ms"),
            "status": acceptance_data.get("status"),
            "evaluation_mode": acceptance_data.get("evaluation_mode", "unknown"),
            "evaluated_at": acceptance_data.get("evaluated_at"),
        }

    # ── LLM-as-Judge benchmark (Q&E.txt) ─────────────────────────────────────
    bench_data = _load_json_safe(BENCHMARK_RESULTS_FILE)
    judge_stats = None
    if bench_data:
        results = bench_data.get("results", {})
        if results:
            scores = [r.get("answer_correctness", 0) for r in results.values()]
            judge_stats = {
                "total_evaluated": len(scores),
                "avg_answer_correctness": round(sum(scores) / len(scores), 1) if scores else 0.0,
            }

    return {
        "generated_at": datetime.now().isoformat(),
        "tool_metrics": tool_stats,
        "iam_stats": iam_stats,
        "sensor_quality": sensor_stats,
        "calibration": calibration_stats,
        "acceptance_benchmark": acceptance_stats,
        "llm_judge_benchmark": judge_stats,
        "note": (
            "Các metric tool/iam/sensor là in-memory (reset khi server restart). "
            "calibration và acceptance_benchmark đọc từ file JSON."
        ),
    }
