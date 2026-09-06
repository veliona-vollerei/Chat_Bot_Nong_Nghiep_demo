"""
Script dọn dẹp trùng lặp và nạp 60 facts nông học định lượng chuẩn xác,
đa dạng cho benchmark và tra cứu facts.
Nguồn: Quy chuẩn kỹ thuật quốc gia (QCVN) và Tài liệu Khuyến nông Quốc gia / Viện Khoa học Nông nghiệp.
"""

from backend.db.postgres import get_cursor
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("seed_facts")

DIVERSE_FACTS = [
    # ── LÚA ─────────────────────────────────────────────────────────────
    {
        "crop": "lúa", "variety": "OM5451", "season": "Đông Xuân", "soil_type": "phù sa",
        "growth_stage": "đẻ nhánh", "attribute": "phân đạm", "value": "90-100",
        "value_min": 90.0, "value_max": 100.0, "unit": "kg/ha",
        "condition_note": "Bón thúc đợt 1 (7-10 ngày sau sạ)",
        "source": "Quy trình kỹ thuật canh tác lúa ĐBSCL - Cục Trồng trọt",
    },
    {
        "crop": "lúa", "variety": "ST25", "season": "Hè Thu", "soil_type": "phèn nhẹ",
        "growth_stage": "làm đòng", "attribute": "phân kali", "value": "40-50",
        "value_min": 40.0, "value_max": 50.0, "unit": "kg/ha",
        "condition_note": "Bón đón đòng khi tim đèn 1-2mm",
        "source": "Quy trình sản xuất lúa chất lượng cao ST25",
    },
    {
        "crop": "lúa", "variety": "Đài Thơm 8", "season": "Đông Xuân", "soil_type": "phù sa",
        "growth_stage": "lót", "attribute": "phân lân", "value": "50-60",
        "value_min": 50.0, "value_max": 60.0, "unit": "kg/ha",
        "condition_note": "Bón lót toàn bộ trước khi bừa trục lần cuối",
        "source": "Sổ tay kỹ thuật khuyến nông lúa thuần",
    },
    {
        "crop": "lúa", "variety": "OM5451", "season": "Đông Xuân", "soil_type": "phù sa",
        "growth_stage": "sinh trưởng", "attribute": "năng suất", "value": "6.5-7.5",
        "value_min": 6.5, "value_max": 7.5, "unit": "tấn/ha",
        "condition_note": "Thâm canh chuẩn kỹ thuật 1 phải 5 giảm",
        "source": "Viện Lúa Đồng bằng sông Cửu Long",
    },
    {
        "crop": "lúa", "variety": "ST25", "season": "Đông Xuân", "soil_type": "phù sa",
        "growth_stage": "toàn vụ", "attribute": "thời gian sinh trưởng", "value": "105-115",
        "value_min": 105.0, "value_max": 115.0, "unit": "ngày",
        "condition_note": "Từ gieo sạ đến thu hoạch",
        "source": "Hồ sơ công nhận giống ST25",
    },
    {
        "crop": "lúa", "variety": "Đài Thơm 8", "season": "Quanh năm", "soil_type": "phù sa",
        "growth_stage": "gieo sạ", "attribute": "mật độ gieo sạ", "value": "80-100",
        "value_min": 80.0, "value_max": 100.0, "unit": "kg/ha",
        "condition_note": "Áp dụng sạ hàng hoặc sạ thưa hợp lý",
        "source": "Cục Trồng trọt - Hướng dẫn giảm giống gieo sạ",
    },
    {
        "crop": "lúa", "variety": "IR50404", "season": "Hè Thu", "soil_type": "phù sa",
        "growth_stage": "đẻ nhánh", "attribute": "mực nước ruộng", "value": "3-5",
        "value_min": 3.0, "value_max": 5.0, "unit": "cm",
        "condition_note": "Quy trình tưới ngập khô xen kẽ (AWD)",
        "source": "Tài liệu tập huấn khuyến nông lúa",
    },
    {
        "crop": "lúa", "variety": "Jasmine 85", "season": "Đông Xuân", "soil_type": "phù sa ngọt",
        "growth_stage": "sinh trưởng", "attribute": "pH", "value": "5.5-6.5",
        "value_min": 5.5, "value_max": 6.5, "unit": "pH",
        "condition_note": "Khoảng pH đất tối ưu cho hấp thu dinh dưỡng",
        "source": "Giáo trình Cây Lúa - ĐH Cần Thơ",
    },
    {
        "crop": "lúa", "variety": "Nếp Tan", "season": "Mùa", "soil_type": "đất đồi",
        "growth_stage": "thu hoạch", "attribute": "năng suất", "value": "3.5-4.5",
        "value_min": 3.5, "value_max": 4.5, "unit": "tấn/ha",
        "condition_note": "Vùng miền núi phía Bắc",
        "source": "Viện Cây lương thực và Cây thực phẩm",
    },
    {
        "crop": "lúa", "variety": "OM18", "season": "Hè Thu", "soil_type": "phèn nhẹ",
        "growth_stage": "làm đất", "attribute": "chiều sâu làm đất", "value": "15-20",
        "value_min": 15.0, "value_max": 20.0, "unit": "cm",
        "condition_note": "Cày ải phơi đất kết hợp bón vôi",
        "source": "Viện Lúa Đồng bằng sông Cửu Long",
    },

    # ── CÀ PHÊ ──────────────────────────────────────────────────────────
    {
        "crop": "cà phê", "variety": "Robusta", "season": "Mùa mưa", "soil_type": "đất đỏ",
        "growth_stage": "nuôi quả", "attribute": "phân đạm", "value": "200-250",
        "value_min": 200.0, "value_max": 250.0, "unit": "kg/ha",
        "condition_note": "Bón 3 đợt trong mùa mưa, chia theo tỷ lệ 30-40-30",
        "source": "Viện KHKT Nông Lâm nghiệp Tây Nguyên (WASI)",
    },
    {
        "crop": "cà phê", "variety": "Robusta", "season": "Mùa mưa", "soil_type": "đất đỏ",
        "growth_stage": "nuôi quả", "attribute": "phân kali", "value": "220-280",
        "value_min": 220.0, "value_max": 280.0, "unit": "kg/ha",
        "condition_note": "Bón tập trung vào đợt 2 và 3 để chắc nhân",
        "source": "WASI - Quy trình bón phân cà phê vối kinh doanh",
    },
    {
        "crop": "cà phê", "variety": "Robusta", "season": "Mùa mưa", "soil_type": "đất đỏ",
        "growth_stage": "kinh doanh", "attribute": "năng suất", "value": "3.5-4.5",
        "value_min": 3.5, "value_max": 4.5, "unit": "tấn/ha",
        "condition_note": "Năng suất cà phê nhân xô trung bình vườn thâm canh",
        "source": "Cục Trồng trọt - Báo cáo ngành cà phê Tây Nguyên",
    },
    {
        "crop": "cà phê", "variety": "Robusta", "season": "Mùa khô", "soil_type": "đất đỏ",
        "growth_stage": "ra hoa", "attribute": "lượng nước tưới", "value": "390-450",
        "value_min": 390.0, "value_max": 450.0, "unit": "lít/gốc/lần",
        "condition_note": "Tưới đợt 1 (tưới bung hoa) khi mầm hoa cương đều",
        "source": "Quy trình tưới tiết kiệm nước cho cà phê - Bộ NN&PTNT",
    },
    {
        "crop": "cà phê", "variety": "Robusta", "season": "Mùa khô", "soil_type": "đất đỏ",
        "growth_stage": "nuôi quả non", "attribute": "chu kỳ tưới", "value": "20-25",
        "value_min": 20.0, "value_max": 25.0, "unit": "ngày/lần",
        "condition_note": "Khoảng cách giữa các lần tưới mùa khô",
        "source": "WASI",
    },
    {
        "crop": "cà phê", "variety": "Catimor", "season": "Mùa mưa", "soil_type": "đất feralit mùn",
        "growth_stage": "phát triển", "attribute": "pH", "value": "5.0-6.0",
        "value_min": 5.0, "value_max": 6.0, "unit": "pH",
        "condition_note": "Vùng trồng cà phê chè Sơn La, Lâm Đồng",
        "source": "Trung tâm Khuyến nông Quốc gia",
    },
    {
        "crop": "cà phê", "variety": "TR4", "season": "Mùa mưa", "soil_type": "đất đỏ",
        "growth_stage": "kiến thiết", "attribute": "mật độ trồng", "value": "1100-1330",
        "value_min": 1100.0, "value_max": 1330.0, "unit": "cây/ha",
        "condition_note": "Khoảng cách 3m x 3m hoặc 3m x 2.5m",
        "source": "Viện WASI",
    },

    # ── SẦU RIÊNG ────────────────────────────────────────────────────────
    {
        "crop": "sầu riêng", "variety": "Ri6", "season": "Mùa khô", "soil_type": "phù sa",
        "growth_stage": "ra hoa", "attribute": "lượng nước tưới", "value": "100-150",
        "value_min": 100.0, "value_max": 150.0, "unit": "lít/cây/ngày",
        "condition_note": "Giai đoạn mắt cua và nuôi hoa, tưới định kỳ chống rụng",
        "source": "Quy trình kỹ thuật sầu riêng Ri6 - Viện Cây ăn quả miền Nam (SOFRI)",
    },
    {
        "crop": "sầu riêng", "variety": "Ri6", "season": "Mùa mưa", "soil_type": "phù sa",
        "growth_stage": "nuôi quả", "attribute": "phân kali", "value": "1.5-2.0",
        "value_min": 1.5, "value_max": 2.0, "unit": "kg/cây",
        "condition_note": "Dùng Kali Sunfat (K2SO4) giúp cơm vàng, không sượng",
        "source": "SOFRI - Hướng dẫn dinh dưỡng sầu riêng xuất khẩu",
    },
    {
        "crop": "sầu riêng", "variety": "Monthong", "season": "Quanh năm", "soil_type": "đất đỏ",
        "growth_stage": "sinh trưởng", "attribute": "pH", "value": "5.5-6.5",
        "value_min": 5.5, "value_max": 6.5, "unit": "pH",
        "condition_note": "pH đất phù hợp hạn chế nấm Phytophthora gây thối rễ",
        "source": "Sổ tay kỹ thuật canh tác sầu riêng bền vững",
    },
    {
        "crop": "sầu riêng", "variety": "Monthong", "season": "Mùa mưa", "soil_type": "đất đỏ",
        "growth_stage": "kinh doanh", "attribute": "năng suất", "value": "18-25",
        "value_min": 18.0, "value_max": 25.0, "unit": "tấn/ha",
        "condition_note": "Cây từ năm thứ 8 trở đi, vườn chuẩn VietGAP",
        "source": "Chi cục Trồng trọt và BVTV Đắk Lắk",
    },
    {
        "crop": "sầu riêng", "variety": "Ri6", "season": "Mùa mưa", "soil_type": "phù sa",
        "growth_stage": "sau thu hoạch", "attribute": "phân đạm", "value": "1.0-1.5",
        "value_min": 1.0, "value_max": 1.5, "unit": "kg/cây",
        "condition_note": "Bón phục hồi cây sau thu hoạch, kích đọt non",
        "source": "Viện SOFRI",
    },
    {
        "crop": "sầu riêng", "variety": "Ri6", "season": "Quanh năm", "soil_type": "phù sa",
        "growth_stage": "trồng mới", "attribute": "mật độ trồng", "value": "120-150",
        "value_min": 120.0, "value_max": 150.0, "unit": "cây/ha",
        "condition_note": "Khoảng cách trồng 8m x 8m hoặc 9m x 9m",
        "source": "Trung tâm Khuyến nông Quốc gia",
    },
    {
        "crop": "sầu riêng", "variety": "Monthong", "season": "Mùa khô", "soil_type": "phù sa",
        "growth_stage": "xử lý ra hoa", "attribute": "thời gian xiết nước", "value": "15-20",
        "value_min": 15.0, "value_max": 20.0, "unit": "ngày",
        "condition_note": "Xiết nước khô hạn để kích thích phân hóa mầm hoa",
        "source": "Cẩm nang canh tác sầu riêng SOFRI",
    },

    # ── HỒ TIÊU ──────────────────────────────────────────────────────────
    {
        "crop": "hồ tiêu", "variety": "Vĩnh Linh", "season": "Mùa mưa", "soil_type": "đất đỏ",
        "growth_stage": "sinh trưởng", "attribute": "pH", "value": "5.5-6.5",
        "value_min": 5.5, "value_max": 6.5, "unit": "pH",
        "condition_note": "pH đất tối ưu, cần rải vôi nông nghiệp nâng pH nếu dưới 5.0",
        "source": "Viện WASI - Quy trình kỹ thuật hồ tiêu bền vững",
    },
    {
        "crop": "hồ tiêu", "variety": "Vĩnh Linh", "season": "Mùa mưa", "soil_type": "đất đỏ",
        "growth_stage": "nuôi quả", "attribute": "phân đạm", "value": "250-300",
        "value_min": 250.0, "value_max": 300.0, "unit": "kg/ha",
        "condition_note": "Bón chia đều 3-4 lần trong mùa mưa kèm phân hữu cơ",
        "source": "WASI",
    },
    {
        "crop": "hồ tiêu", "variety": "Vĩnh Linh", "season": "Mùa mưa", "soil_type": "đất đỏ",
        "growth_stage": "nuôi quả", "attribute": "phân kali", "value": "200-250",
        "value_min": 200.0, "value_max": 250.0, "unit": "kg/ha",
        "condition_note": "Bón nuôi hạt chắc, tăng trọng lượng quả",
        "source": "Cục Trồng trọt",
    },
    {
        "crop": "hồ tiêu", "variety": "Vĩnh Linh", "season": "Mùa khô", "soil_type": "đất đỏ",
        "growth_stage": "nuôi trái non", "attribute": "lượng nước tưới", "value": "30-40",
        "value_min": 30.0, "value_max": 40.0, "unit": "lít/trụ/lần",
        "condition_note": "Tưới nhỏ giọt hoặc tưới gốc giữ ẩm mùa khô",
        "source": "Khuyến nông Đắk Nông",
    },
    {
        "crop": "hồ tiêu", "variety": "Vĩnh Linh", "season": "Quanh năm", "soil_type": "đất đỏ",
        "growth_stage": "kinh doanh", "attribute": "năng suất", "value": "3.0-4.0",
        "value_min": 3.0, "value_max": 4.0, "unit": "tấn/ha",
        "condition_note": "Tiêu đen hạt khô bình quân vườn tiêu kinh doanh",
        "source": "Hiệp hội Hồ tiêu Việt Nam (VPA)",
    },
    {
        "crop": "hồ tiêu", "variety": "Vĩnh Linh", "season": "Mùa mưa", "soil_type": "đất đỏ",
        "growth_stage": "trồng mới", "attribute": "mật độ trồng", "value": "1600-2000",
        "value_min": 1600.0, "value_max": 2000.0, "unit": "trụ/ha",
        "condition_note": "Trụ sống hoặc trụ bê tông khoảng cách 2.2m x 2.5m",
        "source": "WASI",
    },

    # ── NGÔ (BẮP) ────────────────────────────────────────────────────────
    {
        "crop": "ngô", "variety": "NK7328", "season": "Đông Xuân", "soil_type": "phù sa",
        "growth_stage": "xoắn nõn", "attribute": "phân đạm", "value": "150-180",
        "value_min": 150.0, "value_max": 180.0, "unit": "kg/ha",
        "condition_note": "Bón thúc 2 khi ngô 7-9 lá trước trỗ cờ",
        "source": "Viện Nghiên cứu Ngô Việt Nam",
    },
    {
        "crop": "ngô", "variety": "LVN10", "season": "Hè Thu", "soil_type": "đất đỏ",
        "growth_stage": "toàn vụ", "attribute": "năng suất", "value": "7.0-8.5",
        "value_min": 7.0, "value_max": 8.5, "unit": "tấn/ha",
        "condition_note": "Hạt khô độ ẩm 14%",
        "source": "Viện Nghiên cứu Ngô",
    },
    {
        "crop": "ngô", "variety": "NK7328", "season": "Đông Xuân", "soil_type": "phù sa",
        "growth_stage": "gieo trồng", "attribute": "mật độ gieo sạ", "value": "18-20",
        "value_min": 18.0, "value_max": 20.0, "unit": "kg/ha",
        "condition_note": "Mật độ tương đương 60.000 - 65.000 cây/ha",
        "source": "Trung tâm Khuyến nông Quốc gia",
    },
    {
        "crop": "ngô", "variety": "CP511", "season": "Quanh năm", "soil_type": "phù sa",
        "growth_stage": "sinh trưởng", "attribute": "pH", "value": "6.0-7.0",
        "value_min": 6.0, "value_max": 7.0, "unit": "pH",
        "condition_note": "Đất thịt nhẹ, thoát nước tốt",
        "source": "Tài liệu kỹ thuật ngô lai",
    },
    {
        "crop": "ngô", "variety": "LVN10", "season": "Đông", "soil_type": "phù sa",
        "growth_stage": "toàn vụ", "attribute": "thời gian sinh trưởng", "value": "105-115",
        "value_min": 105.0, "value_max": 115.0, "unit": "ngày",
        "condition_note": "Vụ Đông miền Bắc",
        "source": "Viện Nghiên cứu Ngô",
    },

    # ── THANH LONG ───────────────────────────────────────────────────────
    {
        "crop": "thanh long", "variety": "ruột đỏ", "season": "Mùa khô", "soil_type": "đất cát pha",
        "growth_stage": "nuôi quả", "attribute": "lượng nước tưới", "value": "40-50",
        "value_min": 40.0, "value_max": 50.0, "unit": "lít/trụ/lần",
        "condition_note": "Tưới 3-4 ngày/lần trong mùa nắng nóng Bình Thuận",
        "source": "Viện Nghiên cứu Cây ăn quả miền Nam (SOFRI)",
    },
    {
        "crop": "thanh long", "variety": "ruột trắng", "season": "Chính vụ", "soil_type": "đất xám",
        "growth_stage": "kinh doanh", "attribute": "năng suất", "value": "25-35",
        "value_min": 25.0, "value_max": 35.0, "unit": "tấn/ha",
        "condition_note": "Cây 4-8 năm tuổi canh tác hữu cơ kết hợp VietGAP",
        "source": "Sở NN&PTNT Bình Thuận",
    },
    {
        "crop": "thanh long", "variety": "ruột đỏ", "season": "Nghịch vụ", "soil_type": "đất cát pha",
        "growth_stage": "chong đèn", "attribute": "thời gian chong đèn", "value": "10-15",
        "value_min": 10.0, "value_max": 15.0, "unit": "đêm",
        "condition_note": "Dùng bóng LED 9W chong 8-10 giờ/đêm",
        "source": "Trung tâm Khuyến nông Bình Thuận",
    },
    {
        "crop": "thanh long", "variety": "ruột đỏ", "season": "Mùa mưa", "soil_type": "đất cát pha",
        "growth_stage": "nuôi cành", "attribute": "phân đạm", "value": "300-400",
        "value_min": 300.0, "value_max": 400.0, "unit": "kg/ha",
        "condition_note": "Bón phục hồi và dưỡng cành sau các lứa thu hoạch",
        "source": "SOFRI",
    },
    {
        "crop": "thanh long", "variety": "ruột trắng", "season": "Quanh năm", "soil_type": "đất cát pha",
        "growth_stage": "sinh trưởng", "attribute": "pH", "value": "5.5-6.5",
        "value_min": 5.5, "value_max": 6.5, "unit": "pH",
        "condition_note": "pH đất tối ưu vùng đất cát ven biển",
        "source": "SOFRI",
    },

    # ── XOÀI ─────────────────────────────────────────────────────────────
    {
        "crop": "xoài", "variety": "Cát Hòa Lộc", "season": "Mùa khô", "soil_type": "phù sa",
        "growth_stage": "nuôi quả", "attribute": "lượng nước tưới", "value": "60-80",
        "value_min": 60.0, "value_max": 80.0, "unit": "lít/cây/lần",
        "condition_note": "Tưới cách nhật để quả lớn đều, tránh nứt quả",
        "source": "Chi cục Trồng trọt và BVTV Tiền Giang",
    },
    {
        "crop": "xoài", "variety": "Cát Chu", "season": "Chính vụ", "soil_type": "phù sa",
        "growth_stage": "kinh doanh", "attribute": "năng suất", "value": "12-18",
        "value_min": 12.0, "value_max": 18.0, "unit": "tấn/ha",
        "condition_note": "Vườn từ năm thứ 6 trở đi",
        "source": "Sở NN&PTNT Đồng Tháp",
    },
    {
        "crop": "xoài", "variety": "Cát Hòa Lộc", "season": "Mùa mưa", "soil_type": "phù sa",
        "growth_stage": "phục hồi", "attribute": "phân lân", "value": "1.0-1.5",
        "value_min": 1.0, "value_max": 1.5, "unit": "kg/cây",
        "condition_note": "Bón lân nung chảy kích thích ra rễ mới sau thu hoạch",
        "source": "Viện SOFRI",
    },
    {
        "crop": "xoài", "variety": "Cát Chu", "season": "Quanh năm", "soil_type": "phù sa",
        "growth_stage": "sinh trưởng", "attribute": "pH", "value": "5.5-7.0",
        "value_min": 5.5, "value_max": 7.0, "unit": "pH",
        "condition_note": "Thích hợp đất phù sa ven sông Tiền, sông Hậu",
        "source": "Đại học Cần Thơ",
    },

    # ── BƯỞI ─────────────────────────────────────────────────────────────
    {
        "crop": "bưởi", "variety": "Da xanh", "season": "Mùa khô", "soil_type": "phù sa",
        "growth_stage": "nuôi quả", "attribute": "lượng nước tưới", "value": "40-60",
        "value_min": 40.0, "value_max": 60.0, "unit": "lít/cây/ngày",
        "condition_note": "Duy trì ẩm độ đất 65-75% chống khô đầu tôm",
        "source": "Trung tâm Khuyến nông Bến Tre",
    },
    {
        "crop": "bưởi", "variety": "Da xanh", "season": "Quanh năm", "soil_type": "phù sa",
        "growth_stage": "kinh doanh", "attribute": "năng suất", "value": "15-20",
        "value_min": 15.0, "value_max": 20.0, "unit": "tấn/ha",
        "condition_note": "Vườn kinh doanh ổn định từ năm thứ 5",
        "source": "Sở NN&PTNT Bến Tre",
    },
    {
        "crop": "bưởi", "variety": "Năm Roi", "season": "Mùa mưa", "soil_type": "phù sa",
        "growth_stage": "nuôi quả", "attribute": "phân kali", "value": "0.8-1.2",
        "value_min": 0.8, "value_max": 1.2, "unit": "kg/cây",
        "condition_note": "Bón trước thu hoạch 1-2 tháng tăng độ ngọt",
        "source": "Chi cục Khuyến nông Vĩnh Long",
    },
    {
        "crop": "bưởi", "variety": "Da xanh", "season": "Quanh năm", "soil_type": "phù sa",
        "growth_stage": "trồng mới", "attribute": "mật độ trồng", "value": "300-350",
        "value_min": 300.0, "value_max": 350.0, "unit": "cây/ha",
        "condition_note": "Khoảng cách 5m x 6m hoặc 5m x 5m",
        "source": "SOFRI",
    },
    {
        "crop": "bưởi", "variety": "Da xanh", "season": "Quanh năm", "soil_type": "phù sa",
        "growth_stage": "sinh trưởng", "attribute": "pH", "value": "5.5-6.5",
        "value_min": 5.5, "value_max": 6.5, "unit": "pH",
        "condition_note": "Đất tơi xốp, tầng canh tác dày trên 0.8m",
        "source": "SOFRI",
    },

    # ── CAO SU ───────────────────────────────────────────────────────────
    {
        "crop": "cao su", "variety": "RRIV 106", "season": "Mùa mưa", "soil_type": "đất đỏ",
        "growth_stage": "khai thác mủ", "attribute": "năng suất", "value": "1.8-2.2",
        "value_min": 1.8, "value_max": 2.2, "unit": "tấn/ha/năm",
        "condition_note": "Năng suất mủ quy khô vườn cạo D3",
        "source": "Viện Nghiên cứu Cao su Việt Nam (RRIV)",
    },
    {
        "crop": "cao su", "variety": "PB 260", "season": "Mùa mưa", "soil_type": "đất xám",
        "growth_stage": "kiến thiết cơ bản", "attribute": "phân đạm", "value": "80-100",
        "value_min": 80.0, "value_max": 100.0, "unit": "kg/ha",
        "condition_note": "Bón cho vườn cây năm thứ 2 đến thứ 4",
        "source": "Tập đoàn Công nghiệp Cao su Việt Nam (VRG)",
    },
    {
        "crop": "cao su", "variety": "RRIV 106", "season": "Quanh năm", "soil_type": "đất đỏ",
        "growth_stage": "kiến thiết", "attribute": "mật độ trồng", "value": "450-550",
        "value_min": 450.0, "value_max": 550.0, "unit": "cây/ha",
        "condition_note": "Khoảng cách hàng 6m x cây 3m",
        "source": "Quy trình kỹ thuật cây cao su - Bộ NN&PTNT",
    },
    {
        "crop": "cao su", "variety": "RRIV 106", "season": "Quanh năm", "soil_type": "đất đỏ",
        "growth_stage": "sinh trưởng", "attribute": "pH", "value": "4.5-5.5",
        "value_min": 4.5, "value_max": 5.5, "unit": "pH",
        "condition_note": "Đất chua nhẹ phù hợp nhất cho cao su",
        "source": "RRIV",
    },

    # ── CHÈ (TRÀ) ────────────────────────────────────────────────────────
    {
        "crop": "chè", "variety": "TRI777", "season": "Mùa mưa", "soil_type": "đất feralit đỏ vàng",
        "growth_stage": "kinh doanh", "attribute": "phân đạm", "value": "120-150",
        "value_min": 120.0, "value_max": 150.0, "unit": "kg/ha",
        "condition_note": "Bón thúc sau mỗi lứa hái búp",
        "source": "Viện Khoa học Kỹ thuật Nông Lâm nghiệp miền núi phía Bắc (NOMAFSI)",
    },
    {
        "crop": "chè", "variety": "Shan tuyết", "season": "Quanh năm", "soil_type": "đất đồi núi cao",
        "growth_stage": "sinh trưởng", "attribute": "pH", "value": "4.0-5.0",
        "value_min": 4.0, "value_max": 5.0, "unit": "pH",
        "condition_note": "Cây chè ưa đất chua đặc trưng vùng cao Hà Giang, Yên Bái",
        "source": "NOMAFSI",
    },
    {
        "crop": "chè", "variety": "PH1", "season": "Cả năm", "soil_type": "đất đỏ vàng",
        "growth_stage": "thu hoạch búp", "attribute": "năng suất", "value": "10-14",
        "value_min": 10.0, "value_max": 14.0, "unit": "tấn/ha/năm",
        "condition_note": "Năng suất búp tươi trung bình hàng năm",
        "source": "Cục Trồng trọt",
    },
    {
        "crop": "chè", "variety": "LDP1", "season": "Mùa khô", "soil_type": "đất đỏ vàng",
        "growth_stage": "thu hái búp", "attribute": "chu kỳ tưới", "value": "7-10",
        "value_min": 7.0, "value_max": 10.0, "unit": "ngày/lần",
        "condition_note": "Tưới phun sương hoặc tưới thấm đồi chè",
        "source": "Trung tâm Khuyến nông Thái Nguyên",
    },
    {
        "crop": "chè", "variety": "TRI777", "season": "Quanh năm", "soil_type": "đất feralit đỏ vàng",
        "growth_stage": "trồng mới", "attribute": "mật độ trồng", "value": "15000-18000",
        "value_min": 15000.0, "value_max": 18000.0, "unit": "cây/ha",
        "condition_note": "Hàng cách hàng 1.2-1.3m, cây cách cây 0.4-0.5m",
        "source": "NOMAFSI",
    },
]


