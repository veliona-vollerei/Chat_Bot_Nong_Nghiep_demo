"""
Sensor Simulator — GĐ3.

Sinh chuỗi dữ liệu cảm biến 10 phút/lần, 14-30 ngày:
- Soil moisture: mô phỏng theo mưa + bay hơi + tưới
- Temperature/humidity: theo mùa và vùng khí hậu
- Fault injection: chèn lỗi cố định (stale, offline, spike)

Physics model đơn giản (Thornthwaite-style):
- ET_day = 0.0023 * (T_avg + 17.8) * TD^0.5 * Ra (mm/day)
- Soil moisture giảm theo ET, tăng theo mưa và tưới

Output: list[SensorReading] có thể lưu JSON hoặc ghi thẳng vào nextfarm_tools mock.
"""
import math
import random
import json
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


# ─── Constants ────────────────────────────────────────────────────────────
SEED = 42
INTERVAL_MINUTES = 10
DAYS_DEFAULT = 14


@dataclass
class SensorReading:
    farm_id: str
    zone_id: str
    sensor_type: str
    value: float
    unit: str
    measured_at: str   # ISO 8601
    quality_flag: str  # "fresh" | "stale" | "missing" | "fault"
    fault_type: Optional[str] = None  # None | "offline" | "spike" | "drift" | "frozen" | "duplicated_event" | "clock_skew" | "command_failed"
    data_source: str = "fully_synthetic"  # "open_meteo_driven" | "device_simulated" | "fully_synthetic"


@dataclass
class IrrigationEvent:
    farm_id: str
    zone_id: str
    device_id: str
    started_at: str
    ended_at: str
    duration_minutes: int
    volume_liters: float
    trigger: str  # "auto" | "manual"
    data_source: str = "device_simulated"  # "open_meteo_driven" | "device_simulated" | "fully_synthetic"


@dataclass
class SimulatorOutput:
    sensor_readings: list[SensorReading]
    irrigation_events: list[IrrigationEvent]
    total_readings: int
    total_irrigations: int
    farm_id: str
    zone_ids: list[str]
    from_dt: str
    to_dt: str


# ─── Climate Profiles by Region ──────────────────────────────────────────
# (T_avg_C, T_range, humidity_pct, daily_rain_prob, rain_amount_mm)
CLIMATE_PROFILES = {
    "ĐBSCL":   (28.0, 6.0, 80.0, 0.35, 15.0),
    "Tây Nguyên": (22.0, 10.0, 75.0, 0.25, 10.0),
    "Đông Nam Bộ": (27.0, 7.0, 78.0, 0.25, 12.0),
    "ĐBSH":    (24.0, 12.0, 82.0, 0.30, 8.0),
    "default": (27.0, 8.0, 80.0, 0.30, 10.0),
}

SENSOR_UNITS = {
    "soil_moisture": "%",
    "temperature": "°C",
    "humidity": "%",
    "rainfall": "mm",
    "ph": "pH",
    "ec": "mS/cm",
}

SENSOR_RANGES = {
    "soil_moisture": (20.0, 90.0),
    "temperature":   (18.0, 38.0),
    "humidity":      (50.0, 98.0),
    "rainfall":      (0.0, 80.0),
    "ph":            (4.5, 8.5),
    "ec":            (0.1, 3.5),
}


def _get_climate(region: str) -> tuple:
    for key, profile in CLIMATE_PROFILES.items():
        if key in region:
            return profile
    return CLIMATE_PROFILES["default"]


