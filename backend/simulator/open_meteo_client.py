"""
Open-Meteo Client — GĐ3 Farm Simulator.

Gọi Open-Meteo API (miễn phí, không cần API key) để lấy thời tiết thực tế
cho tọa độ các nông trại tại Việt Nam:
- Nhiệt độ (temperature_2m)
- Độ ẩm tương đối (relative_humidity_2m)
- Lượng mưa (precipitation)
- Bốc thoát hơi tiềm năng (et0_fao_evapotranspiration)

Hỗ trợ:
- Local file cache để tái hiện dữ liệu (reproducible) và tránh gọi mạng liên tục
- Fallback mô hình khí hậu nội suy tự động nếu offline / lỗi mạng
"""

import json
import logging
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Optional
from datetime import datetime

logger = logging.getLogger("open_meteo_client")

CACHE_DIR = Path("data/cache/weather")


def fetch_weather_forecast(
    latitude: float,
    longitude: float,
    past_days: int = 7,
    forecast_days: int = 7,
    use_cache: bool = True,
) -> dict:
    """
    Lấy chuỗi dữ liệu thời tiết hourly từ Open-Meteo API.
    
    Args:
        latitude: Vĩ độ (e.g. 10.0452 cho Cần Thơ)
        longitude: Kinh độ (e.g. 105.7469)
        past_days: Số ngày quá khứ
        forecast_days: Số ngày dự báo
        use_cache: Đọc cache cục bộ nếu có
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_key = f"meteo_{latitude:.3f}_{longitude:.3f}_{past_days}_{forecast_days}.json"
    cache_file = CACHE_DIR / cache_key

    if use_cache and cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                logger.info(f"Loaded weather data from cache: {cache_file}")
                return data
        except Exception as e:
            logger.warning(f"Failed to read cache {cache_file}: {e}")

    # Build API URL
    base_url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": "temperature_2m,relative_humidity_2m,precipitation,et0_fao_evapotranspiration",
        "timezone": "Asia/Ho_Chi_Minh",
        "past_days": past_days,
        "forecast_days": forecast_days,
    }
    url = f"{base_url}?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NextFarmChatbot/2.2"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            content = resp.read().decode("utf-8")
            data = json.loads(content)
            
            # Lưu cache
            if use_cache:
                with open(cache_file, "w", encoding="utf-8") as f:
                    f.write(content)
                logger.info(f"Saved weather data to cache: {cache_file}")
            return data
    except Exception as exc:
        logger.warning(f"Open-Meteo API unavailable ({exc}), generating synthetic fallback.")
        return generate_synthetic_weather(latitude, longitude, past_days + forecast_days)


def generate_synthetic_weather(latitude: float, longitude: float, total_days: int = 14) -> dict:
    """Fallback sinh dữ liệu khí hậu tổng hợp nếu không có kết nối internet."""
    import math
    import random

    rng = random.Random(int(latitude * 1000 + longitude * 100))
    times = []
    temps = []
    humidities = []
    precips = []
    et0s = []

    start_time = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    for h in range(total_days * 24):
        dt = start_time.replace(hour=0) 
        # offset hours
        # calculate hour of day
        hour = h % 24
        t_base = 27.0 + 5.0 * math.sin(math.radians((hour - 6) * 15 - 90))
        t = round(t_base + rng.gauss(0, 0.5), 1)
        hum = round(max(40.0, min(98.0, 80.0 - (t - 27.0) * 2.5 + rng.gauss(0, 1.5))), 1)
        rain = round(rng.expovariate(0.2), 1) if (14 <= hour <= 16 and rng.random() < 0.25) else 0.0
        et0 = round(max(0.0, 0.25 * math.sin(math.radians((hour - 6) * 15)) * (t / 25.0)), 2) if 6 <= hour <= 18 else 0.0

        times.append(f"2026-09-0{1 + (h // 24):02d}T{hour:02d}:00")
        temps.append(t)
        humidities.append(hum)
        precips.append(rain)
        et0s.append(et0)

    return {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": {
            "time": times,
            "temperature_2m": temps,
            "relative_humidity_2m": humidities,
            "precipitation": precips,
            "et0_fao_evapotranspiration": et0s,
        },
        "source": "synthetic_fallback",
    }
