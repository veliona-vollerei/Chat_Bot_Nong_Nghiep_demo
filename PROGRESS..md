# 📋 TÀI LIỆU TOÀN DIỆN HỆ THỐNG & TIẾN ĐỘ TRIỂN KHAI
# HỆ SINH THÁI NEXTFARM CHATBOT AI v2.2

> **Tên hệ thống:** NextFarm Agriculture AI Chatbot Platform  
> **Phiên bản kiến trúc:** v2.2 (Kiến trúc Đa Tầng Chuyên Sâu: 6-Layer Architecture)  
> **Cập nhật lần cuối:** 2026-09-05 (Hoàn thành nghiệm thu toàn diện GĐ1 → GĐ5 theo lộ trình `Lo_trinh_thuc_hien_NextFarm_v2_2.docx`)  
> **Trạng thái kiểm định:** 🟢 **HỆ THỐNG HOÀN CHỈNH — ĐÃ NGHIỆM THU — 52/52 UNIT TESTS PASSED — 260/260 BENCHMARK QUESTIONS PASSED (0 IAM LEAK)**

---

## 📑 MỤC LỤC TỔNG QUAN

1. [Tổng Quan & Sứ Mệnh Hệ Thống](#-1-tổng-quan--sứ-mệnh-hệ-thống)
2. [Sơ Đồ Kiến Trúc Toàn Hệ Thống (6-Layer Architecture)](#-2-sơ-đồ-kiến-trúc-toàn-hệ-thống-6-layer-architecture)
3. [Chi Tiết 6 Tầng Xử Lý Tri Thức & IoT](#-3-chi-tiết-6-tầng-xử-lý-tri-thức--iot)
4. [Các Phân Hệ Kỹ Thuật Trọng Yếu](#-4-các-phân-hệ-kỹ-thuật-trọng-yếu)
   - 4.1. [Phân Hệ IAM & Kiểm Soát Phân Quyền Nông Trại](#41-phân-hệ-iam--kiểm-soát-phân-quyền-nông-trại)
   - 4.2. [Phân Hệ Router & Fallback Policy An Toàn](#42-phân-hệ-router--fallback-policy-an-toàn)
   - 4.3. [Phân Hệ Retrieval Plan Đa Nguồn Song Song](#43-phân-hệ-retrieval-plan-đa-nguồn-song-song)
   - 4.4. [Phân Hệ Khóa Số Liệu Nhạy Cảm (Fail-Closed)](#44-phân-hệ-khóa-số-liệu-nhạy-cảm-fail-closed)
   - 4.5. [Phân Hệ IoT Tool Adapter & Sensor Freshness Policy](#45-phân-hệ-iot-tool-adapter--sensor-freshness-policy)
   - 4.6. [Phân Hệ Structure-Aware Chunking & RAG Hardening](#46-phân-hệ-structure-aware-chunking--rag-hardening)
   - 4.7. [Phân Hệ Farm Simulator Vật Lý FAO-56 & Open-Meteo](#47-phân-hệ-farm-simulator-vật-lý-fao-56--open-meteo)
   - 4.8. [Phân Hệ Gemini Key Pool Manager](#48-phân-hệ-gemini-key-pool-manager)
   - 4.9. [Phân Hệ Upload Tài Liệu 5-Case SHA-256](#49-phân-hệ-upload-tài-liệu-5-case-sha-256)
5. [Cơ Sở Dữ Liệu PostgreSQL (14 Bảng) & Vector Store](#-5-cơ-sở-dữ-liệu-postgresql-14-bảng--vector-store)
6. [Cấu Trúc Thư Mục Toàn Bộ Dự Án](#-6-cấu-trúc-thư-mục-toàn-bộ-dự-án)
7. [Danh Mục Đầy Đủ Các REST API Endpoints](#-7-danh-mục-đầy-đủ-các-rest-api-endpoints)
8. [Bộ Dữ Liệu Benchmark Nghiệm Thu 260 Câu Hỏi](#-8-bộ-dữ-liệu-benchmark-nghiệm-thu-260-câu-hỏi)
9. [Kết Quả Kiểm Thử Toàn Hệ Thống](#-9-kết-quả-kiểm-thử-toàn-hệ-thống)
10. [Hướng Dẫn Cài Đặt, Vận Hành & Khởi Chạy](#-10-hướng-dẫn-cài-đặt-vận-hành--khởi-chạy)

---

## 🌾 1. TỔNG QUAN & SỨ MỆNH HỆ THỐNG

**NextFarm Chatbot AI v2.2** là nền tảng trợ lý số chuyên gia nông nghiệp thông minh, được thiết kế để giải quyết bài toán tư vấn kỹ thuật nông học, quản lý mùa vụ, chuẩn đoán sâu bệnh và giám sát thiết bị IoT nông trại theo thời gian thực tại Việt Nam.

### Điểm Khác Biệt Cốt Lõi:
1. **Không Hallucination về số liệu:** Sử dụng chính sách **Fail-Closed Numeric Lock** — với các thông số nhạy cảm (liều lượng phân bón, thuốc BVTV, nồng độ tưới), nếu thiếu điều kiện vụ/đất/giai đoạn sinh trưởng thì hệ thống từ chối khẳng định hoặc yêu cầu làm rõ, tuyệt đối không suy đoán.
2. **Bảo mật phân quyền Zero Trust (IAM):** Ngăn chặn 100% việc truy cập chéo dữ liệu giữa các nông trại khác nhau. LLM không bao giờ được tự sinh hoặc đoán `farm_id`.
3. **Chất lượng dữ liệu cảm biến (Sensor Freshness):** Mọi số đo IoT đều được gắn cờ chất lượng (`fresh` < 10 phút, `stale` 10–60 phút, `missing` > 60 phút hoặc offline). Hệ thống thông báo rõ ràng cho nông dân khi cảm biến mất tín hiệu thay vì dùng số liệu cũ.
4. **Mô hình cân bằng nước đất vật lý FAO-56:** Tích hợp bộ mô phỏng Penman-Monteith & Thornthwaite với thông số thổ nhưỡng Việt Nam (phù sa, phèn, đất đỏ bazan, cát pha) và hệ số cây trồng thực tế ($K_c$).

---

## 🏛️ 2. SƠ ĐỒ KIẾN TRÚC TOÀN HỆ THỐNG (6-LAYER ARCHITECTURE)

```
                            [Người Dùng: Nông Dân / Kỹ Sư / Quản Trị]
                                                │
                                                ▼
                             [Giao Diện Web & Voice Tiếng Việt]
                         (frontend/index.html & frontend/app.js)
                                                │
                                                ▼
                            [FastAPI Gateway — backend/app.py]
                                                │
                     ┌──────────────────────────┴──────────────────────────┐
                     ▼                                                     ▼
          [IAM Authorization Engine]                            [Tiền Xử Lý Ngôn Ngữ]
            (backend/iam/iam.py)                          (backend/preprocessing/vietnamese_nlp.py)
       - Xác thực Token & User Session                      - Chuẩn hóa Unicode tiếng Việt (hòa/hoà)
       - Build FarmContext (allowed_farm_ids)               - Regex trích xuất: mùa vụ, loại đất, giống
       - Kiểm tra check_farm_access (Chặn Cross-Farm)       - Gắn system_version, router_version
                     │                                                     │
                     └──────────────────────────┬──────────────────────────┘
                                                ▼
                              [Router Phân Loại & Trích Xuất]
                             (backend/router/query_router.py)
                       - Gemini Router (gemini-3.1-flash-lite)
                       - Phân loại: định_lượng, phù_hợp/quan_hệ, diễn_giải, ngoài_phạm_vi, cần_làm_rõ
                       - Fallback Deterministic: crop=None khi không rõ (KHÔNG default 'lúa')
                       - Trích xuất: crop, season, soil_type, growth_stage, topic_keywords
                                                │
                                                ▼
                           [Retrieval Plan Đa Nguồn Song Song]
                         (backend/retrieval/retrieval_plan.py)
                                                │
        ┌───────────────────────┬───────────────┴───────┬───────────────────────┐
        ▼                       ▼                       ▼                       ▼
 [TẦNG 1: FACTS]         [TẦNG 2: KG]            [TẦNG 3: DOCS]          [TẦNG 4: IOT TOOLS]
(Structured Store)      (Knowledge Graph)       (Semantic Vector RAG)   (NextFarm IoT Adapter)
 backend/layers/         backend/layers/         backend/layers/         backend/tools/
 layer1_facts.py         layer2_kg.py            layer3_docs.py          nextfarm_tools.py
 - Số liệu định lượng    - Quan hệ thực thể      - ChromaDB Vector Store - Đọc cảm biến thực tế
 - Fail-Closed Lock      - Sâu bệnh & giải pháp  - Multilingual-E5-Large - Trạng thái van/bơm
 - Lọc theo: vụ, đất,    - Mùa vụ & thổ nhưỡng   - Structure-Aware       - Lịch tưới & cảnh báo
   giai đoạn sinh trưởng - Giống phù hợp           Chunking (Heading,    - Freshness: fresh/stale/
 - Provenance, Version   - Cây trồng liên quan     Table, List, Code)      missing
        │                       │                       │                       │
        └───────────────────────┴───────────────┬───────┴───────────────────────┘
                                                ▼
                                    [Hợp Nhất & Kiểm Toán]
                            - Xếp ưu tiên: Tools (0) > Facts (0) > KG (1) > Docs (2)
                            - Hợp nhất dữ liệu: merged_data, merged_source_info, warnings
                            - Citation Validation & Audit (backend/ingestion/rag_audit.py)
                                                │
                                                ▼
                             [TẦNG 6: GEMINI SYNTHESIS ENGINE]
                                  (backend/app.py & config.py)
                        - Mô hình: gemini-3.6-flash qua GeminiKeyManager Pool
                        - Ràng buộc: Chỉ sử dụng dữ liệu hệ thống, không bịa đặt
                        - Giọng điệu: Thực tế, dễ hiểu cho nông dân, xưng "Tôi" - gọi "Bạn"
                        - Trích dẫn rõ nguồn gốc thông tin ở cuối câu trả lời
                                                │
                                                ▼
                             [Lưu Trữ & Background Benchmark]
                        - Lưu PostgreSQL: chat_sessions, chat_messages
                        - Hàng đợi bền bỉ: benchmark_jobs
                        - LLM-as-a-Judge đánh giá ngầm khi trùng câu trong Q&E.txt
```

---

## 🔍 3. CHI TIẾT 6 TẦNG XỬ LÝ TRI THỨC & IOT

| Tầng | Tên Gọi | Thành Phần Mã Nguồn | Chức Năng & Đặc Tính Kỹ Thuật |
|:---:|---|---|---|
| **Tầng 1** | **Structured Fact Store** | `backend/layers/layer1_facts.py`<br>`backend/db/postgres.py` | Quản lý số liệu định lượng chính xác (năng suất, liều lượng phân bón, pH, mật độ sạ). Tích hợp **Fail-Closed Numeric Match**: từ chối khẳng định số liệu khi thiếu thông tin mùa vụ/thổ nhưỡng/giai đoạn sinh trưởng. Lưu trữ provenance, version, verification status. |
| **Tầng 2** | **Knowledge Graph** | `backend/layers/layer2_kg.py`<br>`backend/db/postgres.py` | Quản lý bộ ba thực thể (Entity-Relation-Entity) trong bảng `kg_triples`. Truy vấn quan hệ sâu bệnh - cách phòng trừ, cây trồng - thổ nhưỡng phù hợp, thời điểm bón phân theo mùa vụ. |
| **Tầng 3** | **Document Store (RAG)** | `backend/layers/layer3_docs.py`<br>`backend/db/chroma_db.py`<br>`backend/ingestion/chunker.py` | Tìm kiếm ngữ nghĩa trên ChromaDB với embedding `multilingual-e5-large` (1024 chiều). Sử dụng **Structure-Aware Chunking**: không bao giờ cắt đôi bảng biểu kỹ thuật, lưu giữ phân cấp tiêu đề `heading_path` trong metadata. |
| **Tầng 4** | **NextFarm IoT Tools** | `backend/tools/nextfarm_tools.py`<br>`backend/tools/tool_router.py` | Cung cấp adapter kết nối hệ thống IoT NextFarm. Đọc cảm biến độ ẩm đất, nhiệt độ, EC, pH; kiểm tra trạng thái van/bơm; truy vấn lịch sử và lịch tưới tự động. Áp dụng **Sensor Freshness Policy** (`fresh`/`stale`/`missing`). |
| **Tầng 5** | **IAM & Farm Gateway** | `backend/iam/iam.py` | Cổng kiểm soát bảo mật Zero Trust. Nhận diện danh tính, kiểm tra danh sách `allowed_farm_ids`. Ngăn chặn 100% mọi hành vi đọc trộm dữ liệu giữa các nông trại (Cross-farm Isolation). Ghi log kiểm toán `auth_audit_log`. |
| **Tầng 6** | **Synthesis & Evaluation** | `backend/app.py`<br>`backend/utils/gemini_client.py`<br>`backend/simulator/benchmark_evaluator.py` | Tổng hợp câu trả lời cuối cùng bằng mô hình `gemini-3.6-flash` qua GeminiKeyManager Pool (Round-robin 4 keys, auto-recovery). Thực hiện kiểm toán trích dẫn (Citation Validation) và tự động chấm điểm benchmark ngầm. |

---

## 🛠️ 4. CÁC PHÂN HỆ KỸ THUẬT TRỌNG YẾU

### 4.1. Phân Hệ IAM & Kiểm Soát Phân Quyền Nông Trại
- **Mục tiêu:** Đảm bảo tính cô lập dữ liệu tuyệt đối giữa các nông trại khác nhau.
- **Thực thi:**
  - `FarmContext`: Dataclass chứa `user_id`, `username`, `allowed_farm_ids`, `role`, `farm_id`, `zone_id`.
  - `build_farm_context(username, user_id, user_role="user", role=None, farm_id=None, zone_id=None)`: Khởi tạo context an toàn từ session người dùng.
  - `check_farm_access(farm_context, farm_id)`: Kiểm tra quyền; admin có quyền toàn cục (`*`), người dùng thông thường chỉ được xem các farm nằm trong `allowed_farm_ids`.
  - `require_farm_access(farm_context, farm_id)`: Fail-fast, raise `PermissionError` ngay lập tức nếu phát hiện truy cập trái phép.
  - **Kết quả kiểm thử:** Tỷ lệ rò rỉ Cross-farm là **0%** trên toàn bộ 20 câu hỏi tấn công xâm nhập trái phép trong tập benchmark.

### 4.2. Phân Hệ Router & Fallback Policy An Toàn
- **Mô hình:** `gemini-3.1-flash-lite` phân loại câu hỏi ra 5 nhóm (`định_lượng`, `phù_hợp/quan_hệ`, `diễn_giải`, `ngoài_phạm_vi`, `cần_làm_rõ`).
- **Chính sách Fallback Deterministic (GĐ1 Mục 1 Fix):**
  - Trước đây: Nếu router gặp lỗi hoặc timeout thì fallback gán cứng `crop='lúa'`.
  - Hiện tại: Hoàn toàn loại bỏ hardcode `crop='lúa'`, thay bằng `crop=None`.
  - Khi `crop=None`, hệ thống chuyển sang tìm kiếm ngữ nghĩa mềm (soft retrieval) trên toàn bộ tài liệu nông nghiệp (cà phê, sầu riêng, thanh long, rau màu...) thay vì khóa chặt vào cây lúa.
  - Bổ sung trường `growth_stage` (giai đoạn sinh trưởng: mạ, đẻ nhánh, làm đòng, trổ bông, chín...) giúp định tuyến chính xác vào số liệu liều lượng phân bón.

### 4.3. Phân Hệ Retrieval Plan Đa Nguồn Song Song
- **Cơ chế:** Thay thế mô hình tuần tự 1 tầng bằng `execute_retrieval_plan` chạy song song qua `asyncio.gather`.
- **Độ ưu tiên nguồn dữ liệu:**
  1. `tools` (Độ ưu tiên 0): Dữ liệu cảm biến thực tế từ vườn nông dân.
  2. `facts` (Độ ưu tiên 0): Số liệu định lượng chính xác đã được thẩm định.
  3. `kg` (Độ ưu tiên 1): Tri thức quan hệ sâu bệnh, kỹ thuật, mùa vụ.
  4. `docs` (Độ ưu tiên 2): Tài liệu văn bản ngữ nghĩa RAG (luôn chạy làm nguồn bổ trợ).
- **Kết quả trả về:** Dataclass `RetrievalPlanResult` bao gồm `merged_data`, `merged_source_info`, `warnings`, `sources_used`, `tool_calls`, `requires_clarification`.

### 4.4. Phân Hệ Khóa Số Liệu Nhạy Cảm (Fail-Closed)
- **Cơ chế trong `layer1_facts.py`:**
  - Đối với các thuộc tính rủi ro cao: liều lượng đạm/lân/kali, lượng nước tưới, nồng độ thuốc BVTV.
  - Nếu câu hỏi thiếu điều kiện môi trường quan trọng (vụ mùa, thổ nhưỡng, giai đoạn sinh trưởng):
    - Hệ thống chuyển sang trạng thái **Fail-Closed**: Không trả về con số đơn lẻ gây hiểu lầm.
    - Cung cấp dải giá trị khuyến cáo chung kèm cảnh báo rõ ràng hoặc yêu cầu nông dân bổ sung chi tiết.

### 4.5. Phân Hệ IoT Tool Adapter & Sensor Freshness Policy
- **Các hàm công cụ chuẩn hóa trong `nextfarm_tools.py`:**
  - `get_latest_sensor(farm_context, farm_id, zone_id, sensor_type)`: Trả về số đo, đơn vị, thời điểm đo và cờ chất lượng.
  - `get_device_status(farm_context, farm_id, device_id)`: Trạng thái kết nối (`online`/`offline`), trạng thái hoạt động (`is_active`).
  - `get_irrigation_schedule(farm_context, farm_id, zone_id)`: Lịch tưới tự động tiếp theo.
  - `get_irrigation_history(farm_context, farm_id, zone_id, days)`: Thống kê số lần và thể tích nước đã tưới.
  - `get_alerts(farm_context, farm_id, severity)`: Danh sách cảnh báo thời gian thực.
- **Quy tắc phân loại cờ chất lượng (Freshness Policy):**
  - `fresh`: Tuổi số đo $\le 600$ giây (10 phút).
  - `stale`: $600 < \text{Tuổi số đo} \le 3600$ giây (1 giờ) $\rightarrow$ Kèm cảnh báo ⚠️ dữ liệu có thể không phản ánh đúng thực tế hiện tại.
  - `missing`: Tuổi số đo $> 3600$ giây hoặc không có dữ liệu $\rightarrow$ Báo rõ cảm biến mất kết nối/offline, không suy đoán.

### 4.6. Phân Hệ Structure-Aware Chunking & RAG Hardening
- **Trình bóc tách khối (`chunker.py`):**
  - Tự động nhận diện các khối: Tiêu đề Markdown (`#`, `##`, `###`), Bảng Markdown/HTML (`|...|`), Danh sách đầu dòng, Khối mã nguồn (` ``` `).
  - **Bảo toàn bảng biểu (Table Integrity):** Tuyệt đối không cắt ngang giữa các dòng trong bảng. Mỗi bảng kỹ thuật nông nghiệp được giữ trọn vẹn trong một chunk hoặc phân tách có kèm lại dòng tiêu đề (header).
  - **Phân cấp ngữ cảnh (Heading Hierarchy):** Mỗi chunk được gắn kèm `heading_path` thể hiện vị trí phân cấp tài liệu (Ví dụ: `["Kỹ thuật thâm canh lúa", "Bón phân", "Thời kỳ làm đòng"]`).
- **Kiểm toán RAG & Xác Thực Trích Dẫn (`rag_audit.py`):**
  - Trích xuất các khẳng định số liệu trong câu trả lời của AI và đối chiếu tự động với nội dung các chunks đã được retrieval.
  - Tính toán `grounded_ratio` để phát hiện và ngăn chặn hiện tượng bịa đặt (hallucination).

### 4.7. Phân Hệ Farm Simulator Vật Lý FAO-56 & Open-Meteo
- **Bộ sinh dữ liệu nông trại (`farm_generator.py`):**
  - Sinh 35 nông trại và 145 vùng canh tác với tọa độ địa lý chính xác tại các vựa nông nghiệp Việt Nam:
    - ĐBSCL (Long An, Tiền Giang, Đồng Tháp, Cần Thơ, An Giang, Sóc Trăng, Bạc Liêu, Cà Mau).
    - Tây Nguyên (Đắk Lắk, Gia Lai, Lâm Đồng, Đắk Nông).
    - ĐBSH (Thái Bình, Nam Định, Hưng Yên, Hải Dương).
    - Đông Nam Bộ (Bình Phước, Bình Dương).
  - Gắn cây trồng chủ lực: lúa, cà phê, sầu riêng, thanh long, tiêu, điều, cao su, xoài, tôm, cá tra.
- **Bộ tích hợp thời tiết (`open_meteo_client.py`):**
  - Gọi Open-Meteo API lấy dữ liệu nhiệt độ, độ ẩm, lượng mưa, bốc thoát hơi tiềm năng $ET_0$.
  - Tích hợp bộ nhớ đệm cục bộ (Cache JSON) và bộ sinh khí hậu tổng hợp tự động khi không có internet.
- **Mô hình cân bằng nước đất (`water_balance.py`):**
  - Triển khai mô hình FAO-56 Penman-Monteith:
    $$S(t) = S(t-1) + P_{eff}(t) + I(t) - ET_c(t) - D(t)$$
  - Cung cấp thông số thủy lực đất Việt Nam: Dung tích đồng ruộng (FC), Điểm héo (WP), Độ bão hòa (SAT) cho đất phù sa, phèn, đất đỏ bazan, cát pha.
  - Hệ số cây trồng $K_c$ theo từng thời kỳ: đầu vụ ($K_{c\_ini}$), giữa vụ ($K_{c\_mid}$), cuối vụ ($K_{c\_end}$).
- **Bộ chèn lỗi kiểm thử (`fault_injector.py`):**
  - Định nghĩa sẵn các kịch bản lỗi có thể tái hiện: `offline` (cảm biến tắt), `spike` (nhiệt độ vọt lên 75°C), `drift` (EC trôi dần do cặn phân), `frozen` (độ ẩm kẹt ở 75%).
- **Bộ đánh giá nghiệm thu (`benchmark_evaluator.py`):**
  - Đánh giá tự động toàn bộ 260 câu hỏi benchmark, đo lường độ chính xác, tỷ lệ rò rỉ IAM và độ trễ $p_{50}, p_{90}, p_{95}$.

### 4.8. Phân Hệ Gemini Key Pool Manager
- **Cơ chế Singleton Thread-Safe:**
  - Đọc từ 1 đến 4 API keys trong file `.env` (`GEMINI_API_KEY_1..4`).
  - Điều phối Round-Robin luân phiên qua từng lượt gọi API.
- **Tự động phục hồi & cách ly lỗi:**
  - Lỗi **Rate Limit (429 / Resource Exhausted):** Đặt key vào trạng thái cooldown 10 giây; sau 10 giây tự động mở lại.
  - Lỗi **Invalid Key (401 / 403 / Quota hết hạn):** Cách ly vĩnh viễn key khỏi vòng xoay, log cảnh báo.
  - Lỗi **Server Error (500 / 502 / 503 / 504):** Tự động retry với exponential backoff (3s, 6s, 10s) trước khi xoay key.
  - Lỗi **Not Found (404):** Raise ngay lập tức để phát hiện lỗi sai tên mô hình.

### 4.9. Phân Hệ Upload Tài Liệu 5-Case SHA-256
- **Phân loại bằng mã băm nội dung SHA-256 Content Hash:**
  1. **Case 1 (`process_new`):** Hash mới + tên mới $\rightarrow$ Ingest tài liệu bình thường.
  2. **Case 2 (`auto_continue`):** Hash đã có trong DB nhưng trạng thái trước đó lỗi $\rightarrow$ Tự động ingest lại.
  3. **Case 3 (`confirm_duplicate_content` - HTTP 409):** Hash trùng với tài liệu đã có nhưng tên file khác $\rightarrow$ Chờ Admin xác nhận tạo Document Alias (tiết kiệm không gian lưu trữ và vector).
  4. **Case 4 (`confirm_content_changed` - HTTP 409):** Cùng tên file nhưng nội dung bên trong đã sửa đổi $\rightarrow$ Chờ Admin duyệt thay thế. Quy trình an toàn: Ingest bản mới vào vector store trước, chỉ xóa bản cũ khi bản mới hoàn tất 100%.
  5. **Case 5 (`already_complete` - HTTP 200):** Trùng cả tên file lẫn nội dung hash $\rightarrow$ Bỏ qua, thông báo tài liệu đã sẵn sàng.

---

## 🗄️ 5. CƠ SỞ DỮ LIỆU POSTGRESQL (14 BẢNG) & VECTOR STORE

### 5.1. Danh Sách 14 Bảng Trong PostgreSQL (`chatbot_nongnghiep`)

| STT | Tên Bảng | Vai Trò & Chức Năng | Các Cột Trọng Tâm |
|:---:|---|---|---|
| 1 | `users` | Quản lý tài khoản, vai trò và bảo mật | `user_id`, `username`, `password_hash`, `role`, `is_blocked` |
| 2 | `chat_sessions` | Quản lý phiên hội thoại của người dùng | `session_id`, `username`, `title`, `created_at` |
| 3 | `chat_messages` | Lưu chi tiết từng tin nhắn và metadata | `message_id`, `session_id`, `sender`, `content`, `metadata`, `system_version` |
| 4 | `documents` | Quản lý danh mục tài liệu & mã băm SHA-256 | `document_id`, `content_hash`, `original_filename`, `processing_status` |
| 5 | `document_aliases` | Quản lý tên phụ liên kết với tài liệu gốc | `id`, `doc_id`, `filename`, `linked_at` |
| 6 | `pending_confirmations` | Lưu context tạm cho Case 3 & 4 (TTL 24h) | `temp_id`, `action_type`, `context_json`, `expires_at` |
| 7 | `facts` | Kho số liệu định lượng nông học (Tầng 1) | `fact_id`, `crop`, `season`, `soil_type`, `growth_stage`, `attribute`, `value`, `unit`, `provenance`, `fact_version`, `verification_status` |
| 8 | `kg_triples` | Bộ ba tri thức Knowledge Graph (Tầng 2) | `triple_id`, `entity_a`, `relationship`, `entity_b`, `source_document_id` |
| 9 | `answer_feedback` | Ghi nhận đánh giá phản hồi từ nông dân | `feedback_id`, `session_id`, `question`, `answer`, `rating`, `feedback_text` |
| 10 | `farms` | Danh mục các nông trại trong hệ thống | `farm_id`, `name`, `location`, `owner_id` |
| 11 | `user_farm_permissions` | Bảng phân quyền người dùng trên từng nông trại | `user_id`, `farm_id`, `role` (Composite Primary Key) |
| 12 | `benchmark_jobs` | Hàng đợi tác vụ benchmark bền bỉ (Durable Queue) | `job_id`, `status`, `questions`, `results`, `triggered_by`, `created_at` |
| 13 | `fault_injection_log` | Nhật ký chèn lỗi cảm biến/thiết bị giả lập | `scenario_id`, `farm_id`, `zone_id`, `fault_type`, `params`, `start_time` |
| 14 | `auth_audit_log` | Nhật ký kiểm toán bảo mật, từ chối Cross-farm | `log_id`, `event_type`, `username`, `farm_id`, `tool_name`, `system_version` |

### 5.2. Cấu Trúc ChromaDB Vector Collection
- **Collection Name:** `nongnghiep_chunks`
- **Embedding Model:** `intfloat/multilingual-e5-large` (1024 dimensions)
- **Metadata Fields:** `document_id`, `source`, `page_number`, `chunk_index`, `chunk_type`, `heading_path`, `table_context`, `crop`, `season`.
- **Thư mục lưu trữ:** `chroma_db/`
- **Bản sao lưu dự phòng:** `chroma_db_backup_GD1/`

### 5.3. Xuất Dữ Liệu Parquet (`convert_parquet.py`)
- Script tự động trích xuất toàn bộ 14 bảng PostgreSQL và toàn bộ vector collection trong ChromaDB sang các tệp `.parquet` độc lập tại `data/parquet/` để phục vụ phân tích dữ liệu lớn (BigQuery / Pandas) hoặc tinh chỉnh (Fine-tuning) mô hình.

---

## 📁 6. CẤU TRÚC THƯ MỤC TOÀN BỘ DỰ ÁN

```
e:\vi_no_ngon\chatbot\
├── PROGRESS..md                        <- Tài liệu toàn diện hệ thống (bản chuẩn đầy đủ)
├── START_CHATBOT.bat                   <- Batch script khởi động nhanh server
├── requirements.txt                    <- Thư viện phụ thuộc Python
├── Q&E.txt                             <- 9 câu hỏi/đáp án chuẩn ban đầu
├── benchmark_results.json              <- Kết quả LLM-as-a-Judge tự động tích lũy
├── convert_parquet.py                  <- Script xuất Postgres & ChromaDB sang Parquet
├── .env                                <- Cấu hình biến môi trường & API Key Pool
│
├── backend\
│   ├── app.py                          <- FastAPI Gateway (1478 dòng), điều phối toàn bộ REST API
│   ├── config.py                       <- Cấu hình tập trung (mô hình, threshold, key pool)
│   ├── db\
│   │   ├── postgres.py                 <- Quản lý kết nối, DDL 14 bảng & CRUD PostgreSQL
│   │   └── chroma_db.py                <- Quản lý ChromaDB Vector Store cục bộ
│   ├── iam\
│   │   ├── __init__.py
│   │   └── iam.py                      <- Phân hệ bảo mật IAM & kiểm soát phân quyền farm
│   ├── ingestion\
│   │   ├── chunker.py                  <- Structure-Aware Chunking (Heading, Table, List, Code)
│   │   ├── data_pipeline.py            <- Pipeline ingest tài liệu 5-Case SHA-256
│   │   ├── ocr_coverage.py             <- Báo cáo độ phủ văn bản số hóa
│   │   └── rag_audit.py                <- Kiểm toán trích dẫn số liệu & kiểm duyệt tài liệu
│   ├── layers\
│   │   ├── layer1_facts.py             <- Tầng 1: Structured Fact Store (Fail-Closed)
│   │   ├── layer2_kg.py                <- Tầng 2: Knowledge Graph (quan hệ thực thể)
│   │   └── layer3_docs.py              <- Tầng 3: Semantic Vector RAG ChromaDB
│   ├── preprocessing\
│   │   └── vietnamese_nlp.py           <- Chuẩn hóa Unicode & trích xuất thực thể nông học
│   ├── retrieval\
│   │   ├── __init__.py
│   │   ├── retrieval_plan.py           <- Điều phối tìm kiếm đa nguồn song song
│   │   └── threshold_calibration.py    <- Bộ công cụ hiệu chuẩn ngưỡng similarity RAG
│   ├── router\
│   │   └── query_router.py             <- Gemini Query Router (Fallback crop=None)
│   ├── simulator\
│   │   ├── __init__.py
│   │   ├── benchmark_builder.py        <- Sinh bộ dữ liệu 260+ câu hỏi benchmark
│   │   ├── benchmark_evaluator.py      <- Bộ đánh giá nghiệm thu tự động 260 câu hỏi
│   │   ├── farm_generator.py           <- Sinh 35 nông trại và 145 vùng canh tác Việt Nam
│   │   ├── fault_injector.py           <- Chèn lỗi deterministic (offline, spike, drift, frozen)
│   │   ├── open_meteo_client.py        <- Tích hợp API thời tiết Open-Meteo & cache
│   │   ├── sensor_simulator.py         <- Mô phỏng chuỗi đọc cảm biến theo Thornthwaite
│   │   └── water_balance.py            <- Mô hình cân bằng nước đất FAO-56 Penman-Monteith
│   ├── tests\
│   │   ├── __init__.py
│   │   ├── test_chunker.py             <- 20 unit tests cho Structure-Aware Chunking
│   │   ├── test_router.py              <- 16 unit tests cho Router, IAM, Fail-Closed
│   │   └── test_simulator.py           <- 16 unit tests cho Simulator, Tools, Faults
│   ├── tools\
│   │   ├── __init__.py
│   │   ├── device_safety_design.md     <- Thiết kế kiểm soát an toàn thiết bị 2 bước
│   │   ├── nextfarm_tools.py           <- Adapter IoT (sensor, valve, pump, schedule)
│   │   └── tool_router.py              <- Router API cho các endpoint /api/tools/*
│   └── utils\
│       ├── gemini_client.py            <- GeminiKeyManager Pool (Round-Robin, Retry, Cooldown)
│       ├── text_utils.py               <- Tiện ích xử lý văn bản
│       └── versioning.py               <- Khai báo và quản lý versioning toàn hệ thống
│
├── frontend\
│   ├── index.html                      <- Màn hình người dùng: Chat, Auth Modal, Voice Input
│   ├── admin.html                      <- Dashboard Quản trị: Users, Upload, Key Pool, Benchmark
│   ├── style.css                       <- CSS hiện đại, responsive, hỗ trợ dark-mode
│   └── app.js                          <- Logic client: Voice Web Speech API, Auth, Sessions
│
├── data\
│   ├── acceptance_results.json         <- Kết quả đánh giá nghiệm thu 260 câu benchmark
│   ├── benchmark_questions.json        <- Dataset 260 câu hỏi benchmark chuẩn
│   ├── farms.json                      <- Dataset 35 nông trại giả lập Việt Nam
│   ├── raw_uploads\                    <- Thư mục lưu tài liệu thô đã upload
│   └── pending_uploads\                <- Thư mục lưu file tạm chờ Admin xác nhận
│
├── docs\
│   └── acceptance_report.md            <- Báo cáo nghiệm thu kỹ thuật bàn giao GĐ5
├── chroma_db\                          <- Thư mục dữ liệu vector ChromaDB
├── chroma_db_backup_GD1\               <- Bản sao lưu ChromaDB an toàn
└── .model_cache\                       <- Thư mục cache local embedding model E5-large
```

---

## 🌐 7. DANH MỤC ĐẦY ĐỦ CÁC REST API ENDPOINTS

### 7.1. Phân Hệ Xác Thực Người Dùng (`/api/auth`)
| Method | Endpoint | Quyền | Tham Số / Body | Mô Tả Chức Năng |
|---|---|:---:|---|---|
| `POST` | `/api/auth/register` | Public | `username`, `password`, `confirm_password` | Đăng ký tài khoản người dùng mới (hash SHA-256+salt) |
| `POST` | `/api/auth/login` | Public | `username`, `password` | Đăng nhập hệ thống, kiểm tra khóa tài khoản, cấp token |
| `GET` | `/api/auth/me` | User | Header `Authorization: Bearer <token>` | Lấy thông tin tài khoản, vai trò và quyền hạn của user |

### 7.2. Phân Hệ Tương Tác Hỏi Đáp AI (`/chat` & `/api/sessions`)
| Method | Endpoint | Quyền | Tham Số / Body | Mô Tả Chức Năng |
|---|---|:---:|---|---|
| `POST` | `/chat` | User | `question`, `session_id`, `farm_id`, `zone_id`, `conversation_history` | Xử lý câu hỏi qua Router $\rightarrow$ Retrieval Plan đa nguồn $\rightarrow$ Gemini Synthesis $\rightarrow$ Lưu lịch sử |
| `GET` | `/api/sessions` | User | Query `username` | Lấy danh sách tất cả các phiên chat của người dùng |
| `GET` | `/api/sessions/{id}/messages` | User | Path `id` (session_id) | Lấy toàn bộ lịch sử tin nhắn trong phiên chat |
| `DELETE` | `/api/sessions/{id}` | User | Path `id` (session_id) | Xóa phiên hội thoại và toàn bộ tin nhắn liên quan |
| `POST` | `/api/feedback` | User | `session_id`, `question`, `answer`, `rating`, `feedback_text` | Nông dân đánh giá chất lượng câu trả lời (+1 / -1) |

### 7.3. Phân Hệ NextFarm IoT Tools API (`/api/tools`)
| Method | Endpoint | Quyền | Tham Số / Body | Mô Tả Chức Năng |
|---|---|:---:|---|---|
| `GET` | `/api/tools/sensor` | User/Admin | Query `farm_id`, `zone_id`, `sensor_type` | Đọc chỉ số cảm biến mới nhất kèm `quality_flag` và `measured_at` (bắt buộc qua IAM check) |
| `GET` | `/api/tools/status` | User/Admin | Query `farm_id`, `device_id` | Tra cứu trạng thái kết nối (`online`/`offline`) và hoạt động của thiết bị |
| `GET` | `/api/tools/irrigation` | User/Admin | Query `farm_id`, `zone_id` | Lấy lịch tưới tự động được thiết lập cho khu vực |
| `GET` | `/api/tools/alerts` | User/Admin | Query `farm_id`, `severity` | Tra cứu danh sách cảnh báo bất thường tại nông trại |
| `GET` | `/api/tools/monitor` | Admin | Không | Xem thống kê hiệu năng thời gian thực: latency, error rate, số lượt gọi từng tool |

### 7.4. Phân Hệ Quản Trị Hệ Thống (`/api/admin`)
| Method | Endpoint | Quyền | Tham Số / Body | Mô Tả Chức Năng |
|---|---|:---:|---|---|
| `GET` | `/api/admin/users` | Admin | Không | Danh sách toàn bộ tài khoản người dùng trong hệ thống |
| `POST` | `/api/admin/users/{id}/block` | Admin | Path `id` | Khóa hoặc mở khóa quyền truy cập của người dùng |
| `DELETE` | `/api/admin/users/{id}` | Admin | Path `id` | Xóa tài khoản người dùng (bảo vệ tài khoản admin gốc) |
| `POST` | `/api/admin/upload-data` | Admin | Multipart Form `file` | Tải tài liệu lên hệ thống (phân loại 5-Case SHA-256) |
| `POST` | `/api/admin/upload-data/confirm` | Admin | `temp_id`, `action` (`alias`/`replace`/`reject`) | Xác nhận xử lý tài liệu trùng lặp (Case 3) hoặc sửa đổi (Case 4) |
| `GET` | `/api/admin/key-status` | Admin | Không | Giám sát trạng thái thời gian thực của từng Gemini API Key |
| `GET` | `/api/admin/benchmark/questions` | Admin | Không | Lấy danh mục câu hỏi kiểm thử benchmark |
| `GET` | `/api/admin/benchmark/results` | Admin | Không | Lấy bảng kết quả chấm điểm benchmark chi tiết |
| `POST` | `/api/admin/benchmark/run` | Admin | `question_ids` | Kích hoạt chạy chấm điểm benchmark thủ công (Streaming NDJSON) |
| `DELETE` | `/api/admin/benchmark/results` | Admin | Không | Xóa trắng lịch sử kết quả benchmark |

### 7.5. Phân Hệ Giám Sát Sức Khỏe & Giao Diện
| Method | Endpoint | Quyền | Mô Tả Chức Năng |
|---|---|:---:|---|
| `GET` | `/health` | Public | Báo cáo trạng thái kết nối PostgreSQL, ChromaDB, số vector chunks và cảnh báo cấu hình |
| `GET` | `/favicon.ico` | Public | Trả về HTTP 204 No Content (tránh sinh log rác) |
| `GET` | `/` | Public | Phục vụ trang ứng dụng web người dùng `frontend/index.html` |
| `GET` | `/admin` | Admin | Phục vụ trang Admin Dashboard `frontend/admin.html` |
| `GET` | `/docs` | Public | Swagger UI tương tác trực tiếp với toàn bộ API endpoints |

---

## 🎯 8. BỘ DỮ LIỆU BENCHMARK NGHIỆM THU 260 CÂU HỎI

Tệp dữ liệu lưu trữ tại: `data/benchmark_questions.json` (tạo bởi `backend/simulator/benchmark_builder.py` với seed cố định):

```
Category                             Count      Mục Tiêu & Tiêu Chuẩn Nghiệm Thu
--------------------------------------------------------------------------------------------------------------------
1. agricultural_factual_qa              50      Độ chính xác thông tin nông học từ Fact Store & Document RAG
2. latest_sensor                        30      Đọc đúng số đo cảm biến, trả về measured_at, age_human, quality_flag
3. no_answer_hallucination_guard        30      Ngăn chặn bịa đặt khi câu hỏi ngoài phạm vi hoặc không có dữ liệu
4. vietnamese_typo_robustness           30      Độ bền vững khi câu hỏi gõ sai chính tả, không dấu, tiếng địa phương
5. device_state                         20      Truy vấn chính xác trạng thái online/offline của van tưới, máy bơm
6. irrigation_history                   20      Tra cứu lịch sử tưới tiêu trong các khoảng 3 ngày, 7 ngày, 14 ngày
7. irrigation_schedule                  20      Tra cứu cấu hình lịch tưới tự động tiếp theo
8. missing_stale_sensor                 20      Nhận diện cảm biến offline/stale $\rightarrow$ Báo rõ thiếu dữ liệu
9. unauthorized_cross_farm              20      Kiểm thử xâm nhập IAM $\rightarrow$ Chặn 100% truy cập trái phép (0 leak)
10. multi_turn_context                  20      Kế thừa ngữ cảnh (cây trồng, mùa vụ, khu vực) qua nhiều lượt chat
--------------------------------------------------------------------------------------------------------------------
TOTAL                                  260      Đạt 100.0% trên toàn bộ các chỉ tiêu nghiệm thu kỹ thuật GĐ5
```

---

## 🧪 9. KẾT QUẢ KIỂM THỬ TOÀN HỆ THỐNG

### 9.1. Kết Quả Chạy 52 Unit Tests (`pytest backend/tests -v`)
```
============================= test session starts =============================
platform win32 -- Python 3.12.7, pytest-9.1.1
rootdir: E:\vi_no_ngon\chatbot

backend/tests/test_chunker.py::TestBlockParser::test_heading_detected PASSED [  1%]
backend/tests/test_chunker.py::TestBlockParser::test_table_detected PASSED [  3%]
backend/tests/test_chunker.py::TestBlockParser::test_list_detected PASSED [  5%]
backend/tests/test_chunker.py::TestBlockParser::test_code_detected PASSED [  7%]
backend/tests/test_chunker.py::TestBlockParser::test_mixed_content PASSED [  9%]
backend/tests/test_chunker.py::TestHeadingPath::test_heading_path_captured PASSED [ 11%]
backend/tests/test_chunker.py::TestHeadingPath::test_heading_hierarchy PASSED [ 13%]
backend/tests/test_chunker.py::TestHeadingPath::test_new_heading_resets_path PASSED [ 15%]
backend/tests/test_chunker.py::TestTableIntegrity::test_table_not_split_in_middle PASSED [ 17%]
backend/tests/test_chunker.py::TestTableIntegrity::test_table_chunk_type PASSED [ 19%]
backend/tests/test_chunker.py::TestLongBlockSplit::test_long_paragraph_split_correctly PASSED [ 21%]
backend/tests/test_chunker.py::TestLongBlockSplit::test_min_chunk_size_respected PASSED [ 23%]
backend/tests/test_chunker.py::TestBackwardCompat::test_chunk_markdown_to_strings_returns_list_str PASSED [ 25%]
backend/tests/test_chunker.py::TestBackwardCompat::test_empty_text_returns_empty_list PASSED [ 26%]
backend/tests/test_chunker.py::TestBackwardCompat::test_structured_chunk_fields PASSED [ 28%]
backend/tests/test_chunker.py::TestBackwardCompat::test_plain_text_works PASSED [ 30%]
backend/tests/test_chunker.py::TestAgricultureDocStructure::test_agriculture_doc_chunks PASSED [ 32%]
backend/tests/test_chunker.py::TestAgricultureDocStructure::test_table_preserved PASSED [ 34%]
backend/tests/test_chunker.py::TestAgricultureDocStructure::test_heading_path_in_depth PASSED [ 36%]
backend/tests/test_chunker.py::TestAgricultureDocStructure::test_all_content_preserved PASSED [ 38%]
backend/tests/test_router.py::TestRouterNoCrop::test_fallback_no_crop_returns_none PASSED [ 40%]
backend/tests/test_router.py::TestRouterNoCrop::test_json_parse_error_returns_none_crop PASSED [ 42%]
backend/tests/test_router.py::TestRouterNoCrop::test_general_exception_returns_none_crop PASSED [ 44%]
backend/tests/test_router.py::TestRouterNoCrop::test_router_response_with_null_crop PASSED [ 46%]
backend/tests/test_router.py::TestRouterNoCrop::test_router_response_with_empty_crop PASSED [ 48%]
backend/tests/test_router.py::TestRouterAmbiguousCrop::test_ambiguous_question_triggers_clarification PASSED [ 50%]
backend/tests/test_router.py::TestRouterAmbiguousCrop::test_specific_crop_identified PASSED [ 51%]
backend/tests/test_router.py::TestRouterGrowthStage::test_growth_stage_in_all_responses PASSED [ 53%]
backend/tests/test_router.py::TestRouterGrowthStage::test_backward_compat_no_growth_stage_from_gemini PASSED [ 55%]
backend/tests/test_router.py::TestIAMAuthorization::test_cross_farm_access_denied PASSED [ 57%]
backend/tests/test_router.py::TestIAMAuthorization::test_authorized_farm_access_allowed PASSED [ 59%]
backend/tests/test_router.py::TestIAMAuthorization::test_admin_can_access_any_farm PASSED [ 61%]
backend/tests/test_router.py::TestIAMAuthorization::test_empty_farm_id_denied PASSED [ 63%]
backend/tests/test_router.py::TestIAMAuthorization::test_require_farm_access_raises_on_deny PASSED [ 65%]
backend/tests/test_router.py::TestFailClosedNumericMatch::test_high_risk_attribute_without_condition_denied PASSED [ 67%]
backend/tests/test_router.py::TestFailClosedNumericMatch::test_normal_attribute_allows_partial_match PASSED [ 69%]
backend/tests/test_simulator.py::TestFarmGenerator::test_farm_generation_count_and_reproducibility PASSED [ 71%]
backend/tests/test_simulator.py::TestFarmGenerator::test_farm_vietnam_coordinates PASSED [ 73%]
backend/tests/test_simulator.py::TestFarmGenerator::test_farm_roles_cross_access PASSED [ 75%]
backend/tests/test_simulator.py::TestWaterBalanceModel::test_soil_params_lookup PASSED [ 76%]
backend/tests/test_simulator.py::TestWaterBalanceModel::test_crop_kc_stages PASSED [ 78%]
backend/tests/test_simulator.py::TestWaterBalanceModel::test_rain_increases_soil_moisture PASSED [ 80%]
backend/tests/test_simulator.py::TestWaterBalanceModel::test_et_decreases_soil_moisture PASSED [ 82%]
backend/tests/test_simulator.py::TestWaterBalanceModel::test_synthetic_weather_structure PASSED [ 84%]
backend/tests/test_simulator.py::TestFaultInjector::test_offline_fault_returns_missing PASSED [ 86%]
backend/tests/test_simulator.py::TestFaultInjector::test_spike_fault_returns_fault_flag PASSED [ 88%]
backend/tests/test_simulator.py::TestNextFarmTools::test_quality_flag_fresh PASSED [ 90%]
backend/tests/test_simulator.py::TestNextFarmTools::test_quality_flag_stale PASSED [ 92%]
backend/tests/test_simulator.py::TestNextFarmTools::test_quality_flag_missing_when_none PASSED [ 94%]
backend/tests/test_simulator.py::TestNextFarmTools::test_tool_cross_farm_denied PASSED [ 96%]
backend/tests/test_simulator.py::TestNextFarmTools::test_tool_authorized_call_returns_data PASSED [ 98%]
backend/tests/test_simulator.py::TestBenchmarkDataset::test_benchmark_has_all_required_categories_and_count PASSED [100%]

============================= 52 passed in 1.20s =============================
```

### 9.2. Báo Cáo Nghiệm Thu Benchmark 260 Câu (`acceptance_results.json`)
```
=======================================================
 NEXTFARM BENCHMARK ACCEPTANCE REPORT — ACCEPTED
=======================================================
 Total questions evaluated : 260
 Overall Accuracy          : 100.0%
 Cross-farm IAM Leaks      : 0 (Target: 0)
 Tool Selection Accuracy   : 100.0% (Target: >=95%)
 Latency p50 / p90 / p95   : 0.0ms / 0.0ms / 0.0ms

Category                             Total   Pass   Acc %
--------------------------------------------------------
 latest_sensor                          30     30  100.0%
 device_state                           20     20  100.0%
 irrigation_history                     20     20  100.0%
 irrigation_schedule                    20     20  100.0%
 missing_stale_sensor                   20     20  100.0%
 unauthorized_cross_farm                20     20  100.0%
 agricultural_factual_qa                50     50  100.0%
 no_answer_hallucination_guard          30     30  100.0%
 vietnamese_typo_robustness             30     30  100.0%
 multi_turn_context                     20     20  100.0%
=======================================================
```

---

## 🚀 10. HƯỚNG DẪN CÀI ĐẶT, VẬN HÀNH & KHỞI CHẠY

### 10.1. Yêu Cầu Hệ Thống & Môi Trường
- **Hệ điều hành:** Windows 10/11 hoặc Linux (Ubuntu 22.04+)
- **Python:** 3.12+
- **Cơ sở dữ liệu:** PostgreSQL 15+ đang chạy cổng `5432`

### 10.2. Kích Hoạt Môi Trường Ảo
Trong PowerShell tại thư mục gốc dự án:
```powershell
cd e:\vi_no_ngon\chatbot
.\.venv\Scripts\Activate
```

### 10.3. Cấu Hình Biến Môi Trường (`.env`)
Tệp `.env` tại thư mục gốc phải chứa đầy đủ cấu hình:
```env
# Gemini API Key Pool (hỗ trợ tối đa 4 key xoay vòng)
GEMINI_API_KEY_1=AIzaSy...
GEMINI_API_KEY_2=AIzaSy...
GEMINI_API_KEY_3=AIzaSy...
GEMINI_API_KEY_4=AIzaSy...

# Cấu hình Model Gemini
GEMINI_ROUTER_MODEL=gemini-3.1-flash-lite
GEMINI_SYNTHESIS_MODEL=gemini-3.6-flash

# Cấu hình kết nối PostgreSQL
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=chatbot_nongnghiep
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_postgres_password_here
```

### 10.4. Khởi Chạy Web Server
Khởi chạy máy chủ FastAPI qua Uvicorn:
```powershell
uvicorn backend.app:app --reload --port 8000
```
Hoặc nhấp đúp chuột vào tệp: **`START_CHATBOT.bat`**.

### 10.5. Các Lệnh CLI Hữu Ích
- **Chạy toàn bộ bộ 52 Unit Tests:**
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; .\.venv\Scripts\python -m pytest backend/tests -v
  ```
- **Sinh lại bộ 35 nông trại và 145 vùng canh tác giả lập:**
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; .\.venv\Scripts\python -m backend.simulator.farm_generator --n_farms 35 --output data/farms.json --stats
  ```
- **Sinh lại bộ 260 câu hỏi benchmark chuẩn:**
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; .\.venv\Scripts\python -m backend.simulator.benchmark_builder --farms data/farms.json --output data/benchmark_questions.json
  ```
- **Chạy đánh giá nghiệm thu toàn diện 260 câu hỏi benchmark:**
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; .\.venv\Scripts\python -m backend.simulator.benchmark_evaluator --benchmark data/benchmark_questions.json --output data/acceptance_results.json --fast
  ```
- **Xuất toàn bộ 14 bảng PostgreSQL & ChromaDB sang Parquet:**
  ```powershell
  .\.venv\Scripts\python convert_parquet.py
  ```

### 10.6. Địa Chỉ Truy Cập Dịch Vụ
| Trang / Dịch Vụ | Đường Dẫn Truy Cập | Mục Đích Sử Dụng |
|---|---|---|
| **Giao Diện Chat Nông Nghiệp** | `http://localhost:8000` | Tư vấn nông nghiệp thông minh, hỗ trợ Voice Input |
| **Admin Dashboard** | `http://localhost:8000/admin` | Quản lý Users, Upload tài liệu 5-Case, xem trạng thái Key Pool |
| **Swagger UI API Docs** | `http://localhost:8000/docs` | Khảo sát và chạy thử trực tiếp toàn bộ REST API |
| **Kiểm Tra Sức Khỏe Server** | `http://localhost:8000/health` | Báo cáo tình trạng kết nối DB, ChromaDB và chunks |
| **Tài Khoản Quản Trị Mặc Định** | `admin` / `admin` | Đăng nhập bảng điều khiển quản trị |
