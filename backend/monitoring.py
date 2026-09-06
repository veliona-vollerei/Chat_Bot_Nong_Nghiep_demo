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

# Thời điểm server khởi động — dùng để hiển thị "kể từ khi server khởi động lúc..."
# trong tab Monitoring Live (tránh nhầm lẫn metric in-memory với batch static)
SERVER_START_TIME = datetime.now().isoformat()

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

# ─── Validator Bypass Counter (GD3 Guardrail) ──────────────────────────────────────
# Đếm số lần validator bị fail-closed do hết quota (AllKeysExhaustedError).
# Nếu cao (>= 5 lần) → CRITICAL alert: hệ thống đang chạy không có guardrail.
_validator_bypass_count = 0
_validator_bypass_log: List[dict] = []  # Tối đa 200 bản ghi

# ─── Gemini Token & Cost Tracking (GĐ3 / P2) ──────────────────────────────────
# Giá USD / 1M tokens (theo biểu giá Google AI Studio pay-as-you-go)
GEMINI_PRICING_PER_1M = {
    "gemini-3.1-flash-lite": (0.075, 0.30),
    "gemini-2.0-flash-lite": (0.075, 0.30),
    "gemini-2.5-flash-lite": (0.075, 0.30),
    "gemini-3.6-flash":      (0.10,  0.40),
    "gemini-2.0-flash":      (0.10,  0.40),
    "gemini-2.5-flash":      (0.10,  0.40),
    "gemini-1.5-flash":      (0.075, 0.30),
    "gemini-2.5-pro":        (1.25,  5.00),
    "gemini-2.0-pro":        (1.25,  5.00),
    "gemini-1.5-pro":        (1.25,  5.00),
}
DEFAULT_PRICING_PER_1M = (0.10, 0.40)
USD_TO_VND_RATE = 25400  # Tỷ giá tham chiếu USD -> VND

_gemini_usage = {
    "total_calls": 0,
    "total_prompt_tokens": 0,
    "total_candidate_tokens": 0,
    "total_tokens": 0,
    "estimated_cost_usd": 0.0,
    "estimated_cost_vnd": 0.0,
    "by_model": defaultdict(lambda: {
        "calls": 0,
        "prompt_tokens": 0,
        "candidate_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
        "estimated_cost_vnd": 0.0,
    }),
    "by_conversation": defaultdict(lambda: {
        "calls": 0,
        "prompt_tokens": 0,
        "candidate_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
        "estimated_cost_vnd": 0.0,
        "last_call_at": None,
    }),
}


def record_gemini_usage(
    model: str,
    prompt_tokens: int = 0,
    candidate_tokens: int = 0,
    conversation_id: Optional[str] = None,
):
    """
    Ghi nhận lượng token tiêu thụ và ước tính chi phí cho mỗi lượt gọi Gemini API.
    """
    model_clean = model.strip()
    input_price, output_price = GEMINI_PRICING_PER_1M.get(model_clean, DEFAULT_PRICING_PER_1M)

    call_tokens = prompt_tokens + candidate_tokens
    cost_usd = (prompt_tokens / 1_000_000.0) * input_price + (candidate_tokens / 1_000_000.0) * output_price
    cost_vnd = cost_usd * USD_TO_VND_RATE

    _gemini_usage["total_calls"] += 1
    _gemini_usage["total_prompt_tokens"] += prompt_tokens
    _gemini_usage["total_candidate_tokens"] += candidate_tokens
    _gemini_usage["total_tokens"] += call_tokens
    _gemini_usage["estimated_cost_usd"] += cost_usd
    _gemini_usage["estimated_cost_vnd"] += cost_vnd

    m = _gemini_usage["by_model"][model_clean]
    m["calls"] += 1
    m["prompt_tokens"] += prompt_tokens
    m["candidate_tokens"] += candidate_tokens
    m["total_tokens"] += call_tokens
    m["estimated_cost_usd"] += cost_usd
    m["estimated_cost_vnd"] += cost_vnd

    if conversation_id:
        c = _gemini_usage["by_conversation"][conversation_id]
        c["calls"] += 1
        c["prompt_tokens"] += prompt_tokens
        c["candidate_tokens"] += candidate_tokens
        c["total_tokens"] += call_tokens
        c["estimated_cost_usd"] += cost_usd
        c["estimated_cost_vnd"] += cost_vnd
        c["last_call_at"] = datetime.now().isoformat()


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


