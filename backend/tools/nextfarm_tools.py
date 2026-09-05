"""
NextFarm Tool Adapter / Mock API — Mục 5 GĐ1 + GĐ2.

Cung cấp các tool gọi NextFarm IoT Service:
- Mọi số đo sensor trả về kèm: measured_at, age_seconds, quality_flag
- Áp dụng IAM/Farm authorization trước MỌI tool call
- Log: tool_name, farm_id, latency, error_rate

QUAN TRỌNG:
- Policy freshness: stale/missing phải nói rõ trong câu trả lời
- Không dùng giá trị cũ như dữ liệu hiện tại khi đã stale
- LLM KHÔNG được tự sinh hoặc suy luận farm_id

PoC: dữ liệu mock. Production: gọi NextFarm REST/gRPC API thực.
"""
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Any
from dataclasses import dataclass

from backend.iam.iam import FarmContext, require_farm_access

logger = logging.getLogger(__name__)

# ─── Freshness Policy ───────────────────────────────────────────────────────
# Ngưỡng thời gian (giây) để xác định fresh/stale/missing
FRESH_THRESHOLD_SECONDS = 600    # 10 phút: fresh
STALE_THRESHOLD_SECONDS = 3600   # 1 giờ: stale
# > 1 giờ hoặc không có dữ liệu: missing


def _compute_quality_flag(measured_at: Optional[datetime]) -> dict:
    """
    Tính quality_flag và age_seconds từ thời điểm đo.

    Returns:
        {
            "quality_flag": "fresh" | "stale" | "missing",
            "age_seconds": int | None,
            "age_human": str,  # "2 phút", "45 phút", "Không có dữ liệu"
            "freshness_warning": str | None  # Cảnh báo cho câu trả lời
        }
    """
    if measured_at is None:
        result = {
            "quality_flag": "missing",
            "age_seconds": None,
            "age_human": "Không có dữ liệu",
            "freshness_warning": (
                "⚠️ Không có dữ liệu sensor cho thông số này. "
                "Thiết bị có thể offline hoặc chưa có phép đo nào."
            ),
        }
        try:
            from backend.monitoring import record_sensor_quality
            record_sensor_quality("missing")
        except Exception:
            pass
        return result

    now = datetime.now(timezone.utc)
    if measured_at.tzinfo is None:
        measured_at = measured_at.replace(tzinfo=timezone.utc)

    age_seconds = int((now - measured_at).total_seconds())

    if age_seconds <= 0:
        age_seconds = 0

    # Tính human-readable age
    if age_seconds < 60:
        age_human = f"{age_seconds} giây"
    elif age_seconds < 3600:
        age_human = f"{age_seconds // 60} phút"
    elif age_seconds < 86400:
        age_human = f"{age_seconds // 3600} giờ {(age_seconds % 3600) // 60} phút"
    else:
        age_human = f"{age_seconds // 86400} ngày"

    if age_seconds <= FRESH_THRESHOLD_SECONDS:
        try:
            from backend.monitoring import record_sensor_quality
            record_sensor_quality("fresh")
        except Exception:
            pass
        return {
            "quality_flag": "fresh",
            "age_seconds": age_seconds,
            "age_human": age_human,
            "freshness_warning": None,
        }
    elif age_seconds <= STALE_THRESHOLD_SECONDS:
        try:
            from backend.monitoring import record_sensor_quality
            record_sensor_quality("stale")
        except Exception:
            pass
        return {
            "quality_flag": "stale",
            "age_seconds": age_seconds,
            "age_human": age_human,
            "freshness_warning": (
                f"⚠️ Dữ liệu cũ ({age_human} trước). "
                "Cảm biến có thể chậm cập nhật hoặc gặp sự cố kết nối."
            ),
        }
    else:
        try:
            from backend.monitoring import record_sensor_quality
            record_sensor_quality("missing")
        except Exception:
            pass
        return {
            "quality_flag": "missing",
            "age_seconds": age_seconds,
            "age_human": age_human,
            "freshness_warning": (
                f"⚠️ Dữ liệu quá cũ ({age_human} trước) — xem như MISSING. "
                "Thiết bị có thể offline. Không nên dùng giá trị này để ra quyết định."
            ),
        }


# ─── Mock Data Store (PoC) ─────────────────────────────────────────────────
# Production: thay bằng HTTP call tới NextFarm API
_now = datetime.now(timezone.utc)