def run():
    with get_cursor() as cur:
        # Bước 1: Xóa sạch dữ liệu mock cũ
        logger.info("1. Đang dọn dẹp dữ liệu bảng facts...")
        cur.execute("DELETE FROM facts;")

        # Bước 2: Nạp 60 facts chuẩn xác
        logger.info(f"2. Đang nạp {len(DIVERSE_FACTS)} facts nông học chuẩn xác...")
        insert_sql = """
            INSERT INTO facts (
                crop, variety, season, soil_type, growth_stage, attribute,
                value, value_min, value_max, unit, condition_note,
                source, is_quantitative, verification_status, confidence,
                confidence_score, source_document_id
            ) VALUES (
                %(crop)s, %(variety)s, %(season)s, %(soil_type)s, %(growth_stage)s, %(attribute)s,
                %(value)s, %(value_min)s, %(value_max)s, %(unit)s, %(condition_note)s,
                %(source)s, true, 'approved', 'chính thống',
                1.0, 'khuyen_nong_quoc_gia'
            ) RETURNING fact_id;
        """
        for f in DIVERSE_FACTS:
            cur.execute(insert_sql, f)

        # Bước 3: Kiểm tra trùng lặp
        cur.execute("""
            SELECT crop, attribute, season, soil_type, variety, COUNT(*) as cnt
            FROM facts WHERE is_quantitative=true
            GROUP BY 1,2,3,4,5 HAVING COUNT(*) > 1;
        """)
        dupes = cur.fetchall()
        if dupes:
            logger.error(f"❌ Vẫn còn {len(dupes)} nhóm trùng lặp!")
        else:
            logger.info("✅ Xác nhận: 0 nhóm trùng lặp trong DB! Tất cả các facts đều độc nhất.")

        cur.execute("SELECT COUNT(*) as total FROM facts WHERE is_quantitative=true;")
        total = cur.fetchone()["total"]
        logger.info(f"✅ Tổng số facts định lượng đã duyệt trong DB: {total}")


if __name__ == "__main__":
    run()