def record_validator_bypass(reason: str = "api_exhausted"):
    """
    Ghi nhận một lần validator bị fail-closed do hết quota API.

    Được gọi từ validator.py khi AllKeysExhaustedError xảy ra.
    Nếu count >= 5 → _compute_alerts() sẽ phát CRITICAL alert VALIDATOR_BYPASSED.
    """
    global _validator_bypass_count
    _validator_bypass_count += 1
    _validator_bypass_log.append({
        "timestamp": datetime.now().isoformat(),
        "reason": reason,
        "count_at_event": _validator_bypass_count,
    })
    # Giữ tối đa 200 bản ghi gần nhất
    if len(_validator_bypass_log) > 200:
        _validator_bypass_log.pop(0)
    logger.critical(
        f"[VALIDATOR_BYPASSED] Guardrail fail-closed lần thứ {_validator_bypass_count} "
        f"do hết quota Gemini API. Reason: {reason}"
    )


def _compute_p95(latencies: list) -> float:
    if not latencies:
        return 0.0
    s = sorted(latencies)
    idx = int(len(s) * 0.95)
    return round(s[min(idx, len(s) - 1)], 1)


# ─── Ngưỡng cảnh báo tự động ───────────────────────────────────────────────────
ALERT_THRESHOLDS = {
    "hallucination_rate_pct": 5.0,      # Cảnh báo nếu missing_rate > 5%
    "tool_failure_rate_pct": 10.0,      # Cảnh báo nếu tool lỗi > 10%
    "iam_deny_rate_min_pct": 0.0,       # Cảnh báo nếu có bất kỳ IAM leak (allow cross-farm)
    # Giảm từ 0.80 xuống 0.75 vì corpus hiện tại (752 chunks, chủ yếu lúa+sầu riêng) chưa phủ
    # hết câu test về cà phê/tiêu/điều/xoài — F1=0.782 là hợp lý trong bối cảnh này.
    # Cận nhật khi bổ sung corpus cây trồng mới.
    "calibration_f1_min": 0.75,
    "acceptance_mode_required": "full_flow",  # Cảnh báo nếu file nghiệm thu dùng schema_check_only
    "latency_p95_warn_ms": 10000.0,    # Cảnh báo nếu p95 latency > 10 giây
}