_MOCK_SENSORS: dict[str, dict] = {
    "farm_001:zone_A:soil_moisture": {
        "value": 65.3, "unit": "%", "sensor_type": "soil_moisture",
        "measured_at": _now - timedelta(minutes=5),  # fresh
    },
    "farm_001:zone_B:soil_moisture": {
        "value": 42.1, "unit": "%", "sensor_type": "soil_moisture",
        "measured_at": _now - timedelta(minutes=45),  # stale
    },
    "farm_001:zone_A:temperature": {
        "value": 28.5, "unit": "°C", "sensor_type": "temperature",
        "measured_at": _now - timedelta(minutes=3),  # fresh
    },
    "farm_002:zone_A:soil_moisture": {
        "value": 58.0, "unit": "%", "sensor_type": "soil_moisture",
        "measured_at": _now - timedelta(hours=2),  # missing (>1h)
    },
}

_MOCK_DEVICES: dict[str, dict] = {
    "farm_001:valve_A": {
        "device_id": "valve_A", "device_type": "irrigation_valve",
        "status": "online", "is_active": True,
        "last_seen": _now - timedelta(minutes=2),
    },
    "farm_001:valve_B": {
        "device_id": "valve_B", "device_type": "irrigation_valve",
        "status": "offline", "is_active": False,
        "last_seen": _now - timedelta(hours=3),
    },
    "farm_002:pump_A": {
        "device_id": "pump_A", "device_type": "pump",
        "status": "online", "is_active": False,
        "last_seen": _now - timedelta(minutes=10),
    },
}

_MOCK_SCHEDULES: list[dict] = [
    {
        "schedule_id": "sch_001", "farm_id": "farm_001", "zone_id": "zone_A",
        "device_id": "valve_A", "start_time": "06:00", "duration_minutes": 30,
        "repeat": "daily", "is_active": True,
        "next_run": (_now + timedelta(hours=4)).isoformat(),
    },
]

_MOCK_ALERTS: list[dict] = [
    {
        "alert_id": "alt_001", "farm_id": "farm_001", "zone_id": "zone_B",
        "alert_type": "sensor_stale", "severity": "warning",
        "message": "Cảm biến độ ẩm zone B không cập nhật > 45 phút",
        "created_at": (_now - timedelta(minutes=40)).isoformat(),
        "is_resolved": False,
    },
]

_MOCK_IRRIGATION_HISTORY: list[dict] = [
    {
        "event_id": "irr_001", "farm_id": "farm_001", "zone_id": "zone_A",
        "device_id": "valve_A", "start_time": (_now - timedelta(hours=6)).isoformat(),
        "end_time": (_now - timedelta(hours=5, minutes=30)).isoformat(),
        "duration_minutes": 30, "water_volume_liters": 150.0,
        "trigger": "scheduled",
    },
]


# ─── Tool Functions ──────────────────────────────────────────────────────────

def _log_tool_call(tool_name: str, farm_id: str, latency_ms: float, success: bool):
    """Ghi log cho mỗi tool call: tool, farm, latency, kết quả."""
    status = "OK" if success else "ERROR"
    logger.info(
        f"TOOL_CALL [{status}] tool={tool_name} farm={farm_id} latency={latency_ms:.1f}ms"
    )
    # Push metric vào monitoring module (non-blocking, best-effort)
    try:
        from backend.monitoring import record_tool_call
        record_tool_call(tool_name, farm_id, latency_ms, success)
    except Exception:
        pass