def _thornthwaite_et(T_avg: float, day_of_year: int, lat_deg: float = 10.0) -> float:
    """
    Ước tính bốc hơi tiềm năng (ET0, mm/ngày) theo Thornthwaite đơn giản.
    Chỉ dùng nhiệt độ (không cần bức xạ đầy đủ).
    """
    if T_avg < 0:
        return 0.0
    # Ước tính số giờ ngày dựa trên vĩ độ (sin curve)
    decl = 23.45 * math.sin(math.radians(360/365 * (day_of_year - 81)))
    phi = math.radians(lat_deg)
    d = math.radians(decl)
    try:
        hs = math.degrees(math.acos(-math.tan(phi) * math.tan(d)))
    except ValueError:
        hs = 90.0
    N = 2 * hs / 15  # giờ ngày
    # Thornthwaite: ET = 1.6 * (10*T/I)^a * (N/12) * (d/30)
    I = 12.0  # chỉ số nhiệt (giả định vùng nhiệt đới)
    a = 0.49 + 0.0179 * I - 0.0000771 * I**2 + 0.000000675 * I**3
    if I > 0:
        ET = 1.6 * (10 * T_avg / I) ** a * (N / 12)
    else:
        ET = 0.0
    return max(0.0, ET)


def simulate_zone(
    farm_id: str,
    zone_id: str,
    sensor_types: list[str],
    region: str = "ĐBSCL",
    lat: float = 10.0,
    n_days: int = DAYS_DEFAULT,
    seed: int = SEED,
    fault_scenarios: Optional[list[dict]] = None,
) -> SimulatorOutput:
    """
    Sinh chuỗi sensor readings và irrigation events cho 1 zone.

    Args:
        fault_scenarios: List of {sensor_type, start_offset_hours, duration_hours, fault_type}
    """
    rng = random.Random(seed)
    T_avg, T_range, hum_base, rain_prob, rain_amount = _get_climate(region)

    from_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    from_dt -= timedelta(days=n_days)
    to_dt = datetime.now()

    readings: list[SensorReading] = []
    irrigations: list[IrrigationEvent] = []

    # State
    soil_moisture = rng.uniform(40.0, 70.0)
    current_dt = from_dt

    # Build fault schedule
    fault_schedule: dict[str, list] = {st: [] for st in sensor_types}
    if fault_scenarios:
        for fs in fault_scenarios:
            st = fs["sensor_type"]
            start = from_dt + timedelta(hours=fs.get("start_offset_hours", 24))
            end = start + timedelta(hours=fs.get("duration_hours", 4))
            if st in fault_schedule:
                fault_schedule[st].append({
                    "start": start, "end": end,
                    "fault_type": fs.get("fault_type", "offline")
                })

    # Lịch tưới (mỗi 2-3 ngày nếu soil_moisture < 45%)
    last_irrigation = from_dt - timedelta(days=2)

    while current_dt <= to_dt:
        day_of_year = current_dt.timetuple().tm_yday
        hour = current_dt.hour

        # Nhiệt độ theo giờ (thấp nhất 5-6h, cao nhất 13-14h)
        T = T_avg + T_range * math.sin(math.radians((hour - 6) * 15 - 90))
        T += rng.gauss(0, 0.5)  # noise

        # Độ ẩm (ngược chiều nhiệt độ)
        H = hum_base - (T - T_avg) * 2.0 + rng.gauss(0, 2.0)
        H = max(40.0, min(99.0, H))

        # Mưa: chỉ xảy ra 1 lần/ngày trong khoảng 14-17h
        rain = 0.0
        if 14 <= hour <= 16 and rng.random() < rain_prob / 3:
            rain = rng.expovariate(1.0 / rain_amount)
            soil_moisture = min(soil_moisture + rain * 0.3, 90.0)

        # ET (mỗi giờ)
        et_day = _thornthwaite_et(T, day_of_year, lat)
        et_hour = et_day / 24
        soil_moisture = max(soil_moisture - et_hour * 0.5, 10.0)

        # Auto irrigation nếu đất quá khô
        if (soil_moisture < 35.0 and
                (current_dt - last_irrigation).total_seconds() > 3600 * 18):
            # Tưới 30-60 phút
            dur = rng.randint(30, 60)
            volume = rng.uniform(800, 2000)
            irrigations.append(IrrigationEvent(
                farm_id=farm_id,
                zone_id=zone_id,
                device_id=f"{zone_id}_valve_01",
                started_at=current_dt.isoformat(),
                ended_at=(current_dt + timedelta(minutes=dur)).isoformat(),
                duration_minutes=dur,
                volume_liters=round(volume, 1),
                trigger="auto",
            ))
            soil_moisture = min(soil_moisture + volume / 500, 85.0)
            last_irrigation = current_dt

        # Sinh readings
        for st in sensor_types:
            unit = SENSOR_UNITS.get(st, "")
            lo, hi = SENSOR_RANGES.get(st, (0.0, 100.0))
            fault_type = None
            quality_flag = "fresh"
            value = None

            # Check fault
            for f in fault_schedule.get(st, []):
                if f["start"] <= current_dt <= f["end"]:
                    fault_type = f["fault_type"]
                    break

            if fault_type == "offline":
                quality_flag = "missing"
                value = None
            elif fault_type == "spike":
                value = round(rng.uniform(hi * 1.5, hi * 2), 2)
                quality_flag = "fault"
            elif fault_type == "drift":
                # Drift: giá trị lệch dần
                drift = (current_dt - fault_schedule[st][0]["start"]).total_seconds() / 3600 * 2
                value = _sensor_value(st, soil_moisture, T, H, rain, rng) + drift
                value = round(max(lo * 0.5, value), 2)
                quality_flag = "fault"
            else:
                value = _sensor_value(st, soil_moisture, T, H, rain, rng)
                value = round(max(lo, min(hi, value)), 2)
                quality_flag = "fresh"

            # Xác định data_source dựa trên loại cảm biến
            ds = "open_meteo_driven" if st in ("temperature", "humidity", "rainfall") else "fully_synthetic"

            readings.append(SensorReading(
                farm_id=farm_id,
                zone_id=zone_id,
                sensor_type=st,
                value=value,
                unit=unit,
                measured_at=current_dt.isoformat(),
                quality_flag=quality_flag,
                fault_type=fault_type,
                data_source=ds,
            ))

        current_dt += timedelta(minutes=INTERVAL_MINUTES)

    return SimulatorOutput(
        sensor_readings=readings,
        irrigation_events=irrigations,
        total_readings=len(readings),
        total_irrigations=len(irrigations),
        farm_id=farm_id,
        zone_ids=[zone_id],
        from_dt=from_dt.isoformat(),
        to_dt=to_dt.isoformat(),
    )


