"""
Tests for backend.monitoring module:
- Tool call metrics
- Sensor quality distribution
- IAM checks
- Gemini token & cost tracking per model and conversation
"""
# pyrefly: ignore [missing-import]
import pytest
from backend.monitoring import (
    record_tool_call,
    record_iam_check,
    record_sensor_quality,
    record_gemini_usage,
    get_monitoring_stats,
    _compute_p95,
)


def test_compute_p95():
    latencies = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    p95 = _compute_p95(latencies)
    assert p95 == 100.0
    assert _compute_p95([]) == 0.0


def test_tool_metrics_recording():
    record_tool_call("test_tool", "farm_01", 120.5, success=True)
    stats = get_monitoring_stats()
    assert "test_tool" in stats["tool_metrics"]
    tm = stats["tool_metrics"]["test_tool"]
    assert tm["call_count"] >= 1
    assert tm["success_count"] >= 1


def test_iam_check_recording():
    record_iam_check(allowed=False, farm_id="farm_02", username="intruder")
    stats = get_monitoring_stats()
    assert stats["iam_stats"]["total_checks"] >= 1
    assert stats["iam_stats"]["deny_count"] >= 1


def test_sensor_quality_recording():
    record_sensor_quality("fresh")
    record_sensor_quality("stale")
    record_sensor_quality("missing")
    stats = get_monitoring_stats()
    sq = stats["sensor_quality"]
    assert sq["total_reads"] >= 3
    assert sq["fresh_count"] >= 1
    assert sq["stale_count"] >= 1
    assert sq["missing_count"] >= 1


def test_gemini_token_and_cost_tracking():
    # Test tracking for flash-lite and flash models
    record_gemini_usage(
        model="gemini-3.1-flash-lite",
        prompt_tokens=1000,
        candidate_tokens=200,
        conversation_id="conv_test_1",
    )
    record_gemini_usage(
        model="gemini-3.6-flash",
        prompt_tokens=2000,
        candidate_tokens=500,
        conversation_id="conv_test_1",
    )

    stats = get_monitoring_stats()
    usage = stats["gemini_usage"]

    assert usage["total_calls"] >= 2
    assert usage["total_prompt_tokens"] >= 3000
    assert usage["total_candidate_tokens"] >= 700
    assert usage["total_tokens"] >= 3700
    assert usage["estimated_cost_usd"] > 0
    assert usage["estimated_cost_vnd"] > 0

    # Model breakdown
    assert "gemini-3.1-flash-lite" in usage["by_model"]
    assert "gemini-3.6-flash" in usage["by_model"]

    # Conversation breakdown
    assert "conv_test_1" in usage["top_conversations"]
    assert usage["top_conversations"]["conv_test_1"]["calls"] >= 2