def get_latest_sensor(
    farm_context: FarmContext,
    farm_id: str,
    zone_id: str,
    sensor_type: str,
) -> dict:
    """
    Lấy số đo sensor mới nhất cho farm/zone/loại.

    QUAN TRỌNG: Kết quả luôn kèm measured_at, age_seconds, quality_flag.
    Caller phải truyền freshness_warning vào câu trả lời nếu stale/missing.

    Args:
        farm_context: FarmContext đã xác thực (từ IAM)
        farm_id: ID farm (không để LLM tự sinh)
        zone_id: ID zone
        sensor_type: Loại sensor (soil_moisture, temperature, humidity...)

    Returns:
        {
            "found": bool,
            "farm_id": str,
            "zone_id": str,
            "sensor_type": str,
            "value": float | None,
            "unit": str | None,
            "measured_at": str | None,  # ISO8601
            "age_seconds": int | None,
            "age_human": str,
            "quality_flag": "fresh" | "stale" | "missing",
            "freshness_warning": str | None
        }
    """
    t0 = time.time()
    try:
        # IAM check bắt buộc
        require_farm_access(farm_context, farm_id, tool_name="get_latest_sensor")

        key = f"{farm_id}:{zone_id}:{sensor_type}"
        raw = _MOCK_SENSORS.get(key)

        if raw is None:
            # Fallback simulator: sinh dữ liệu cho các nông trại giả lập
            default_units = {
                "soil_moisture": ("%", 62.5),
                "temperature": ("°C", 28.5),
                "humidity": ("%", 78.0),
                "rainfall": ("mm", 0.0),
                "ph": ("pH", 6.2),
                "ec": ("mS/cm", 1.1),
            }
            if sensor_type in default_units:
                unit, val = default_units[sensor_type]
                raw = {
                    "value": val,
                    "unit": unit,
                    "sensor_type": sensor_type,
                    "measured_at": datetime.now(timezone.utc) - timedelta(minutes=3),
                }

        if raw is None:
            freshness = _compute_quality_flag(None)
            _log_tool_call("get_latest_sensor", farm_id, (time.time()-t0)*1000, True)
            return {
                "found": False,
                "farm_id": farm_id,
                "zone_id": zone_id,
                "sensor_type": sensor_type,
                "value": None,
                "unit": None,
                "measured_at": None,
                **freshness,
            }

        freshness = _compute_quality_flag(raw["measured_at"])
        _log_tool_call("get_latest_sensor", farm_id, (time.time()-t0)*1000, True)
        return {
            "found": True,
            "farm_id": farm_id,
            "zone_id": zone_id,
            "sensor_type": sensor_type,
            "value": raw["value"],
            "unit": raw["unit"],
            "measured_at": raw["measured_at"].isoformat(),
            **freshness,
        }

    except PermissionError as e:
        _log_tool_call("get_latest_sensor", farm_id, (time.time()-t0)*1000, False)
        return {
            "found": False,
            "error": str(e),
            "error_type": "authorization_denied",
        }
    except Exception as e:
        logger.error(f"get_latest_sensor error: {e}")
        _log_tool_call("get_latest_sensor", farm_id, (time.time()-t0)*1000, False)
        return {"found": False, "error": str(e), "error_type": "tool_error"}


def get_device_status(
    farm_context: FarmContext,
    farm_id: str,
    device_id: str,
) -> dict:
    """
    Lấy trạng thái thiết bị.

    Returns:
        {
            "found": bool,
            "device_id": str,
            "device_type": str,
            "status": "online" | "offline" | "unknown",
            "is_active": bool,
            "last_seen": str | None,
            "age_seconds": int | None,
            "quality_flag": str
        }
    """
    t0 = time.time()
    try:
        require_farm_access(farm_context, farm_id, tool_name="get_device_status")

        key = f"{farm_id}:{device_id}"
        raw = _MOCK_DEVICES.get(key)

        if raw is None:
            # Fallback simulator cho thiết bị giả lập
            raw = {
                "device_id": device_id,
                "device_type": "irrigation_valve" if "valve" in device_id else "pump",
                "status": "online",
                "is_active": True,
                "last_seen": datetime.now(timezone.utc) - timedelta(minutes=2),
            }

        freshness = _compute_quality_flag(raw.get("last_seen"))
        _log_tool_call("get_device_status", farm_id, (time.time()-t0)*1000, True)
        return {
            "found": True,
            "farm_id": farm_id,
            "device_id": device_id,
            "device_type": raw.get("device_type"),
            "status": raw.get("status"),
            "is_active": raw.get("is_active"),
            "last_seen": raw["last_seen"].isoformat() if raw.get("last_seen") else None,
            "age_seconds": freshness["age_seconds"],
            "age_human": freshness["age_human"],
            "quality_flag": freshness["quality_flag"],
            "freshness_warning": freshness.get("freshness_warning"),
        }

    except PermissionError as e:
        _log_tool_call("get_device_status", farm_id, (time.time()-t0)*1000, False)
        return {"found": False, "error": str(e), "error_type": "authorization_denied"}
    except Exception as e:
        logger.error(f"get_device_status error: {e}")
        _log_tool_call("get_device_status", farm_id, (time.time()-t0)*1000, False)
        return {"found": False, "error": str(e), "error_type": "tool_error"}


def get_irrigation_schedule(
    farm_context: FarmContext,
    farm_id: str,
    zone_id: Optional[str] = None,
) -> dict:
    """Lấy lịch tưới của farm/zone."""
    t0 = time.time()
    try:
        require_farm_access(farm_context, farm_id, tool_name="get_irrigation_schedule")

        schedules = [
            s for s in _MOCK_SCHEDULES
            if s["farm_id"] == farm_id
            and (zone_id is None or s.get("zone_id") == zone_id)
        ]
        _log_tool_call("get_irrigation_schedule", farm_id, (time.time()-t0)*1000, True)
        return {
            "found": len(schedules) > 0,
            "farm_id": farm_id,
            "zone_id": zone_id,
            "schedules": schedules,
            "count": len(schedules),
        }

    except PermissionError as e:
        _log_tool_call("get_irrigation_schedule", farm_id, (time.time()-t0)*1000, False)
        return {"found": False, "error": str(e), "error_type": "authorization_denied"}
    except Exception as e:
        logger.error(f"get_irrigation_schedule error: {e}")
        _log_tool_call("get_irrigation_schedule", farm_id, (time.time()-t0)*1000, False)
        return {"found": False, "error": str(e), "error_type": "tool_error"}


