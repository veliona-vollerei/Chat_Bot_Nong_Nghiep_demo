"""
Unit tests cho GĐ2 và GĐ3:
- Farm Generator & Dataset Integrity
- Sensor Simulator & Physics Model
- Open-Meteo Client & Synthetic Weather Fallback
- Water Balance Model (FAO-56 Soil Moisture Dynamics)
- Fault Injector (Deterministic Faults & Quality Flags)
- NextFarm Tools & Freshness Policy
- Benchmark Builder (260+ questions schema & category breakdown)
"""

# pyrefly: ignore [missing-import]
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Simulator modules
from backend.simulator.farm_generator import generate_farms, VIETNAM_AG_REGIONS
from backend.simulator.sensor_simulator import simulate_zone, SensorReading
from backend.simulator.open_meteo_client import generate_synthetic_weather
from backend.simulator.water_balance import (
    update_soil_moisture_step,
    get_soil_params,
    get_crop_kc,
)
from backend.simulator.fault_injector import (
    FaultScenario,
    FaultInjectorRegistry,
    default_fault_injector,
)
from backend.simulator.benchmark_builder import build_benchmark, BenchmarkQuestion

# Tool modules
from backend.iam.iam import build_farm_context
from backend.tools.nextfarm_tools import (
    get_latest_sensor,
    get_device_status,
    get_irrigation_schedule,
    get_irrigation_history,
    _compute_quality_flag,
)


# ─── 1. Farm Generator Tests ────────────────────────────────────────────────
class TestFarmGenerator:
    def test_farm_generation_count_and_reproducibility(self):
        ds1 = generate_farms(n_farms=10, seed=42)
        ds2 = generate_farms(n_farms=10, seed=42)
        assert ds1.total_farms == 10
        assert ds2.total_farms == 10
        assert ds1.total_zones == ds2.total_zones
        assert ds1.farms[0].farm_id == ds2.farms[0].farm_id

    def test_farm_vietnam_coordinates(self):
        ds = generate_farms(n_farms=15, seed=123)
        for farm in ds.farms:
            # Vĩ độ Việt Nam 8.5°N - 23.5°N, Kinh độ 102°E - 110°E
            assert 8.0 <= farm.latitude <= 24.0, f"Lat out of VN: {farm.latitude}"
            assert 102.0 <= farm.longitude <= 110.0, f"Lon out of VN: {farm.longitude}"
            assert len(farm.zones) >= 3

    def test_farm_roles_cross_access(self):
        ds = generate_farms(n_farms=5, seed=99)
        # Ít nhất mỗi farm có 1 owner
        for f in ds.farms:
            roles = [u.role for u in f.users]
            assert "owner" in roles


# ─── 2. Water Balance & Climate Tests ───────────────────────────────────────
class TestWaterBalanceModel:
    def test_soil_params_lookup(self):
        p_phusa = get_soil_params("phù sa ven sông")
        assert p_phusa["fc"] == 38.0
        p_cat = get_soil_params("cát pha")
        assert p_cat["fc"] == 18.0

    def test_crop_kc_stages(self):
        kc_ini, depth = get_crop_kc("lúa", "mạ cây con")
        kc_mid, _ = get_crop_kc("lúa", "đẻ nhánh làm đòng")
        assert kc_mid > kc_ini

    def test_rain_increases_soil_moisture(self):
        m_start = 30.0
        m_after_rain = update_soil_moisture_step(
            current_moisture=m_start,
            et0_mm=0.0,
            rain_mm=25.0,
            irrigation_mm=0.0,
            crop="lúa",
            soil_type="phù sa",
        )
        assert m_after_rain > m_start

    def test_et_decreases_soil_moisture(self):
        m_start = 35.0
        m_after_et = update_soil_moisture_step(
            current_moisture=m_start,
            et0_mm=5.0,
            rain_mm=0.0,
            irrigation_mm=0.0,
            crop="cà phê",
            soil_type="đất đỏ bazan",
        )
        assert m_after_et < m_start

    def test_synthetic_weather_structure(self):
        weather = generate_synthetic_weather(10.5, 106.0, total_days=3)
        hourly = weather["hourly"]
        assert len(hourly["time"]) == 3 * 24
        assert len(hourly["temperature_2m"]) == 3 * 24
        assert len(hourly["relative_humidity_2m"]) == 3 * 24


