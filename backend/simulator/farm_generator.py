"""
Farm Generator — GĐ3 Mục Farm Simulator.

Sinh 30-50 farm giả lập với:
- Tọa độ thực tế các vùng nông nghiệp Việt Nam (ĐBSCL, Tây Nguyên, ĐBSH...)
- 3-6 zone/farm với loại đất, loại cây trồng, diện tích
- User/role: owner, manager, viewer — có quyền chéo/không chéo để test IAM
- Dữ liệu cố định (seed) để reproducible

GĐ3: Dữ liệu này sẽ được kết nối với sensor_simulator để sinh chuỗi sensor readings.

Chạy:
    python -m backend.simulator.farm_generator
    python -m backend.simulator.farm_generator --output data/farms.json
"""
import json
import random
import hashlib
import argparse
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional


# ─── Seed cố định để reproducible ─────────────────────────────────────────
SEED = 42

# ─── Vùng nông nghiệp thực tế Việt Nam ───────────────────────────────────
VIETNAM_AG_REGIONS = [
    # (tên vùng, lat_center, lon_center, lat_range, lon_range, cây trồng chủ)
    ("ĐBSCL - Long An",        10.535, 106.408, 0.5, 0.6, ["lúa", "mía", "thanh long"]),
    ("ĐBSCL - Tiền Giang",     10.350, 106.350, 0.4, 0.5, ["lúa", "sầu riêng", "khóm"]),
    ("ĐBSCL - Đồng Tháp",     10.565, 105.636, 0.5, 0.6, ["lúa", "xoài", "hoa sen"]),
    ("ĐBSCL - An Giang",       10.396, 105.438, 0.5, 0.6, ["lúa", "rau màu"]),
    ("ĐBSCL - Kiên Giang",     10.013, 105.081, 0.6, 0.7, ["lúa", "hồ tiêu"]),
    ("ĐBSCL - Cần Thơ",        10.035, 105.788, 0.3, 0.4, ["lúa", "cá tra"]),
    ("ĐBSCL - Hậu Giang",       9.784, 105.470, 0.4, 0.5, ["lúa", "mía"]),
    ("ĐBSCL - Sóc Trăng",       9.602, 105.974, 0.4, 0.5, ["lúa", "tôm"]),
    ("ĐBSCL - Bạc Liêu",        9.294, 105.727, 0.4, 0.5, ["lúa", "tôm"]),
    ("ĐBSCL - Cà Mau",          9.177, 105.150, 0.5, 0.6, ["lúa", "tôm"]),
    # Tây Nguyên
    ("Tây Nguyên - Đắk Lắk",   12.667, 108.038, 0.6, 0.7, ["cà phê", "hồ tiêu", "cao su"]),
    ("Tây Nguyên - Gia Lai",    13.983, 108.000, 0.6, 0.7, ["cà phê", "mía", "cao su"]),
    ("Tây Nguyên - Lâm Đồng",  11.750, 108.183, 0.4, 0.5, ["cà phê", "rau", "dâu tây"]),
    ("Tây Nguyên - Đắk Nông",  11.983, 107.690, 0.4, 0.5, ["cà phê", "hồ tiêu"]),
    # Đông Nam Bộ
    ("Đông Nam Bộ - Bình Phước", 11.752, 106.723, 0.5, 0.6, ["cao su", "điều", "cà phê"]),
    ("Đông Nam Bộ - Bình Dương", 11.165, 106.617, 0.3, 0.4, ["cao su", "rau"]),
    # ĐBSH
    ("ĐBSH - Thái Bình",        20.450, 106.336, 0.3, 0.4, ["lúa"]),
    ("ĐBSH - Nam Định",         20.420, 106.168, 0.3, 0.4, ["lúa", "rau"]),
    ("ĐBSH - Hưng Yên",         20.646, 106.051, 0.3, 0.4, ["lúa", "nhãn"]),
    ("ĐBSH - Hải Dương",        20.940, 106.314, 0.3, 0.4, ["lúa", "vải", "cà rốt"]),
]

SOIL_TYPES = ["phù sa", "phèn nhẹ", "phèn nặng", "xám bạc màu", "đất đỏ basalt",
              "cát pha", "thịt nhẹ", "sét pha cát"]