def get_irrigation_history(
    farm_context: FarmContext,
    farm_id: str,
    zone_id: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """Lấy lịch sử tưới."""
    t0 = time.time()
    try:
        require_farm_access(farm_context, farm_id, tool_name="get_irrigation_history")

        events = [
            e for e in _MOCK_IRRIGATION_HISTORY
            if e["farm_id"] == farm_id
            and (zone_id is None or e.get("zone_id") == zone_id)
        ][:limit]

        _log_tool_call("get_irrigation_history", farm_id, (time.time()-t0)*1000, True)
        return {
            "found": len(events) > 0,
            "farm_id": farm_id,
            "zone_id": zone_id,
            "events": events,
            "count": len(events),
        }

    except PermissionError as e:
        _log_tool_call("get_irrigation_history", farm_id, (time.time()-t0)*1000, False)
        return {"found": False, "error": str(e), "error_type": "authorization_denied"}
    except Exception as e:
        logger.error(f"get_irrigation_history error: {e}")
        _log_tool_call("get_irrigation_history", farm_id, (time.time()-t0)*1000, False)
        return {"found": False, "error": str(e), "error_type": "tool_error"}


def get_alerts(
    farm_context: FarmContext,
    farm_id: str,
    severity: Optional[str] = None,
    include_resolved: bool = False,
) -> dict:
    """Lấy danh sách cảnh báo của farm."""
    t0 = time.time()
    try:
        require_farm_access(farm_context, farm_id, tool_name="get_alerts")

        alerts = [
            a for a in _MOCK_ALERTS
            if a["farm_id"] == farm_id
            and (severity is None or a.get("severity") == severity)
            and (include_resolved or not a.get("is_resolved", False))
        ]
        _log_tool_call("get_alerts", farm_id, (time.time()-t0)*1000, True)
        return {
            "found": len(alerts) > 0,
            "farm_id": farm_id,
            "alerts": alerts,
            "count": len(alerts),
        }

    except PermissionError as e:
        _log_tool_call("get_alerts", farm_id, (time.time()-t0)*1000, False)
        return {"found": False, "error": str(e), "error_type": "authorization_denied"}
    except Exception as e:
        logger.error(f"get_alerts error: {e}")
        _log_tool_call("get_alerts", farm_id, (time.time()-t0)*1000, False)
        return {"found": False, "error": str(e), "error_type": "tool_error"}


def get_command_history(
    farm_context: FarmContext,
    farm_id: str,
    device_id: Optional[str] = None,
    limit: int = 10,
) -> dict:
    """Lấy log lệnh điều khiển thiết bị."""
    t0 = time.time()
    try:
        require_farm_access(farm_context, farm_id, tool_name="get_command_history")

        # Mock: chưa có lệnh nào (PoC read-only)
        _log_tool_call("get_command_history", farm_id, (time.time()-t0)*1000, True)
        return {
            "found": False,
            "farm_id": farm_id,
            "device_id": device_id,
            "commands": [],
            "count": 0,
            "note": "PoC read-only — chưa có lịch sử lệnh",
        }

    except PermissionError as e:
        _log_tool_call("get_command_history", farm_id, (time.time()-t0)*1000, False)
        return {"found": False, "error": str(e), "error_type": "authorization_denied"}
    except Exception as e:
        logger.error(f"get_command_history error: {e}")
        _log_tool_call("get_command_history", farm_id, (time.time()-t0)*1000, False)
        return {"found": False, "error": str(e), "error_type": "tool_error"}


def get_user_permissions(
    farm_context: FarmContext,
    target_username: str,
) -> dict:
    """
    Lấy thông tin quyền của user.
    Chỉ admin hoặc chính user đó mới được xem.
    """
    if farm_context.role != "admin" and farm_context.username != target_username:
        logger.warning(
            f"IAM DENY: user {farm_context.username} cố xem quyền của {target_username}"
        )
        return {
            "found": False,
            "error": "Không có quyền xem thông tin quyền của user khác",
            "error_type": "authorization_denied",
        }

    from backend.iam.iam import resolve_allowed_farm_ids
    allowed = resolve_allowed_farm_ids(target_username)
    return {
        "found": True,
        "username": target_username,
        "allowed_farm_ids": allowed,
    }