# ─── 3. Fault Injector Tests ────────────────────────────────────────────────
class TestFaultInjector:
    def test_offline_fault_returns_missing(self):
        reg = FaultInjectorRegistry()
        sc = FaultScenario(
            scenario_id="TEST_OFFLINE",
            farm_id="farm_test",
            zone_id="zone_01",
            target_type="sensor",
            target_name="soil_moisture",
            fault_type="offline",
            start_time="2026-09-01T00:00:00",
            end_time="2026-09-01T12:00:00",
        )
        reg.add_scenario(sc)
        val, flag, fault = reg.apply_sensor_fault(
            reading_val=45.0,
            farm_id="farm_test",
            zone_id="zone_01",
            sensor_type="soil_moisture",
            dt=datetime.fromisoformat("2026-09-01T06:00:00"),
        )
        assert flag == "missing"
        assert val is None
        assert fault == "offline"

    def test_spike_fault_returns_fault_flag(self):
        reg = FaultInjectorRegistry()
        sc = FaultScenario(
            scenario_id="TEST_SPIKE",
            farm_id="farm_test",
            zone_id="zone_01",
            target_type="sensor",
            target_name="temperature",
            fault_type="spike",
            start_time="2026-09-01T00:00:00",
            end_time="2026-09-01T12:00:00",
            params={"spike_value": 75.0},
        )
        reg.add_scenario(sc)
        val, flag, fault = reg.apply_sensor_fault(
            reading_val=28.0,
            farm_id="farm_test",
            zone_id="zone_01",
            sensor_type="temperature",
            dt=datetime.fromisoformat("2026-09-01T06:00:00"),
        )
        assert flag == "fault"
        assert val == 75.0
        assert fault == "spike"


# ─── 4. NextFarm Tools & Freshness Tests ─────────────────────────────────────
class TestNextFarmTools:
    def test_quality_flag_fresh(self):
        now = datetime.now(timezone.utc)
        res = _compute_quality_flag(now - timedelta(minutes=5))
        assert res["quality_flag"] == "fresh"

    def test_quality_flag_stale(self):
        now = datetime.now(timezone.utc)
        res = _compute_quality_flag(now - timedelta(minutes=45))
        assert res["quality_flag"] == "stale"
        assert "⚠️" in (res["freshness_warning"] or "")

    def test_quality_flag_missing_when_none(self):
        res = _compute_quality_flag(None)
        assert res["quality_flag"] == "missing"

    def test_tool_cross_farm_denied(self):
        # User farmer_a chỉ có quyền farm_001, không được gọi farm_002
        ctx = build_farm_context(
            username="farmer_a",
            user_id="1",
            user_role="user",
        )
        res = get_latest_sensor(
            farm_context=ctx,
            farm_id="farm_002",
            zone_id="zone_A",
            sensor_type="soil_moisture",
        )
        assert res.get("found") is False
        assert res.get("error_type") == "authorization_denied"

    def test_tool_authorized_call_returns_data(self):
        ctx = build_farm_context(
            username="farmer_a",
            user_id="1",
            user_role="user",
        )
        res = get_latest_sensor(
            farm_context=ctx,
            farm_id="farm_001",
            zone_id="zone_A",
            sensor_type="soil_moisture",
        )
        assert res.get("found") is True
        assert "value" in res
        assert "quality_flag" in res


# ─── 5. Benchmark Dataset Tests ──────────────────────────────────────────────
class TestBenchmarkDataset:
    def test_benchmark_has_all_required_categories_and_count(self):
        dataset = build_benchmark(seed=42)
        assert dataset.total >= 260
        required_categories = [
            "latest_sensor",
            "device_state",
            "irrigation_history",
            "irrigation_schedule",
            "missing_stale_sensor",
            "unauthorized_cross_farm",
            "agricultural_factual_qa",
            "no_answer_hallucination_guard",
            "vietnamese_typo_robustness",
            "multi_turn_context",
        ]
        for cat in required_categories:
            assert cat in dataset.by_category, f"Missing category: {cat}"
            assert dataset.by_cat(cat) if hasattr(dataset, "by_cat") else dataset.by_category[cat] >= 10
