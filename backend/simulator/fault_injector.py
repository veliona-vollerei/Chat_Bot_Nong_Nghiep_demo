"""
Fault Injector — GĐ3 Farm Simulator.

Cung cấp cơ chế chèn lỗi giả lập có thể tái hiện (deterministic & reproducible)
phục vụ benchmark và kiểm thử hệ thống:
- offline: Cảm biến mất kết nối (missing)
- spike: Đột biến bất thường (out of physical range, fault)
- drift: Trôi giá trị dần theo thời gian do suy giảm hiệu chuẩn (fault)
- frozen: Kẹt giá trị không đổi (fault)
- device_offline: Thiết bị (van, bơm) không phản hồi lệnh

Các kịch bản lỗi được gán cố định theo scenario_id, farm_id, zone_id, sensor_id / device_id.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Optional, Any
import json
import logging

logger = logging.getLogger("fault_injector")


@dataclass
class FaultScenario:
    scenario_id: str
    farm_id: str
    zone_id: Optional[str]
    target_type: str  # "sensor" | "device"
    target_name: str  # sensor_type (e.g. "soil_moisture") or device_id (e.g. "valve_01")
    fault_type: str   # "offline" | "spike" | "drift" | "frozen"
    start_time: str   # ISO format
    end_time: str     # ISO format
    params: dict = field(default_factory=dict)
    description: str = ""


# ─── Standard Benchmark Fault Scenarios ──────────────────────────────────
STANDARD_BENCHMARK_FAULTS = [
    FaultScenario(
        scenario_id="SCENARIO_OFFLINE_SM_FARM001",
        farm_id="farm_001",
        zone_id="farm_001_z01",
        target_type="sensor",
        target_name="soil_moisture",
        fault_type="offline",
        start_time="2026-09-01T08:00:00",
        end_time="2026-09-03T18:00:00",
        params={"reason": "sensor_battery_depleted"},
        description="Cảm biến độ ẩm đất khu 1 nông trại 001 hết pin, offline 2.5 ngày",
    ),
    FaultScenario(
        scenario_id="SCENARIO_SPIKE_TEMP_FARM002",
        farm_id="farm_002",
        zone_id="farm_002_z02",
        target_type="sensor",
        target_name="temperature",
        fault_type="spike",
        start_time="2026-09-02T12:00:00",
        end_time="2026-09-02T15:00:00",
        params={"spike_value": 68.5},
        description="Nhiệt độ nhảy đột biến 68.5°C do bức xạ nhiệt chiếu trực tiếp vào vỏ node",
    ),
    FaultScenario(
        scenario_id="SCENARIO_DRIFT_EC_FARM003",
        farm_id="farm_003",
        zone_id="farm_003_z01",
        target_type="sensor",
        target_name="ec",
        fault_type="drift",
        start_time="2026-09-01T00:00:00",
        end_time="2026-09-05T00:00:00",
        params={"rate_per_day": 0.35},
        description="Cảm biến EC trôi giá trị tăng dần 0.35 mS/cm mỗi ngày do bám cặn phân bón",
    ),
    FaultScenario(
        scenario_id="SCENARIO_FROZEN_HUMIDITY_FARM004",
        farm_id="farm_004",
        zone_id="farm_004_z01",
        target_type="sensor",
        target_name="humidity",
        fault_type="frozen",
        start_time="2026-09-02T00:00:00",
        end_time="2026-09-04T00:00:00",
        params={"frozen_value": 75.0},
        description="Độ ẩm không khí bị treo cứng ở 75.0% suốt 48 giờ",
    ),
    FaultScenario(
        scenario_id="SCENARIO_VALVE_OFFLINE_FARM001",
        farm_id="farm_001",
        zone_id="farm_001_z01",
        target_type="device",
        target_name="valve_01",
        fault_type="offline",
        start_time="2026-09-03T06:00:00",
        end_time="2026-09-06T00:00:00",
        params={"power_cut": True},
        description="Van điện từ tưới khu 1 đứt cáp nguồn, không phản hồi lệnh bật van",
    ),
]


class FaultInjectorRegistry:
    """Quản lý và tra cứu các kịch bản lỗi đang hiệu lực."""

    def __init__(self, scenarios: Optional[list[FaultScenario]] = None):
        self.scenarios: list[FaultScenario] = scenarios or list(STANDARD_BENCHMARK_FAULTS)

    def add_scenario(self, scenario: FaultScenario):
        self.scenarios.append(scenario)

    def find_active_fault(
        self,
        farm_id: str,
        target_name: str,
        timestamp: datetime,
        zone_id: Optional[str] = None,
    ) -> Optional[FaultScenario]:
        """Tìm xem có kịch bản lỗi nào đang diễn ra tại thời điểm timestamp không."""
        for sc in self.scenarios:
            if sc.farm_id != farm_id:
                continue
            if zone_id and sc.zone_id and sc.zone_id != zone_id:
                continue
            if sc.target_name != target_name:
                continue
            try:
                st = datetime.fromisoformat(sc.start_time)
                et = datetime.fromisoformat(sc.end_time)
                if st <= timestamp <= et:
                    return sc
            except Exception:
                continue
        return None

    def apply_sensor_fault(
        self,
        reading_val: Optional[float],
        farm_id: str,
        zone_id: str,
        sensor_type: str,
        dt: datetime,
    ) -> tuple[Optional[float], str, Optional[str]]:
        """
        Áp dụng lỗi lên giá trị cảm biến.
        
        Returns:
            (new_value, quality_flag, fault_type)
        """
        active_fault = self.find_active_fault(farm_id, sensor_type, dt, zone_id=zone_id)
        if not active_fault:
            return reading_val, "fresh", None

        ftype = active_fault.fault_type
        if ftype == "offline":
            return None, "missing", "offline"
        elif ftype == "spike":
            spike_v = active_fault.params.get("spike_value", 99.9)
            return spike_v, "fault", "spike"
        elif ftype == "drift":
            st = datetime.fromisoformat(active_fault.start_time)
            days = (dt - st).total_seconds() / 86400.0
            rate = active_fault.params.get("rate_per_day", 0.2)
            base_v = reading_val if reading_val is not None else 50.0
            return round(base_v + days * rate, 2), "fault", "drift"
        elif ftype == "frozen":
            frozen_v = active_fault.params.get("frozen_value", reading_val or 50.0)
            return frozen_v, "fault", "frozen"

        return reading_val, "fresh", None


# Singleton instance
default_fault_injector = FaultInjectorRegistry()
