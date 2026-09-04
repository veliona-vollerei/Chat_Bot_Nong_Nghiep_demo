"""
Water Balance Model — GĐ3 Farm Simulator.

Triển khai mô hình cân bằng nước đất theo FAO-56 (Penman-Monteith / Thornthwaite):
  S(t) = S(t-1) + P_eff(t) + I(t) - ETc(t) - D(t)

Trong đó:
- S(t): Độ ẩm đất (%)
- P_eff: Mưa hiệu quả (mm chuyển sang % độ ẩm theo tầng rễ)
- I(t): Tưới (mm)
- ETc = Kc * ET0: Bốc thoát hơi của cây trồng theo hệ số vụ Kc
- D(t): Thấm sâu / tiêu thoát nước khi vượt quá dung tích đồng ruộng (Field Capacity)
"""

import math
from dataclasses import dataclass
from typing import Optional

# ─── Soil Hydraulic Properties ──────────────────────────────────────────
# (Field Capacity FC %, Permanent Wilting Point WP %, Saturation SAT %, Root Depth m)
SOIL_PROPERTIES = {
    "phù sa":        {"fc": 38.0, "wp": 18.0, "sat": 48.0, "drainage_rate": 0.4},
    "đất đỏ":        {"fc": 34.0, "wp": 20.0, "sat": 46.0, "drainage_rate": 0.5},
    "đất đỏ bazan":  {"fc": 35.0, "wp": 20.0, "sat": 45.0, "drainage_rate": 0.5},
    "phèn":          {"fc": 42.0, "wp": 22.0, "sat": 52.0, "drainage_rate": 0.25},
    "cát pha":       {"fc": 18.0, "wp": 8.0,  "sat": 32.0, "drainage_rate": 0.75},
    "default":       {"fc": 32.0, "wp": 16.0, "sat": 44.0, "drainage_rate": 0.4},
}

# ─── Crop Coefficients (FAO-56 Kc by Growth Stage) ──────────────────────
# (Kc_ini, Kc_mid, Kc_end)
CROP_KC = {
    "lúa":         {"ini": 1.05, "mid": 1.20, "end": 0.90, "root_depth": 0.3},
    "cà phê":      {"ini": 0.90, "mid": 0.95, "end": 0.95, "root_depth": 1.0},
    "hồ tiêu":     {"ini": 0.80, "mid": 1.05, "end": 0.85, "root_depth": 0.8},
    "sầu riêng":   {"ini": 0.85, "mid": 1.10, "end": 0.90, "root_depth": 1.2},
    "thanh long":  {"ini": 0.50, "mid": 0.65, "end": 0.55, "root_depth": 0.5},
    "xoài":        {"ini": 0.80, "mid": 1.00, "end": 0.85, "root_depth": 1.2},
    "rau":         {"ini": 0.60, "mid": 1.05, "end": 0.85, "root_depth": 0.3},
    "default":     {"ini": 0.75, "mid": 1.00, "end": 0.80, "root_depth": 0.6},
}


def get_soil_params(soil_type: Optional[str]) -> dict:
    if not soil_type:
        return SOIL_PROPERTIES["default"]
    soil_lower = soil_type.lower()
    for key, val in SOIL_PROPERTIES.items():
        if key in soil_lower:
            return val
    return SOIL_PROPERTIES["default"]


def get_crop_kc(crop: Optional[str], growth_stage: Optional[str] = "giữa vụ") -> tuple[float, float]:
    """Trả về (Kc, root_depth_m)."""
    if not crop:
        params = CROP_KC["default"]
    else:
        crop_lower = crop.lower()
        matched = False
        for key, val in CROP_KC.items():
            if key in crop_lower:
                params = val
                matched = True
                break
        if not matched:
            params = CROP_KC["default"]

    stage = (growth_stage or "").lower()
    if any(k in stage for k in ["đầu vụ", "cây con", "mạ", "kiến thiết"]):
        kc = params["ini"]
    elif any(k in stage for k in ["cuối vụ", "chín", "thu hoạch"]):
        kc = params["end"]
    else:
        kc = params["mid"]

    return kc, params["root_depth"]


def update_soil_moisture_step(
    current_moisture: float,
    et0_mm: float,
    rain_mm: float,
    irrigation_mm: float,
    crop: str,
    soil_type: str,
    growth_stage: str = "giữa vụ",
    step_hours: float = 1.0,
) -> float:
    """
    Cập nhật độ ẩm đất cho 1 bước thời gian (mặc định 1 giờ hoặc phân đoạn giờ).
    
    Returns:
        Độ ẩm đất mới (% thể tích).
    """
    soil = get_soil_params(soil_type)
    kc, root_depth = get_crop_kc(crop, growth_stage)

    # Đổi mm nước sang % độ ẩm đất trên độ sâu rễ (root_depth m = root_depth * 1000 mm)
    # 1 mm nước = 100 / (root_depth * 1000) % độ ẩm thể tích
    mm_to_pct = 0.1 / root_depth

    # Bốc thoát hơi cây trồng ETc
    etc_mm = kc * et0_mm
    moisture_loss = etc_mm * mm_to_pct

    # Lượng nước cấp (mưa hiệu quả + tưới)
    eff_rain = rain_mm * 0.85 if rain_mm > 2.0 else 0.0
    moisture_gain = (eff_rain + irrigation_mm) * mm_to_pct

    # Cập nhật tạm thời
    new_moisture = current_moisture + moisture_gain - moisture_loss

    # Tiêu thoát khi vượt dung tích đồng ruộng (Field Capacity)
    if new_moisture > soil["fc"]:
        excess = new_moisture - soil["fc"]
        drainage = excess * min(1.0, soil["drainage_rate"] * step_hours)
        new_moisture -= drainage

    # Giới hạn vật lý giữa điểm héo và độ bão hòa
    lower_bound = max(5.0, soil["wp"] * 0.6)
    upper_bound = soil["sat"]
    return round(max(lower_bound, min(upper_bound, new_moisture)), 2)
