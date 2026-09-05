"""
Tool Monitoring API — GĐ2.

Các endpoint cung cấp:
  GET  /api/tools/sensor     — Đọc cảm biến theo farm_id/zone_id (có IAM)
  GET  /api/tools/status     — Trạng thái thiết bị
  GET  /api/tools/irrigation — Lịch tưới
  GET  /api/tools/alerts     — Cảnh báo
  GET  /api/tools/monitor    — Dashboard: latency, error rate, freshness stats

Tất cả tool calls đều:
  1. Kiểm tra IAM/farm authorization
  2. Trả về quality_flag (fresh/stale/missing)
  3. Ghi tool_latency, error_rate vào log
"""
import time
import logging
from typing import Optional
# pyrefly: ignore [missing-import]
from fastapi import APIRouter, HTTPException, Header

from backend.iam.iam import build_farm_context, require_farm_access
from backend.tools.nextfarm_tools import (
    get_latest_sensor,
    get_device_status,
    get_irrigation_schedule,
    get_irrigation_history,
    get_alerts,
    get_command_history,
)
from backend.utils.versioning import SYSTEM_VERSION, version_log_prefix

logger = logging.getLogger(__name__)

# ─── Router ────────────────────────────────────────────────────────────────
router = APIRouter(prefix="/api/tools", tags=["NextFarm Tools"])

# ─── In-memory monitoring stats (PoC: production dùng Prometheus/metrics DB) ─
_tool_stats: dict[str, dict] = {}   # tool_name → {calls, errors, total_latency_ms}


def _record_stat(tool_name: str, latency_ms: float, error: bool = False):
    """Ghi stat vào in-memory store."""
    if tool_name not in _tool_stats:
        _tool_stats[tool_name] = {"calls": 0, "errors": 0, "total_latency_ms": 0.0}
    s = _tool_stats[tool_name]
    s["calls"] += 1
    s["total_latency_ms"] += latency_ms
    if error:
        s["errors"] += 1


def _run_tool(tool_name: str, fn, *args, **kwargs) -> dict:
    """Wrapper: gọi tool, đo latency, ghi stat."""
    t0 = time.time()
    try:
        result = fn(*args, **kwargs)
        latency_ms = (time.time() - t0) * 1000
        _record_stat(tool_name, latency_ms, error=bool(result.get("error")))
        result["_latency_ms"] = round(latency_ms, 1)
        logger.debug(f"{version_log_prefix()} tool={tool_name} latency={latency_ms:.1f}ms "
                     f"quality={result.get('quality_flag', '?')}")
        return result
    except Exception as e:
        latency_ms = (time.time() - t0) * 1000
        _record_stat(tool_name, latency_ms, error=True)
        logger.error(f"Tool {tool_name} exception: {e}")
        raise


def _build_ctx(username: Optional[str], farm_id: str):
    """Tạo FarmContext từ username và farm_id (frontend truyền vào, không LLM)."""
    return build_farm_context(
        username=username or "anonymous",
        user_id=username or "0",
        role="user",
        farm_id=farm_id,
    )


# ─── GET /api/tools/sensor ──────────────────────────────────────────────────
@router.get("/sensor")
async def api_get_sensor(
    farm_id: str,
    zone_id: str,
    sensor_type: str = "soil_moisture",
    x_username: Optional[str] = Header(None),
):
    """
    Đọc giá trị cảm biến mới nhất từ farm/zone.

    Headers:
        X-Username: tên user (từ auth middleware)

    Query params:
        farm_id, zone_id, sensor_type (soil_moisture, temperature, humidity, rainfall, ph, ec)
    """
    farm_ctx = _build_ctx(x_username, farm_id)
    # IAM check — 403 nếu không có quyền
    try:
        require_farm_access(farm_ctx, farm_id, "get_latest_sensor")
    except PermissionError as e:
        logger.warning(f"IAM DENY /api/tools/sensor: user={x_username} farm={farm_id}")
        raise HTTPException(status_code=403, detail=str(e))

    result = _run_tool("get_latest_sensor", get_latest_sensor,
                       farm_ctx, farm_id, zone_id, sensor_type)

    if result.get("error_type") == "authorization_denied":
        raise HTTPException(status_code=403, detail=result.get("error"))

    return result


# ─── GET /api/tools/device ──────────────────────────────────────────────────
@router.get("/device")
async def api_get_device_status(
    farm_id: str,
    device_id: str,
    x_username: Optional[str] = Header(None),
):
    """Trạng thái thiết bị (valve, pump, sensor node...)."""
    farm_ctx = _build_ctx(x_username, farm_id)
    try:
        require_farm_access(farm_ctx, farm_id, "get_device_status")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    result = _run_tool("get_device_status", get_device_status,
                       farm_ctx, farm_id, device_id)
    return result


# ─── GET /api/tools/irrigation/schedule ───────────────────────────────────
@router.get("/irrigation/schedule")
async def api_get_irrigation_schedule(
    farm_id: str,
    zone_id: str,
    x_username: Optional[str] = Header(None),
):
    """Lịch tưới được lập trình cho zone."""
    farm_ctx = _build_ctx(x_username, farm_id)
    try:
        require_farm_access(farm_ctx, farm_id, "get_irrigation_schedule")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    result = _run_tool("get_irrigation_schedule", get_irrigation_schedule,
                       farm_ctx, farm_id, zone_id)
    return result


# ─── GET /api/tools/irrigation/history ────────────────────────────────────
@router.get("/irrigation/history")
async def api_get_irrigation_history(
    farm_id: str,
    zone_id: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    x_username: Optional[str] = Header(None),
):
    """Lịch sử tưới (thực tế đã thực hiện)."""
    farm_ctx = _build_ctx(x_username, farm_id)
    try:
        require_farm_access(farm_ctx, farm_id, "get_irrigation_history")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    result = _run_tool("get_irrigation_history", get_irrigation_history,
                       farm_ctx, farm_id, zone_id, from_date, to_date)
    return result


# ─── GET /api/tools/alerts ─────────────────────────────────────────────────
@router.get("/alerts")
async def api_get_alerts(
    farm_id: str,
    severity: str = "all",
    x_username: Optional[str] = Header(None),
):
    """Cảnh báo từ hệ thống IoT (drought, overwater, device_fault...)."""
    farm_ctx = _build_ctx(x_username, farm_id)
    try:
        require_farm_access(farm_ctx, farm_id, "get_alerts")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    result = _run_tool("get_alerts", get_alerts, farm_ctx, farm_id, severity)
    return result


# ─── GET /api/tools/monitor ────────────────────────────────────────────────
@router.get("/monitor")
async def api_get_monitoring_dashboard():
    """
    Dashboard monitoring tool calls.
    Trả về: latency trung bình, error rate, số lần gọi theo từng tool.
    Production: thay bằng Prometheus/Grafana metrics endpoint.
    """
    dashboard = {}
    for tool_name, s in _tool_stats.items():
        calls = s["calls"]
        errors = s["errors"]
        avg_latency = s["total_latency_ms"] / calls if calls > 0 else 0.0
        error_rate = errors / calls if calls > 0 else 0.0
        dashboard[tool_name] = {
            "calls": calls,
            "errors": errors,
            "error_rate_pct": round(error_rate * 100, 1),
            "avg_latency_ms": round(avg_latency, 1),
            "status": "ok" if error_rate < 0.05 else "degraded",
        }

    return {
        "system_version": SYSTEM_VERSION,
        "tool_stats": dashboard,
        "total_tools": len(dashboard),
        "degraded_tools": [t for t, v in dashboard.items() if v["status"] == "degraded"],
    }