CROP_GROWTH_STAGES = {
    "lúa":     ["mạ", "đẻ_nhánh", "làm_đòng", "trỗ_bông", "chín"],
    "cà phê":  ["kiến_thiết", "cho_quả", "già_cỗi"],
    "hồ tiêu": ["trồng_mới", "cho_quả", "già"],
    "cao su":  ["khai_thác", "kiến_thiết"],
    "sầu riêng":["ra_hoa", "đậu_quả", "thu_hoạch"],
    "xoài":   ["ra_hoa", "đậu_quả", "thu_hoạch"],
    "default": ["sinh_trưởng", "thu_hoạch"],
}

SENSOR_TYPES = ["soil_moisture", "temperature", "humidity", "rainfall", "ph", "ec"]
DEVICE_TYPES = ["valve", "pump", "sensor_node", "weather_station"]


# ─── Data Classes ─────────────────────────────────────────────────────────

@dataclass
class Zone:
    zone_id: str
    name: str
    crop: str
    growth_stage: str
    soil_type: str
    area_ha: float       # diện tích (ha)
    latitude: float
    longitude: float
    sensors: list[str] = field(default_factory=list)   # sensor_type list
    devices: list[str] = field(default_factory=list)   # device_id list


@dataclass
class User:
    user_id: str
    username: str
    role: str   # "owner", "manager", "viewer"


@dataclass
class Farm:
    farm_id: str
    name: str
    region: str
    latitude: float
    longitude: float
    owner: User
    zones: list[Zone] = field(default_factory=list)
    users: list[User] = field(default_factory=list)  # kể cả owner


@dataclass
class FarmDataset:
    farms: list[Farm]
    total_farms: int
    total_zones: int
    total_users: int
    seed: int


# ─── Generator ────────────────────────────────────────────────────────────

def _stable_id(prefix: str, *parts) -> str:
    """Tạo ID ổn định dựa trên nội dung (không random)."""
    key = "_".join(str(p) for p in parts)
    h = hashlib.md5(key.encode()).hexdigest()[:8]
    return f"{prefix}_{h}"


def generate_farms(
    n_farms: int = 35,
    seed: int = SEED,
    min_zones: int = 3,
    max_zones: int = 6,
) -> FarmDataset:
    """
    Sinh dataset farm giả lập.

    Args:
        n_farms: Số lượng farm (30-50)
        seed: Random seed để reproducible
        min_zones, max_zones: Số zone/farm

    Returns:
        FarmDataset với tất cả farm, zone, user
    """
    rng = random.Random(seed)
    farms = []
    user_counter = 0
    total_zones = 0

    for farm_idx in range(n_farms):
        # Chọn vùng (lặp vòng để đảm bảo cover đủ vùng)
        region_info = VIETNAM_AG_REGIONS[farm_idx % len(VIETNAM_AG_REGIONS)]
        region_name, lat_c, lon_c, lat_r, lon_r, main_crops = region_info

        lat = lat_c + rng.uniform(-lat_r, lat_r)
        lon = lon_c + rng.uniform(-lon_r, lon_r)

        farm_id = f"farm_{farm_idx+1:03d}"
        farm_name = f"{region_name.split(' - ')[-1]} Farm {farm_idx+1}"

        # Owner
        user_counter += 1
        owner_id = f"user_{user_counter:04d}"
        owner = User(
            user_id=owner_id,
            username=f"owner_{farm_idx+1:03d}",
            role="owner",
        )

        # Thêm manager và viewer
        users = [owner]
        # Manager (50% farm có manager)
        if rng.random() > 0.5:
            user_counter += 1
            users.append(User(
                user_id=f"user_{user_counter:04d}",
                username=f"mgr_{farm_idx+1:03d}",
                role="manager",
            ))
        # 1-2 viewer
        n_viewers = rng.randint(0, 2)
        for v in range(n_viewers):
            user_counter += 1
            users.append(User(
                user_id=f"user_{user_counter:04d}",
                username=f"viewer_{farm_idx+1:03d}_{v+1}",
                role="viewer",
            ))

        # Zones
        n_zones = rng.randint(min_zones, max_zones)
        zones = []
        for zone_idx in range(n_zones):
            crop = rng.choice(main_crops)
            growth_stages = CROP_GROWTH_STAGES.get(crop, CROP_GROWTH_STAGES["default"])
            zone_lat = lat + rng.uniform(-0.02, 0.02)
            zone_lon = lon + rng.uniform(-0.02, 0.02)

            # Chọn sensor types cho zone
            n_sensors = rng.randint(2, len(SENSOR_TYPES))
            zone_sensors = rng.sample(SENSOR_TYPES, n_sensors)

            # Devices
            zone_devices = [
                f"{farm_id}_z{zone_idx+1}_valve_01",
                f"{farm_id}_z{zone_idx+1}_pump_01",
            ]
            if "soil_moisture" in zone_sensors or "ph" in zone_sensors:
                zone_devices.append(f"{farm_id}_z{zone_idx+1}_sensor_node_01")

            zone = Zone(
                zone_id=f"{farm_id}_z{zone_idx+1:02d}",
                name=f"Zone {zone_idx+1} ({crop})",
                crop=crop,
                growth_stage=rng.choice(growth_stages),
                soil_type=rng.choice(SOIL_TYPES),
                area_ha=round(rng.uniform(0.5, 5.0), 2),
                latitude=round(zone_lat, 6),
                longitude=round(zone_lon, 6),
                sensors=zone_sensors,
                devices=zone_devices,
            )
            zones.append(zone)
            total_zones += 1

        farm = Farm(
            farm_id=farm_id,
            name=farm_name,
            region=region_name,
            latitude=round(lat, 6),
            longitude=round(lon, 6),
            owner=owner,
            zones=zones,
            users=users,
        )
        farms.append(farm)

    return FarmDataset(
        farms=farms,
        total_farms=len(farms),
        total_zones=total_zones,
        total_users=user_counter,
        seed=seed,
    )