def _sensor_value(st: str, soil_moisture: float, T: float, H: float, rain: float, rng: random.Random) -> float:
    """Tính giá trị cảm biến từ trạng thái vật lý."""
    noise = rng.gauss(0, 0.5)
    if st == "soil_moisture":
        return soil_moisture + noise
    elif st == "temperature":
        return T + noise
    elif st == "humidity":
        return H + noise * 2
    elif st == "rainfall":
        return round(max(0, rain + abs(noise) * 0.1), 2)
    elif st == "ph":
        # pH dao động nhẹ theo độ ẩm đất
        return 6.0 + (soil_moisture - 50) * 0.02 + noise * 0.1
    elif st == "ec":
        return 0.5 + (100 - soil_moisture) * 0.02 + noise * 0.05
    return 0.0


def save_output(output: SimulatorOutput, path: Path):
    """Lưu SimulatorOutput ra JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(output)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ Saved {output.total_readings} readings, {output.total_irrigations} irrigations → {path}")


if __name__ == "__main__":
    import sys, os, argparse
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

    parser = argparse.ArgumentParser()
    parser.add_argument("--farm_id", default="farm_001")
    parser.add_argument("--zone_id", default="farm_001_z01")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--output", default="data/sensor_sim.json")
    args = parser.parse_args()

    # Fault scenarios mẫu
    faults = [
        {"sensor_type": "soil_moisture", "start_offset_hours": 48, "duration_hours": 6, "fault_type": "offline"},
        {"sensor_type": "temperature", "start_offset_hours": 72, "duration_hours": 2, "fault_type": "spike"},
    ]

    out = simulate_zone(
        farm_id=args.farm_id,
        zone_id=args.zone_id,
        sensor_types=["soil_moisture", "temperature", "humidity", "rainfall", "ph"],
        region="ĐBSCL",
        n_days=args.days,
        fault_scenarios=faults,
    )
    save_output(out, Path(args.output))
    print(f"Simulated {args.days} days: {out.total_readings} readings")