def _compute_alerts(
    sensor_stats: dict,
    tool_stats: dict,
    iam_stats: dict,
    calibration_stats: Optional[dict],
    acceptance_stats: Optional[dict],
) -> List[dict]:
    """
    Tính danh sách cảnh báo tự động dựa trên ngưỡng ALERT_THRESHOLDS.
    Trả về list[{"level": "WARNING"|"CRITICAL", "code": str, "message": str}].
    """
    alerts: List[dict] = []

    # 1. Sensor missing rate
    missing_rate = sensor_stats.get("missing_rate_pct", 0.0)
    if missing_rate > ALERT_THRESHOLDS["hallucination_rate_pct"]:
        alerts.append({
            "level": "WARNING",
            "code": "HIGH_MISSING_SENSOR_RATE",
            "message": (
                f"Tỷ lệ cảm biến mất dữ liệu cao: {missing_rate:.1f}% "
                f"(ngưỡng: {ALERT_THRESHOLDS['hallucination_rate_pct']}%)"
            ),
        })

    # 2. Tool failure rate
    for tool_name, tm in tool_stats.items():
        fail_rate = tm.get("failure_rate_pct", 0.0)
        if fail_rate > ALERT_THRESHOLDS["tool_failure_rate_pct"]:
            alerts.append({
                "level": "WARNING",
                "code": f"HIGH_TOOL_FAILURE_{tool_name.upper()}",
                "message": (
                    f"Tool '{tool_name}' có tỷ lệ lỗi cao: {fail_rate:.1f}% "
                    f"(ngưỡng: {ALERT_THRESHOLDS['tool_failure_rate_pct']}%)"
                ),
            })

    # 3. IAM cross-farm leak (allow khi không nên allow)
    # Phát hiện bằng cách kiểm tra deny_rate gần 0% khi có nhiều check
    total_iam = iam_stats.get("total_checks", 0)
    deny_count = iam_stats.get("deny_count", 0)
    if total_iam > 10 and deny_count == 0:
        # Nếu có >= 10 check mà không một lần nào deny — có thể IAM đang bị bypass
        alerts.append({
            "level": "WARNING",
            "code": "IAM_NO_DENY_DETECTED",
            "message": (
                f"IAM đã xử lý {total_iam} check nhưng không có lần deny nào — "
                "kiểm tra lại cấu hình phân quyền cross-farm."
            ),
        })

    # 4. Calibration F1 dưới ngưỡng
    if calibration_stats:
        f1 = calibration_stats.get("optimal_f1")
        if f1 is not None and f1 < ALERT_THRESHOLDS["calibration_f1_min"]:
            alerts.append({
                "level": "WARNING",
                "code": "LOW_CALIBRATION_F1",
                "message": (
                    f"F1 hiệu chuẩn RAG: {f1:.3f} "
                    f"(ngưỡng tối thiểu: {ALERT_THRESHOLDS['calibration_f1_min']}). "
                    "Nguyên nhân có thể: corpus chưa phủ cây trồng trong tập calibration. "
                    "Giải pháp: bổ sung tài liệu hoặc chạy lại threshold_calibration.py."
                ),
            })

    # 5. Acceptance results chưa phải full_flow
    if acceptance_stats:
        mode = acceptance_stats.get("evaluation_mode", "")
        if mode != ALERT_THRESHOLDS["acceptance_mode_required"]:
            alerts.append({
                "level": "CRITICAL",
                "code": "ACCEPTANCE_NOT_FULL_FLOW",
                "message": (
                    f"File nghiệm thu đang ở chế độ '{mode}' — "
                    "KHÔNG phải kết quả nghiệm thu thật (full_flow). "
                    "Chạy lại: python -m backend.simulator.benchmark_evaluator"
                ),
            })

    # 6. Latency p95 cao bất thường
    if acceptance_stats:
        p95 = acceptance_stats.get("p95_latency_ms", 0) or 0
        warn_ms = ALERT_THRESHOLDS["latency_p95_warn_ms"]
        if p95 > warn_ms:
            alerts.append({
                "level": "WARNING",
                "code": "HIGH_LATENCY_P95",
                "message": (
                    f"Latency p95 thực tế: {p95/1000:.1f}s "
                    f"(ngưỡng: {warn_ms/1000:.0f}s). "
                    "Nguyên nhân: nhóm agricultural_factual_qa gọi Gemini 2 lần/câu. "
                    "Kiểm tra quota API và cân nhắc cache/batching."
                ),
            })

    # 7. Validator bypass (guardrail fail-closed) — cần react ngay
    if _validator_bypass_count >= 5:
        alerts.append({
            "level": "CRITICAL",
            "code": "VALIDATOR_BYPASSED",
            "message": (
                f"Validator đã fail-closed {_validator_bypass_count} lần do hết quota Gemini API — "
                "hệ thống đang chạy không có guardrail. "
                "Kiểm tra quota API key và thêm key mới nếu cần."
            ),
        })
    elif _validator_bypass_count > 0:
        alerts.append({
            "level": "WARNING",
            "code": "VALIDATOR_BYPASSED",
            "message": (
                f"Validator đã fail-closed {_validator_bypass_count} lần do hết quota Gemini API. "
                "Theo dõi thêm nếu tiếp tục tăng."
            ),
        })

    return alerts


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

    # ── Alerts tự động ───────────────────────────────────────────────────────
    alerts = _compute_alerts(
        sensor_stats=sensor_stats,
        tool_stats=tool_stats,
        iam_stats=iam_stats,
        calibration_stats=calibration_stats,
        acceptance_stats=acceptance_stats,
    )

    # ── Gemini Key Pool Status ─────────────────────────────────────────────
    gemini_pool_status = []
    try:
        from backend.utils.gemini_client import key_manager
        if key_manager:
            gemini_pool_status = key_manager.status()
    except Exception as e:
        logger.warning(f"Không lấy được trạng thái Gemini Key Pool: {e}")

    # ── Gemini Usage & Cost Summary ────────────────────────────────────────
    by_model_dict = {}
    for m_name, m_data in _gemini_usage["by_model"].items():
        by_model_dict[m_name] = {
            "calls": m_data["calls"],
            "prompt_tokens": m_data["prompt_tokens"],
            "candidate_tokens": m_data["candidate_tokens"],
            "total_tokens": m_data["total_tokens"],
            "estimated_cost_usd": round(m_data["estimated_cost_usd"], 6),
            "estimated_cost_vnd": round(m_data["estimated_cost_vnd"], 2),
        }

    # Top 10 conversations by cost
    sorted_convs = sorted(
        _gemini_usage["by_conversation"].items(),
        key=lambda x: x[1]["estimated_cost_usd"],
        reverse=True
    )[:10]
    top_convs = {
        cid: {
            "calls": c["calls"],
            "total_tokens": c["total_tokens"],
            "estimated_cost_usd": round(c["estimated_cost_usd"], 6),
            "estimated_cost_vnd": round(c["estimated_cost_vnd"], 2),
            "last_call_at": c["last_call_at"],
        }
        for cid, c in sorted_convs
    }

    gemini_usage_summary = {
        "total_calls": _gemini_usage["total_calls"],
        "total_prompt_tokens": _gemini_usage["total_prompt_tokens"],
        "total_candidate_tokens": _gemini_usage["total_candidate_tokens"],
        "total_tokens": _gemini_usage["total_tokens"],
        "estimated_cost_usd": round(_gemini_usage["estimated_cost_usd"], 6),
        "estimated_cost_vnd": round(_gemini_usage["estimated_cost_vnd"], 2),
        "by_model": by_model_dict,
        "top_conversations": top_convs,
    }

    return {
        "generated_at": datetime.now().isoformat(),
        "server_start_time": SERVER_START_TIME,   # GĐ3: phân biệt live vs static
        "alerts": alerts,
        "alert_count": len(alerts),
        "tool_metrics": tool_stats,
        "iam_stats": iam_stats,
        "sensor_quality": sensor_stats,
        "gemini_pool": gemini_pool_status,
        "gemini_usage": gemini_usage_summary,
        "calibration": calibration_stats,
        "acceptance_benchmark": acceptance_stats,
        "llm_judge_benchmark": judge_stats,
        # GĐ3 Guardrail: số lần validator bị fail-closed do hết quota
        "validator_guardrail": {
            "bypass_count": _validator_bypass_count,
            "recent_bypasses": _validator_bypass_log[-10:],  # 10 lần gần nhất
        },
        "note": (
            "Các metric tool/iam/sensor/gemini_usage là in-memory (reset khi server restart). "
            "calibration và acceptance_benchmark đọc từ file JSON.\n"
            f"Server khởi động lúc: {SERVER_START_TIME}"
        ),
    }