def save_dataset(dataset: FarmDataset, output_path: Path):
    """Lưu dataset ra JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(dataset)
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"✅ Saved {dataset.total_farms} farms, {dataset.total_zones} zones "
          f"({dataset.total_users} users) → {output_path}")


def load_dataset(path: Path) -> FarmDataset:
    """Load dataset từ JSON file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    farms = []
    for f in data["farms"]:
        owner_data = f["owner"]
        owner = User(**owner_data)
        zones = [Zone(**z) for z in f["zones"]]
        users = [User(**u) for u in f["users"]]
        farms.append(Farm(
            farm_id=f["farm_id"],
            name=f["name"],
            region=f["region"],
            latitude=f["latitude"],
            longitude=f["longitude"],
            owner=owner,
            zones=zones,
            users=users,
        ))
    return FarmDataset(
        farms=farms,
        total_farms=data["total_farms"],
        total_zones=data["total_zones"],
        total_users=data["total_users"],
        seed=data["seed"],
    )


# ─── Update mock IAM từ dataset ────────────────────────────────────────────

def build_iam_mock_from_dataset(dataset: FarmDataset) -> dict:
    """
    Xây dựng mapping user → allowed_farm_ids từ dataset.
    Dùng để update iam.py MOCK_USER_FARMS (cho test).
    """
    user_farms: dict[str, list[str]] = {}
    for farm in dataset.farms:
        for user in farm.users:
            if user.username not in user_farms:
                user_farms[user.username] = []
            user_farms[user.username].append(farm.farm_id)
    return user_farms


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

    parser = argparse.ArgumentParser(description="Generate Farm Simulator Dataset")
    parser.add_argument("--n_farms", type=int, default=35, help="Số lượng farm")
    parser.add_argument("--seed", type=int, default=SEED, help="Random seed")
    parser.add_argument("--output", default="data/farms.json", help="Output JSON path")
    parser.add_argument("--stats", action="store_true", help="In thống kê")
    args = parser.parse_args()

    dataset = generate_farms(n_farms=args.n_farms, seed=args.seed)
    output_path = Path(args.output)
    save_dataset(dataset, output_path)

    if args.stats:
        print(f"\n📊 Farm Dataset Stats:")
        print(f"   Farms   : {dataset.total_farms}")
        print(f"   Zones   : {dataset.total_zones}")
        print(f"   Users   : {dataset.total_users}")
        print(f"   Avg zones/farm: {dataset.total_zones/dataset.total_farms:.1f}")

        # Phân bố crop
        crops: dict[str, int] = {}
        for farm in dataset.farms:
            for zone in farm.zones:
                crops[zone.crop] = crops.get(zone.crop, 0) + 1
        print(f"\n   Phân bố cây trồng:")
        for crop, cnt in sorted(crops.items(), key=lambda x: -x[1]):
            print(f"     {crop:<20} {cnt:>3} zones")
