# 🌾 NextFarm Chatbot Nông Nghiệp AI — v2.2
## Tài liệu hệ thống đầy đủ & Hướng dẫn vận hành

---

## 📋 Mục lục

1. [Tổng quan hệ thống](#1-tổng-quan-hệ-thống)
2. [Kiến trúc tổng thể](#2-kiến-trúc-tổng-thể)
3. [Cấu trúc thư mục](#3-cấu-trúc-thư-mục)
4. [Chi tiết từng module](#4-chi-tiết-từng-module)
5. [Cơ sở dữ liệu](#5-cơ-sở-dữ-liệu)
6. [Luồng xử lý câu hỏi](#6-luồng-xử-lý-câu-hỏi)
7. [Hệ thống IAM & Bảo mật](#7-hệ-thống-iam--bảo-mật)
8. [Pipeline nạp dữ liệu](#8-pipeline-nạp-dữ-liệu)
9. [Benchmark & Đánh giá](#9-benchmark--đánh-giá)
10. [Monitoring & Giám sát](#10-monitoring--giám-sát)
11. [Cấu hình .env](#11-cấu-hình-env)
12. [Hướng dẫn cài đặt & Chạy hệ thống](#12-hướng-dẫn-cài-đặt--chạy-hệ-thống)
13. [Danh sách API Endpoints](#13-danh-sách-api-endpoints)
14. [Troubleshooting](#14-troubleshooting)

---

## 1. Tổng quan hệ thống

**NextFarm Chatbot** là hệ thống chatbot tư vấn nông nghiệp thông minh, xây dựng trên kiến trúc **RAG (Retrieval-Augmented Generation)** kết hợp với **Agentic Tools** để hỗ trợ nông dân tra cứu thông tin:

- 🌾 Kỹ thuật canh tác đa dạng nông sản (lúa, cà phê, sầu riêng, dưa hấu, rau màu, gia súc...)
- 💊 Liều lượng phân bón, thuốc BVTV theo mùa vụ, loại đất, giai đoạn sinh trưởng
- 🌱 Chọn giống phù hợp điều kiện đất đai, thời vụ
- 📡 Đọc dữ liệu cảm biến IoT thời gian thực từ NextFarm Platform
- 🔒 Quản lý phân quyền theo trang trại (Farm-level IAM)

### Công nghệ cốt lõi

| Thành phần | Công nghệ |
|---|---|
| Backend API | FastAPI + Uvicorn |
| LLM | Google Gemini (gemini-3.6-flash, gemini-3.1-flash-lite) |
| Embedding | `intfloat/multilingual-e5-large` (1024 dims) |
| Vector DB | ChromaDB (local persistent) |
| Relational DB | PostgreSQL |
| Sparse Retrieval | BM25 Okapi (`rank_bm25`) |
| Doc Parsing | marker-master (PDF, DOCX, PPTX, XLSX, EPUB...) |
| Vietnamese NLP | underthesea |
| Frontend | Vanilla HTML/CSS/JS |

---

## 2. Kiến trúc tổng thể

```
+---------------------------------------------------------------------+
|                        FRONTEND (Browser)                           |
|  index.html (Chat UI)          admin.html (Admin Dashboard)         |
+---------------------+-----------------------------------------------+
                      | HTTP REST API
                      v
+---------------------------------------------------------------------+
|                     FastAPI Backend (app.py)                        |
|                                                                     |
|   +--------------+    +-----------------+    +------------------+  |
|   |  Auth API    |    |   Chat API      |    |   Admin API      |  |
|   | /api/auth/*  |    | /api/chat       |    | /api/admin/*     |  |
|   +--------------+    +--------+--------+    +------------------+  |
|                                |                                    |
|              +-----------------v------------------+                |
|              |        Query Processing Pipeline    |                |
|              |                                     |                |
|              |  1. Vietnamese NLP preprocessing    |                |
|              |  2. Fast-path Rule Router (Layer 0) |                |
|              |  3. LLM Router (Gemini) [fallback]  |                |
|              |  4. Retrieval Plan (parallel)       |                |
|              |     +-- Layer 1: Facts (PostgreSQL) |                |
|              |     +-- Layer 2: KG (PostgreSQL)    |                |
|              |     +-- Layer 3: RAG (ChromaDB)     |                |
|              |     +-- Tools: NextFarm IoT API     |                |
|              |  5. Merge & Rank (RRF)              |                |
|              |  6. Synthesis (Gemini)              |                |
|              |  7. Validation (Guardrail)          |                |
|              +-------------------------------------+                |
+---------------------------------------------------------------------+
                              |
             +----------------+------------------+
             v                v                  v
     +--------------+  +-----------+   +------------------+
     | PostgreSQL   |  | ChromaDB  |   | Gemini API Pool  |
     | - facts      |  | - vectors |   | - Key rotation   |
     | - kg_triples |  | - chunks  |   | - 8 keys max     |
     | - users      |  |           |   | - Rate limit safe|
     | - sessions   |  +-----------+   +------------------+
     | - documents  |
     +--------------+
```

### Kiến trúc 3 Tầng (Tri-Layer RAG)

```
Tang 1 — Structured Fact Store (PostgreSQL)
  +-- So lieu dinh luong cung: lieu phan bon, nang suat, thoi gian sinh truong
  +-- Fail-closed policy: du lieu rui ro PHAI co du dieu kien moi tra ve
  +-- LLM KHONG duoc tu sinh so lieu

Tang 2 — Knowledge Graph (PostgreSQL kg_triples)
  +-- Quan he: giong <-> dat <-> mua vu <-> sau benh <-> ky thuat
  +-- Thay the Neo4j — dung SQL thay Cypher
  +-- LLM KHONG duoc tu suy luan quan he

Tang 3 — Document Store / RAG (ChromaDB)
  +-- Dense retrieval: multilingual-e5-large + ChromaDB
  +-- Sparse retrieval: BM25 Okapi
  +-- Hybrid: RRF (Reciprocal Rank Fusion)
  +-- Fallback khi Tang 1,2 khong tim thay
```

---

## 3. Cấu trúc thư mục

```
e:\vi_no_ngon\chatbot\
|
+-- .env                          # Bien moi truong (API keys, DB config)
+-- requirements.txt              # Python dependencies
+-- START_CHATBOT.bat             # Script khoi dong nhanh (Windows)
+-- Q&E.txt                       # Bo cau hoi/dap thu cong de benchmark
+-- calibration_results.json      # Ket qua calibration nguong retrieval
|
+-- backend/                      # Backend Python
|   +-- app.py                    # FastAPI app — toan bo routes (1869 dong)
|   +-- config.py                 # Cau hinh tap trung (DB, API, Models)
|   +-- monitoring.py             # Thu thap metrics van hanh real-time
|   +-- validator.py              # Guardrail — LLM-as-judge groundedness
|   |
|   +-- router/                   # Bo dinh tuyen cau hoi
|   |   +-- fast_path_router.py   # Rule-based router (0 API call, <5ms)
|   |   +-- query_router.py       # LLM Router + Synthesis (Gemini)
|   |
|   +-- layers/                   # 3 tang du lieu
|   |   +-- layer1_facts.py       # Tang 1: Structured Facts (PostgreSQL)
|   |   +-- layer2_kg.py          # Tang 2: Knowledge Graph (PostgreSQL)
|   |   +-- layer3_docs.py        # Tang 3: Semantic Search (ChromaDB)
|   |
|   +-- retrieval/                # Retrieval nang cao
|   |   +-- retrieval_plan.py     # Multi-source parallel retrieval
|   |   +-- bm25_retrieval.py     # BM25 sparse retrieval
|   |   +-- rrf_merger.py         # Reciprocal Rank Fusion merger
|   |   +-- threshold_calibration.py  # Tu dong calibrate nguong similarity
|   |
|   +-- tools/                    # NextFarm IoT Tool API
|   |   +-- nextfarm_tools.py     # Tool adapters: sensor, device, farm stats
|   |   +-- tool_router.py        # FastAPI router cho /api/tools/*
|   |   +-- device_safety_design.md  # Tai lieu thiet ke an toan thiet bi
|   |
|   +-- ingestion/                # Pipeline nap du lieu
|   |   +-- data_pipeline.py      # Xu ly tai lieu -> chunks -> ChromaDB
|   |   +-- chunker.py            # Structure-aware chunker (Markdown-based)
|   |   +-- ocr_coverage.py       # Kiem tra ty le trang co chu (OCR check)
|   |   +-- rag_audit.py          # Kiem tra chat luong RAG sau ingest
|   |
|   +-- db/                       # Database connectors
|   |   +-- postgres.py           # PostgreSQL — moi thao tac DB (28KB)
|   |   +-- chroma_db.py          # ChromaDB — get_collection helper
|   |
|   +-- iam/                      # Phan quyen truy cap trang trai
|   |   +-- iam.py                # IAM — FarmContext, require_farm_access
|   |
|   +-- preprocessing/            # Tien xu ly NLP
|   |   +-- vietnamese_nlp.py     # Normalize, tach mua vu, dat, giong
|   |
|   +-- utils/                    # Tien ich dung chung
|   |   +-- gemini_client.py      # GeminiKeyManager (rotation pool)
|   |   +-- text_utils.py         # Tien ich xu ly van ban
|   |   +-- versioning.py         # Version tracking
|   |
|   +-- simulator/                # Cong cu kiem thu & Benchmark
|   |   +-- benchmark_evaluator.py   # Danh gia tu dong 260+ cau hoi
|   |   +-- benchmark_builder.py     # Xay dung bo cau hoi benchmark
|   |   +-- farm_generator.py        # Tao du lieu trang trai mo phong
|   |   +-- sensor_simulator.py      # Mo phong cam bien IoT
|   |   +-- fault_injector.py        # Tiem loi de kiem thu do ben
|   |   +-- water_balance.py         # Mo hinh can bang nuoc
|   |   +-- open_meteo_client.py     # Client thoi tiet OpenMeteo
|   |
|   +-- tests/                    # Unit tests
|
+-- frontend/                     # Giao dien web
|   +-- index.html                # Chat UI (nguoi dung)
|   +-- admin.html                # Admin Dashboard (48KB)
|   +-- app.js                    # JavaScript logic chat
|   +-- style.css                 # CSS styling
|
+-- data/                         # Du lieu
|   +-- raw_uploads/              # File tai lieu tho da upload
|   +-- pending_uploads/          # File cho admin xac nhan (case 3,4)
|   +-- parquet/                  # Du lieu parquet
|   +-- page_cache/               # Cache trang tai lieu
|   +-- benchmark_questions.json  # 260+ cau hoi benchmark
|   +-- acceptance_results.json   # Ket qua nghiem thu
|   +-- farms.json                # Du lieu trang trai mau
|
+-- chroma_db/                    # ChromaDB persistent storage (vector index)
+-- marker-master/                # Thu vien doc tai lieu (PDF, DOCX, ...)
+-- .model_cache/                 # Cache model embedding (multilingual-e5-large)
+-- .venv/                        # Python virtual environment
```

---

## 4. Chi tiết từng module

### 4.1 `backend/app.py` — FastAPI Application (1869 dòng)

File chính định nghĩa toàn bộ API endpoints. Bao gồm:

- **Startup event**: Dọn rác `pending_confirmations` hết hạn khi server khởi động
- **CORS middleware**: Cho phép tất cả origins (development mode)
- **Pydantic models**: `RegisterRequest`, `LoginRequest`, `ChatRequest`, `ChatResponse`, `FeedbackRequest`, `UploadConfirmRequest`
- **Tool API Router**: Đăng ký `/api/tools/*` từ `backend.tools.tool_router`
- **Title**: "Chatbot Nông Nghiệp AI — NextFarm v2.2"

**ChatResponse** trả về:
```json
{
  "session_id": "...",
  "answer": "...",
  "source": "...",
  "is_partial_match": false,
  "question_type": "...",
  "layer_used": "...",
  "clarification_needed": false,
  "tool_sources": [],
  "retrieval_sources": [],
  "freshness_warnings": [],
  "requires_clarification": false
}
```

### 4.2 `backend/router/fast_path_router.py` — Fast-Path Router (Layer 0)

**Mục đích**: Rule-based routing cực nhanh, **0 API call**, **< 5ms**

**Cơ chế**:
1. Dùng regex pattern matching
2. Nhận dạng intent trực tiếp từ từ khóa
3. Trả kết quả ngay nếu khớp — bỏ qua Gemini hoàn toàn
4. Trả `None` nếu không chắc → fallback sang Gemini

**Phân loại intent**:

| Intent | Ví dụ từ khóa |
|---|---|
| `định_lượng` | liều lượng, kg/ha, bón, năng suất tấn/ha, mật độ cây/m2... |
| `phù_hợp/quan_hệ` | giống nào phù hợp, chọn giống, sâu bệnh trên, phòng trừ... |
| `diễn_giải` | tại sao, vì sao, cách bón, quy trình, kỹ thuật canh tác... |
| `ngoài_phạm_vi` | bất động sản, chứng khoán, bitcoin, du lịch, phim... |
| `chào_hỏi` | xin chào, hello, chào buổi sáng... |

### 4.3 `backend/router/query_router.py` — LLM Router + Synthesis

**Hàm chính**:
- `route_question_with_fast_path(question, history)` — Thử fast-path trước, fallback Gemini
- `route_question(question, history)` — Gọi Gemini phân loại
- `synthesize_answer(question, data, source)` — Tổng hợp câu trả lời từ dữ liệu

**ROUTER_PROMPT** trích xuất:
```json
{
  "question_type": "định_lượng | phù_hợp/quan_hệ | diễn_giải | ngoài_phạm_vi | cần_làm_rõ",
  "crop": "tên cây trồng hoặc null",
  "season": "Đông Xuân | Hè Thu | Mùa | null",
  "soil_type": "phù sa | phèn nhẹ | phèn trung bình | phèn nặng | mặn | đất đỏ | null",
  "growth_stage": "mạ | đẻ_nhánh | làm_đòng | trổ_bông | chín | null",
  "variety": "tên giống nếu có hoặc null",
  "topic_keywords": ["từ khóa chính"],
  "confidence": "high | medium | low",
  "clarification_question": "câu hỏi lại hoặc null"
}
```

**Models sử dụng**:
- Router: `GEMINI_ROUTER_MODEL` (mặc định: gemini-3.1-flash-lite — nhanh)
- Synthesis: `GEMINI_SYNTHESIS_MODEL` (mặc định: gemini-3.6-flash — cân bằng)
- Fallback: `GEMINI_FALLBACK_MODEL` (khi bị rate-limit)

### 4.4 `backend/layers/layer1_facts.py` — Tầng 1: Structured Fact Store

**Nguyên tắc bất biến**: Số liệu định lượng CHỈ đến từ đây. LLM không được tự sinh.

**Fail-Closed Policy** (dữ liệu rủi ro cao — `HIGH_RISK_KEYWORDS`):
```
liều, liều lượng, lượng, nồng độ, tưới, phân, thuốc, bón, xịt, phụn...
```
- Bắt buộc có ít nhất 1 trong: `season`, `soil_type`, `growth_stage`
- Nếu thiếu → trả `found=False, requires_clarification=True`
- Không trả số liệu chung cho dữ liệu rủi ro

**Hàm chính**:
- `get_fact(attribute, crop, season, soil_type, growth_stage)` → tra cứu fact
- `get_rice_variety(variety_name)` → thông tin giống lúa
- `get_all_rice_varieties()` → danh sách tất cả giống

**Return structure**:
```python
{
    "found": bool,
    "is_partial_match": bool,    # True nếu khớp một phần điều kiện
    "requires_clarification": bool,  # True nếu fail-closed thiếu điều kiện
    "results": [...],            # Danh sách fact khớp
    "warning": str | None        # Cảnh báo partial match
}
```

### 4.5 `backend/layers/layer2_kg.py` — Tầng 2: Knowledge Graph

**Lưu trữ**: Bảng `kg_triples` trong PostgreSQL — thay thế Neo4j

**Hàm chính**:
- `find_suitable_varieties(soil_type, season)` → tìm giống phù hợp
- `find_pest_info(crop, pest_name)` → thông tin sâu bệnh
- `find_technique_info(crop, technique)` → thông tin kỹ thuật

**Schema kg_triples** (ví dụ):
```
("OM5451",  "PHÙ_HỢP_VỚI", "phèn nhẹ",    "LoạiĐất", chunk_123, 0.95)
("OM5451",  "PHÙ_HỢP_VỚI", "Đông Xuân",   "MùaVụ",   chunk_456, 0.90)
("Rầy nâu", "GÂY_HẠI_CHO", "lúa",         "CâyTrồng",chunk_789, 1.00)
```

### 4.6 `backend/layers/layer3_docs.py` — Tầng 3: RAG / Document Store

**Embedding model**: `intfloat/multilingual-e5-large` (lazy load lần đầu, cache `.model_cache/`)

**Cơ chế retrieval**:
- Dense: ChromaDB cosine similarity
- Prefix e5: `query: <text>` cho câu hỏi, `passage: <text>` cho đoạn văn
- Hybrid: kết hợp với BM25 qua RRF

**Hàm chính**:
- `semantic_search(query, crop, season, soil_type, top_k)` → dense retrieval
- `hybrid_search(query, ...)` → dense + BM25 + RRF
- `store_chunk(chunk_id, text, metadata)` → lưu chunk vào ChromaDB
- `embed_query(text)` → embedding câu hỏi
- `embed_passage(text)` → embedding đoạn văn

### 4.7 `backend/retrieval/retrieval_plan.py` — Multi-Source Parallel Retrieval

**Cơ chế**: asyncio.gather gọi song song 4 nguồn cùng lúc

```python
sources = await asyncio.gather(
    _fetch_facts(attribute, crop, season, soil_type, growth_stage),  # Layer 1
    _fetch_kg(soil_type, season, pest_name, technique),               # Layer 2
    _fetch_docs(query, crop, season, soil_type),                      # Layer 3
    _fetch_tools(farm_context, query_intent),                         # IoT Tools
)
result = merge_results(sources)  # RRF merge + dedup
```

**Priority** (thấp = cao hơn):
```
Facts (0) > KG (1) > Tools (2) > Docs (3)
```

**RetrievalPlanResult** trả về:
```python
{
    "found": bool,
    "sources": [RetrievalSource, ...],
    "merged_data": str,           # Dữ liệu đã merge thành text
    "merged_source_info": str,    # Nguồn gốc
    "warnings": [str, ...],       # Cảnh báo (stale, partial match...)
    "primary_layer": str,         # Layer chính được dùng
    "sources_used": [str, ...],   # Danh sách sources đã dùng
    "tool_calls": [...],          # Tool calls đã thực hiện
    "requires_clarification": bool
}
```

### 4.8 `backend/retrieval/bm25_retrieval.py` — BM25 Sparse Retrieval

**Đặc biệt hữu ích cho**: tên thuốc BVTV, mã liều lượng, tên giống mà embedding hay nhầm/bỏ sót

- **Lazy build**: Index được build từ ChromaDB lần đầu tiên gọi
- **Auto-invalidation**: Tự rebuild khi chunk count thay đổi
- **Cache in-memory**: Thread-safe với `threading.Lock()`
- **Tokenizer Việt**: regex `\b[\w]{2,}\b`, lowercase, loại token < 2 ký tự

### 4.9 `backend/retrieval/rrf_merger.py` — Reciprocal Rank Fusion

Công thức RRF chuẩn:
```
score(d) = Σ 1 / (k + rank_i(d))
```
- `k = 60` (hằng số RRF chuẩn)
- Merge dense scores từ ChromaDB + sparse scores từ BM25

### 4.10 `backend/tools/nextfarm_tools.py` — NextFarm IoT Tools

**Freshness Policy** (ngưỡng cố định):
```
fresh   : age_seconds <= 600   (10 phút)
stale   : 600 < age <= 3600    (10 phút — 1 giờ)
missing : age > 3600 hoặc không có dữ liệu
```

**Tools chính**:

| Tool | Mô tả |
|---|---|
| `get_latest_sensor(farm_ctx, sensor_type, zone_id)` | Đọc cảm biến (nhiệt độ, độ ẩm, pH, EC...) |
| `get_device_status(farm_ctx, device_id)` | Trạng thái thiết bị (bơm, van, máy phun...) |
| `get_farm_stats(farm_ctx)` | Tổng quan trang trại |
| `get_weather_forecast(farm_ctx, days)` | Dự báo thời tiết từ OpenMeteo |

**Mỗi giá trị trả về kèm**:
```python
{
    "value": ...,
    "unit": "°C | % | pH | ...",
    "measured_at": datetime,
    "age_seconds": int,
    "quality_flag": "fresh | stale | missing",
    "age_human": "2 phút | 45 phút | ...",
    "freshness_warning": str | None   # Cảnh báo nếu stale/missing
}
```

**Lưu ý quan trọng**:
- Giá trị `stale/missing` PHẢI được cảnh báo rõ trong câu trả lời
- LLM KHÔNG được tự sinh/suy luận `farm_id`
- PoC hiện tại: dữ liệu mock. Production: gọi NextFarm REST/gRPC API thực.

### 4.11 `backend/tools/tool_router.py` — Tool API Router

FastAPI APIRouter với prefix `/api/tools`, đăng ký vào app chính.
Cho phép gọi trực tiếp từ frontend hoặc debug tool.

### 4.12 `backend/iam/iam.py` — Farm IAM (Identity & Access Management)

**FarmContext** dataclass:
```python
@dataclass
class FarmContext:
    user_id: str
    username: str
    allowed_farm_ids: list[str]   # Danh sách farm_id được phép
    customer_id: Optional[str] = None
    role: str = "user"            # "user" | "admin"
    farm_id: Optional[str] = None  # farm_id đang request
    zone_id: Optional[str] = None  # zone_id trong farm
```

**Mock permissions (PoC)**:
```python
{
    "admin":     ["*"],                        # admin = mọi farm
    "demo_user": ["farm_001", "farm_002"],
    "farmer_a":  ["farm_001"],
    "farmer_b":  ["farm_003", "farm_004"],
}
```

**Nguyên tắc cứng**: Cross-farm unauthorized access = **0 trường hợp** được phép.

### 4.13 `backend/utils/gemini_client.py` — GeminiKeyManager

**Pool quản lý 8 API Keys với xoay vòng tự động**:

```
Key pool: [key_1, key_2, key_3, key_4, ...]
             |        |        |
         active  rate_limit  invalid
             |
         cooldown 10s → active lại
```

**Phân loại lỗi**:

| Loại | Keywords nhận dạng | Hành động |
|---|---|---|
| `rate_limit` | 429, RESOURCE_EXHAUSTED, quota | Cooldown 10s, thử key tiếp |
| `invalid_key` | 401, 403, API_KEY_INVALID | Đánh dấu vĩnh viễn, bỏ qua |
| `server_error` | 500, 502, 503, INTERNAL | Thử key tiếp |
| `not_found` | 404, model không tồn tại | Log + báo lỗi |

**Exception**: `AllKeysExhaustedError` khi tất cả key đều không khả dụng.

### 4.14 `backend/validator.py` — Guardrail (LLM-as-Judge)

**Cơ chế groundedness check**:
```
Input: câu hỏi + context (ground truth) + câu trả lời chatbot
Output: { grounded, hallucination_detected, confidence, reason }

grounded=True  → Câu trả lời OK, trả về người dùng
grounded=False → Retry với refined retrieval
                 Hết retry → ABSTAIN (câu từ chối cố định)
```

**ABSTAIN_ANSWER**:
> "Tôi chưa tìm thấy đủ căn cứ trong kho dữ liệu nông nghiệp để trả lời chắc chắn câu hỏi này. Vui lòng hỏi cụ thể hơn (loại cây, mùa vụ, loại đất) hoặc liên hệ chuyên gia nông nghiệp địa phương."

**Fail-safe cứng**: JSON hỏng / exception → luôn coi là `invalid`, KHÔNG bao giờ mặc định pass.

### 4.15 `backend/monitoring.py` — Monitoring & Metrics

**Thu thập in-memory (reset khi restart server)**:

| Metric | Mô tả |
|---|---|
| `_tool_metrics` | call_count, success, error, latency/p95 từng tool |
| `_cross_farm_denies` | Log IAM deny chi tiết |
| `_stale_count/_fresh_count/_missing_count` | Sensor quality counters |

**Gemini Cost Tracking**:
```python
GEMINI_PRICING_PER_1M = {
    "gemini-3.1-flash-lite": (0.075, 0.30),   # (input, output) USD/1M tokens
    "gemini-3.6-flash":      (0.10,  0.40),
}
```

**Static data** (đọc từ file):
- `calibration_results.json` → Recall@K
- `data/acceptance_results.json` → Benchmark status

**Endpoint**: `GET /api/monitoring/stats?username=admin`

### 4.16 `backend/ingestion/data_pipeline.py` — Data Pipeline

**Định dạng hỗ trợ**: PDF, DOCX, DOC, PPTX, PPT, XLSX, XLS, EPUB, HTML, HTM, TXT, MD, JSON

**marker-master**: OCR đã tắt (`disable_ocr=True`) — chỉ lấy chữ kỹ thuật số. Trang scan/ảnh thuần túy bị bỏ qua.

**5 Case xử lý upload**:

| Case | Tên | Hành động |
|---|---|---|
| 1 | `process_new` | Tài liệu mới → xử lý bình thường |
| 2 | `auto_continue` | Nội dung có, dở dang → ingest lại từ đầu |
| 3 | `confirm_duplicate_content` | Nội dung trùng, tên khác → HTTP 409, hỏi admin |
| 4 | `confirm_content_changed` | Cùng tên, nội dung đổi → HTTP 409, hỏi admin |
| 5 | `already_complete` | Tên + nội dung đã có → bỏ qua (HTTP 200) |

**Case 4 — Safe replace protocol**:
```
1. Ingest bản MỚI trước
2. Chỉ khi thành công → xóa chunk CŨ khỏi ChromaDB
3. Đánh dấu doc cũ = "superseded" trong PostgreSQL
4. Nếu ingest mới partial_failure → GIỮ NGUYÊN bản cũ
```

---

## 5. Cơ sở dữ liệu

### 5.1 PostgreSQL — Schema đầy đủ

```sql
-- Người dùng
CREATE TABLE users (
    user_id       SERIAL PRIMARY KEY,
    username      VARCHAR UNIQUE NOT NULL,
    password_hash VARCHAR NOT NULL,           -- SHA-256
    role          VARCHAR DEFAULT 'user',     -- 'user' | 'admin'
    is_blocked    BOOLEAN DEFAULT FALSE,
    created_at    TIMESTAMP DEFAULT NOW()
);

-- Lịch sử chat
CREATE TABLE chat_sessions (
    session_id  VARCHAR PRIMARY KEY,
    username    VARCHAR,
    created_at  TIMESTAMP DEFAULT NOW()
);
CREATE TABLE chat_messages (
    id          SERIAL PRIMARY KEY,
    session_id  VARCHAR REFERENCES chat_sessions(session_id),
    role        VARCHAR,    -- 'user' | 'assistant'
    content     TEXT,
    created_at  TIMESTAMP DEFAULT NOW()
);

-- Tang 1 — Structured Facts
CREATE TABLE facts (
    fact_id         SERIAL PRIMARY KEY,
    crop            VARCHAR,
    attribute       VARCHAR,     -- 'liều phân đạm', 'năng suất'...
    value           NUMERIC,
    unit            VARCHAR,
    season          VARCHAR,     -- 'Đông Xuân' | 'Hè Thu' | 'Mùa'
    soil_type       VARCHAR,
    growth_stage    VARCHAR,
    condition_note  TEXT,
    fact_version    VARCHAR DEFAULT '1.0',
    source_chunk_id VARCHAR
);

-- Giống lúa (quan hệ riêng)
CREATE TABLE rice_varieties (
    variety_id      SERIAL PRIMARY KEY,
    variety_name    VARCHAR UNIQUE,
    duration_days   INTEGER,
    yield_potential VARCHAR,
    resistant_pests TEXT[],
    suitable_soil   TEXT[]
);

-- Tang 2 — Knowledge Graph
CREATE TABLE kg_triples (
    triple_id     SERIAL PRIMARY KEY,
    entity_a      VARCHAR,          -- VD: "OM5451"
    relationship  VARCHAR,          -- VD: "PHÙ_HỢP_VỚI"
    entity_b      VARCHAR,          -- VD: "phèn nhẹ"
    entity_b_type VARCHAR,          -- "LoạiĐất" | "MùaVụ" | "SâuBệnh"
    source_chunk_id VARCHAR,
    confidence    FLOAT DEFAULT 1.0
);

-- Tài liệu đã ingest
CREATE TABLE documents (
    doc_id        VARCHAR PRIMARY KEY,
    filename      VARCHAR,
    content_hash  VARCHAR UNIQUE,
    status        VARCHAR,         -- 'processing'|'success'|'failed'|'superseded'
    chunk_count   INTEGER,
    created_at    TIMESTAMP DEFAULT NOW()
);
CREATE TABLE document_filenames (   -- Alias nhiều tên cho 1 doc
    id       SERIAL PRIMARY KEY,
    doc_id   VARCHAR REFERENCES documents(doc_id),
    filename VARCHAR
);

-- Upload chờ xác nhận admin
CREATE TABLE pending_confirmations (
    temp_id      VARCHAR PRIMARY KEY,
    action_type  VARCHAR,     -- 'confirm_duplicate_content' | 'confirm_content_changed'
    context_json JSONB,
    expires_at   TIMESTAMP    -- hết hạn sau 24h
);

-- Feedback người dùng
CREATE TABLE feedbacks (
    id            SERIAL PRIMARY KEY,
    session_id    VARCHAR,
    question      TEXT,
    answer        TEXT,
    rating        INTEGER,   -- 1 (tốt) | -1 (không tốt)
    feedback_text TEXT,
    created_at    TIMESTAMP DEFAULT NOW()
);
```

### 5.2 ChromaDB — Collection `nongnghiep_chunks`

**Mỗi document (chunk) có**:
- `id`: chunk_id duy nhất
- `embedding`: vector 1024 chiều (multilingual-e5-large)
- `document`: nội dung text của chunk
- `metadata`:
```python
{
    "source_document_id": str,   # doc_id
    "source_title": str,         # tên tài liệu
    "chunk_index": int,          # số thứ tự chunk trong doc
    "heading_path": str,         # "Chương 2 > Phần 3.1 > ..."
    "chunk_type": str,           # "text" | "table" | "list"
    "crop": str,                 # loại cây trồng liên quan (nếu có)
    "page_number": int,          # số trang trong tài liệu gốc
}
```

---

## 6. Luồng xử lý câu hỏi

```
Người dùng gửi câu hỏi qua POST /api/chat
        |
        v
[BƯỚC 1] Vietnamese NLP Preprocessing
   +-- normalize_input()       : chuẩn hóa Unicode, xử lý typo
   +-- extract_season()        : nhận diện "vụ Đông Xuân", "HT", "mùa"...
   +-- extract_soil_type()     : nhận diện "đất phèn", "đất mặn"...
   +-- extract_variety_name()  : nhận diện "giống OM5451", "IR50404"...
        |
        v
[BƯỚC 2] Fast-Path Rule Router (< 5ms, 0 API call)
   +-- Khớp intent rõ ràng → routing ngay không qua Gemini
   +-- Không khớp → tiếp tục bước 3
        |
        v
[BƯỚC 3] LLM Router (Gemini Flash-Lite)
   +-- Gọi Gemini phân loại intent, trích xuất entities
   |
   +-- question_type == "ngoài_phạm_vi" -----> Từ chối lịch sự
   +-- question_type == "cần_làm_rõ"    -----> Trả về clarification_question
   |
   v
[BƯỚC 4] Retrieval Plan (asyncio.gather — song song)
   +-- _fetch_facts()   → Layer 1: get_fact() từ PostgreSQL
   +-- _fetch_kg()      → Layer 2: kg_triples từ PostgreSQL
   +-- _fetch_docs()    → Layer 3: hybrid_search() ChromaDB + BM25 + RRF
   +-- _fetch_tools()   → NextFarm IoT (nếu có farm_context & farm_id)
        |
        v
[BƯỚC 5] Merge & Rank Results
   +-- RRF merge scores từ nhiều nguồn
   +-- Dedup theo content similarity
   +-- Ưu tiên: Facts(0) > KG(1) > Tools(2) > Docs(3)
        |
        v
[BƯỚC 6] Synthesis (Gemini Flash)
   +-- synthesize_answer(question, merged_data, source)
   +-- Chỉ dùng dữ liệu hệ thống — không hallucinate
        |
        v
[BƯỚC 7] Validation / Guardrail
   +-- validate_answer(question, context, answer)
   +-- grounded=True  → OK, qua bước 8
   +-- grounded=False → Retry với refined query
                     → Hết retry → ABSTAIN_ANSWER
        |
        v
[BƯỚC 8] Lưu lịch sử chat PostgreSQL
   +-- save_chat_message(session_id, "user", question)
   +-- save_chat_message(session_id, "assistant", answer)
        |
        v
Trả về ChatResponse cho Frontend
```

---

## 7. Hệ thống IAM & Bảo mật

### 7.1 Xác thực người dùng

| Endpoint | Mô tả |
|---|---|
| `POST /api/auth/register` | Tạo tài khoản user thường |
| `POST /api/auth/login` | Đăng nhập, trả token |
| `GET /api/auth/me` | Xem thông tin tài khoản |

**Token format**: `token_{username}_{user_id}` (bearer token đơn giản, PoC)

**Password**: SHA-256 hash, không lưu plaintext

**Admin mặc định**: username=`admin`, password=`admin`
- Được tạo khi init_db
- Không thể đăng ký thêm account tên "admin"
- Không thể bị block hoặc xóa

### 7.2 Farm Authorization Flow

```
Request chat với farm_id (truyền từ frontend)
        |
        v
build_farm_context(username, farm_id, zone_id)
        |
        v
resolve_allowed_farm_ids(username, role)
        |
        v
check_farm_access(farm_ctx, requested_farm_id)
        |
   +-----------+
   |           |
allowed?     denied
   |           |
   v           v
  OK      403 Forbidden
         (log IAM deny,
          không giải thích lý do chi tiết)
```

---

## 8. Pipeline nạp dữ liệu

### 8.1 Upload qua Admin Dashboard

**Truy cập**: `http://localhost:8000/admin.html` → tab "Nạp dữ liệu"

**Luồng xử lý** (Case 1 — tài liệu mới):
```
Admin upload file
        |
        v
1. Tính content_hash (SHA-256 của bytes)
2. Check trạng thái với check_upload_status()
3. Lưu file vào data/raw_uploads/
4. marker-master đọc file → Markdown text
5. OCR coverage check (phát hiện trang scan, trang trắng)
6. StructureAwareChunker: chunk theo cấu trúc Markdown/heading
7. multilingual-e5-large: embed từng chunk
8. Lưu vào ChromaDB (vector + metadata)
9. Lưu metadata vào PostgreSQL documents
10. Cập nhật status = "success"
```

**Xử lý Case 3 & 4** (cần admin xác nhận):
```
1. Upload nhận HTTP 409 với temp_id
2. File tạm lưu vào data/pending_uploads/{temp_id}.pdf
3. pending_confirmation lưu vào PostgreSQL (hết hạn 24h)
4. Admin xác nhận qua POST /api/admin/upload-data/confirm:
   - "accept" → xử lý tiếp (merge alias hoặc replace doc)
   - "reject" → xóa file tạm, không thay đổi gì
```

### 8.2 Script convert Parquet

```bash
python convert_parquet.py
```

Đọc file `.parquet` từ `data/parquet/`, chuyển sang JSON và nạp vào hệ thống.

### 8.3 Kiểm tra sau ingest

```bash
python -m backend.ingestion.rag_audit
```

Kiểm tra chất lượng RAG: coverage, chunk count, embedding health.

---

## 9. Benchmark & Đánh giá

### 9.1 Bộ câu hỏi benchmark

| File | Mô tả |
|---|---|
| `data/benchmark_questions.json` | 260+ câu hỏi với ground truth, metadata phân loại |
| `Q&E.txt` | Bộ câu hỏi/đáp thủ công (định dạng: `N,câu hỏi: ... trả lời: ...`) |

### 9.2 Chạy Benchmark

```powershell
# Kích hoạt virtualenv
cd e:\vi_no_ngon\chatbot
.venv\Scripts\activate

# Benchmark schema check nhanh (CI, không gọi Gemini)
python -m backend.simulator.benchmark_evaluator --schema-check-only

# Benchmark đầy đủ (gọi Gemini judge)
python -m backend.simulator.benchmark_evaluator `
    --benchmark data/benchmark_questions.json `
    --output data/acceptance_results.json

# Benchmark tùy chỉnh output
python -m backend.simulator.benchmark_evaluator `
    --benchmark data/benchmark_questions.json `
    --output data/my_test_results.json
```

### 9.3 Tiêu chí đánh giá — LLM-as-Judge

**JUDGE_PROMPT** dùng Gemini chấm 2 tiêu chí:

```
factual_score  (0-100): Độ chính xác số liệu, tên gọi, thông số kỹ thuật
semantic_score (0-100): Đúng trọng tâm, đủ ý, không lạc đề
```

**Xếp loại**:

| Điểm | Xếp loại |
|---|---|
| >= 90 | Xuất sắc |
| >= 80 | Tốt |
| >= 70 | Khá |
| >= 50 | Chưa đạt |
| < 50 | Kém |

### 9.4 Benchmark qua Admin Dashboard

Endpoint `POST /api/benchmark/run` chạy benchmark từ `Q&E.txt`:
- Gọi full pipeline cho từng câu hỏi
- Chấm điểm bằng Gemini judge
- Lưu kết quả vào `benchmark_results.json`
- Xem kết quả tại tab Benchmark trong `admin.html`

### 9.5 Calibration ngưỡng Retrieval

```powershell
python -m backend.retrieval.threshold_calibration
```

Tự động tìm ngưỡng similarity tối ưu (Recall@K), lưu vào `calibration_results.json`.
Kết quả được hiển thị trong tab Monitoring.

---

## 10. Monitoring & Giám sát

### 10.1 Admin Dashboard

Truy cập tab **"Monitoring"** tại `http://localhost:8000/admin.html`:

**In-memory metrics** (từ khi server khởi động):
- Tool call stats: total, success rate, error rate, avg/p95 latency
- IAM deny count và log chi tiết
- Sensor quality: fresh/stale/missing counts
- Gemini token usage và cost estimate (USD)

**Static metrics** (từ file):
- Recall@K từ `calibration_results.json`
- Benchmark status từ `data/acceptance_results.json`

### 10.2 Gemini Key Pool Monitor

```
GET /api/admin/key-status?username=admin
```

Response ví dụ:
```json
{
  "summary": {
    "total_keys": 4,
    "active": 3,
    "rate_limited": 1,
    "invalid": 0,
    "pool_healthy": true
  },
  "keys": [
    {
      "key_index": 1,
      "key_preview": "ab12cd",
      "status": "active",
      "cooldown_remaining_seconds": 0,
      "total_calls": 145,
      "total_errors": 2,
      "rotations_caused": 1,
      "is_current": true
    }
  ]
}
```

---

## 11. Cấu hình .env

Tạo/chỉnh sửa file `.env` tại `e:\vi_no_ngon\chatbot\.env`:

```env
# ============================================================
# GEMINI API KEYS — BẮT BUỘC điền ít nhất 1 key hợp lệ
# Pool tối đa 8 keys, xoay vòng tự động khi bị rate-limit
# ============================================================
GEMINI_API_KEY_1=AIza...your_key_1_here
GEMINI_API_KEY_2=AIza...your_key_2_here
GEMINI_API_KEY_3=AIza...your_key_3_here
GEMINI_API_KEY_4=AIza...your_key_4_here
# GEMINI_API_KEY_5=
# GEMINI_API_KEY_6=
# GEMINI_API_KEY_7=
# GEMINI_API_KEY_8=

# ============================================================
# GEMINI MODELS — Có thể giữ mặc định
# ============================================================
GEMINI_ROUTER_MODEL=gemini-2.0-flash-lite
GEMINI_SYNTHESIS_MODEL=gemini-2.0-flash
GEMINI_JUDGE_MODEL=gemini-2.0-flash
GEMINI_FALLBACK_MODEL=gemini-2.0-flash-lite

# ============================================================
# POSTGRESQL — BẮT BUỘC điền đúng password
# ============================================================
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_postgres_password_here
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=chatbot_nongnghiep

# ============================================================
# EMBEDDING MODEL — Giữ mặc định (thay đổi cần rebuild index)
# ============================================================
EMBEDDING_MODEL=intfloat/multilingual-e5-large

# ============================================================
# APP CONFIG
# ============================================================
APP_HOST=0.0.0.0
APP_PORT=8000
DEBUG=true
```

**Lấy Gemini API Key miễn phí**: https://aistudio.google.com/app/apikey

---

## 12. Hướng dẫn cài đặt & Chạy hệ thống

### 12.1 Yêu cầu hệ thống

| Thành phần | Yêu cầu |
|---|---|
| OS | Windows 10/11 64-bit (hoặc Ubuntu 20.04+) |
| Python | 3.10, 3.11, hoặc 3.12 |
| RAM | 8 GB tối thiểu (16 GB khuyến nghị) |
| Disk | 5 GB trống (model ~1.5 GB + ChromaDB + dependencies) |
| PostgreSQL | Version 14, 15, hoặc 16 |
| Internet | Cần thiết để gọi Gemini API |

---

### 12.2 Cài đặt lần đầu (Step-by-step)

#### Bước 1: Cài PostgreSQL

1. Tải tại: https://www.postgresql.org/download/windows/
2. Cài đặt, đặt mật khẩu cho user `postgres`
3. Sau khi cài, tạo database:

```sql
-- Mở pgAdmin hoặc psql
CREATE DATABASE chatbot_nongnghiep;
```

Hoặc qua command line:
```powershell
psql -U postgres -c "CREATE DATABASE chatbot_nongnghiep;"
```

#### Bước 2: Tạo Virtual Environment

```powershell
cd e:\vi_no_ngon\chatbot

# Tạo venv
python -m venv .venv

# Kích hoạt
.venv\Scripts\activate

# Kiểm tra Python version
python --version  # Phải >= 3.10
```

#### Bước 3: Cài Python dependencies

```powershell
# Nâng cấp pip trước
python -m pip install --upgrade pip

# Cài toàn bộ dependencies
pip install -r requirements.txt
```

> **Lưu ý**: `torch` (~2GB) và `sentence-transformers` (~500MB) mất 5-15 phút tải.
> Nếu mạng chậm, có thể cài riêng: `pip install torch --index-url https://download.pytorch.org/whl/cpu`

#### Bước 4: Tạo và điền file .env

```powershell
# Tạo file .env (nếu chưa có)
Copy-Item .env.example .env  # nếu có file mẫu
# Hoặc tạo mới và mở bằng Notepad:
notepad .env
```

Điền đầy đủ theo hướng dẫn Mục 11.

#### Bước 5: Khởi tạo Database

```powershell
# Tạo tất cả tables và dữ liệu ban đầu
python -c "from backend.db.postgres import init_db; init_db(); print('Database initialized!')"
```

Output mong đợi:
```
Database initialized!
```

Kiểm tra kết quả trong pgAdmin: database `chatbot_nongnghiep` phải có các tables: `users`, `facts`, `kg_triples`, `documents`, `chat_sessions`, `chat_messages`, `feedbacks`, `pending_confirmations`.

#### Bước 6: Kiểm tra cấu hình

```powershell
python backend/config.py
```

Output mong đợi:
```
OK Cau hinh OK!
  Gemini Keys : 4 key(s) da nap (toi da 8)
  Router Model   : gemini-2.0-flash-lite
  Synthesis Model: gemini-2.0-flash
  Postgres       : localhost:5432/chatbot_nongnghiep
  ChromaDB       : e:\vi_no_ngon\chatbot\chroma_db
  Embedding      : intfloat/multilingual-e5-large
```

Nếu thấy lỗi đỏ → sửa theo hướng dẫn trong mục 14 Troubleshooting.

---

### 12.3 Khởi động server

#### Cách 1: File BAT (khuyến nghị cho Windows)

```
Double-click: START_CHATBOT.bat
```

Script tự động:
1. `cd /d e:\vi_no_ngon\chatbot`
2. `.venv\Scripts\activate`
3. `set PYTHONIOENCODING=utf-8`
4. `python -m uvicorn backend.app:app --reload --port 8000`

#### Cách 2: PowerShell thủ công

```powershell
cd e:\vi_no_ngon\chatbot
.venv\Scripts\activate
$env:PYTHONIOENCODING = "utf-8"
python -m uvicorn backend.app:app --reload --port 8000
```

#### Cách 3: Production mode (không reload)

```powershell
cd e:\vi_no_ngon\chatbot
.venv\Scripts\activate
python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --workers 1
```

> **QUAN TRỌNG**: Luôn dùng `--workers 1` vì:
> - ChromaDB in-memory không shared giữa workers
> - BM25 index in-memory không shared
> - Key rotation state không shared

#### Log khởi động bình thường:

```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO: startup_cleanup - Startup OK
INFO: Tool API Router đã đăng ký (/api/tools/*)
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

---

### 12.4 Truy cập hệ thống

| URL | Mô tả | Quyền |
|---|---|---|
| `http://localhost:8000` | Chat UI | Mọi người |
| `http://localhost:8000/admin.html` | Admin Dashboard | Admin only |
| `http://localhost:8000/docs` | Swagger API UI | Dev |
| `http://localhost:8000/redoc` | ReDoc API Docs | Dev |

**Tài khoản mặc định**:
- Admin: `admin` / `admin`
- Tạo user mới: đăng ký qua giao diện hoặc `POST /api/auth/register`

---

### 12.5 Nạp dữ liệu nông nghiệp

1. Đăng nhập Admin Dashboard: `http://localhost:8000/admin.html`
2. Tab **"Nạp dữ liệu"** → chọn file PDF/DOCX/TXT/...
3. Click **"Upload"** → chờ xử lý (thời gian tùy kích thước file)
4. Xem kết quả: số chunks đã tạo, trạng thái ingest

**Lưu ý lần đầu nạp dữ liệu**:
- Model embedding (`multilingual-e5-large`) sẽ tự download lần đầu (~1.5 GB, mất vài phút)
- Sau đó cache vào `.model_cache/` — lần sau không cần tải lại

---

### 12.6 Chạy Benchmark (tùy chọn)

```powershell
cd e:\vi_no_ngon\chatbot
.venv\Scripts\activate

# Nhanh — không gọi API
python -m backend.simulator.benchmark_evaluator --schema-check-only

# Đầy đủ — tốn Gemini API quota
python -m backend.simulator.benchmark_evaluator `
    --benchmark data/benchmark_questions.json `
    --output data/acceptance_results.json
```

---

## 13. Danh sách API Endpoints

### Auth

| Method | Endpoint | Body / Params | Mô tả |
|---|---|---|---|
| POST | `/api/auth/register` | `{username, password, confirm_password}` | Đăng ký tài khoản |
| POST | `/api/auth/login` | `{username, password}` | Đăng nhập |
| GET | `/api/auth/me` | `?username=<user>` | Thông tin user |

### Chat

| Method | Endpoint | Body / Params | Mô tả |
|---|---|---|---|
| POST | `/api/chat` | `{session_id, username, question, conversation_history, farm_id, zone_id}` | Gửi câu hỏi |
| POST | `/api/feedback` | `{session_id, question, answer, rating, feedback_text}` | Feedback 👍/👎 |
| GET | `/api/sessions` | `?username=<user>` | Danh sách sessions |
| GET | `/api/sessions/{id}/messages` | — | Lịch sử tin nhắn |
| DELETE | `/api/sessions/{id}` | `?username=<user>` | Xóa session |

### Admin — Quản lý Users

| Method | Endpoint | Mô tả |
|---|---|---|
| GET | `/api/admin/users?username=admin` | Danh sách người dùng |
| POST | `/api/admin/users/{id}/block?username=admin` | Block/unblock user |
| DELETE | `/api/admin/users/{id}?username=admin` | Xóa user |

### Admin — Quản lý Dữ liệu

| Method | Endpoint | Mô tả |
|---|---|---|
| POST | `/api/admin/upload-data?username=admin` | Upload tài liệu (multipart/form-data) |
| POST | `/api/admin/upload-data/confirm?username=admin` | Xác nhận case 3/4 (`{temp_id, decision}`) |

### Admin — Monitoring

| Method | Endpoint | Mô tả |
|---|---|---|
| GET | `/api/admin/key-status?username=admin` | Trạng thái Gemini key pool |
| GET | `/api/monitoring/stats?username=admin` | Metrics vận hành |

### Admin — Benchmark

| Method | Endpoint | Mô tả |
|---|---|---|
| POST | `/api/benchmark/run?username=admin` | Chạy benchmark từ Q&E.txt |
| GET | `/api/benchmark/results?username=admin` | Xem kết quả |

### NextFarm IoT Tools

| Method | Endpoint | Mô tả |
|---|---|---|
| GET | `/api/tools/sensor/{farm_id}/{sensor_type}` | Đọc cảm biến |
| GET | `/api/tools/device/{farm_id}/{device_id}` | Trạng thái thiết bị |
| GET | `/api/tools/farm/{farm_id}/stats` | Tổng quan trang trại |

---

## 14. Troubleshooting

### Lỗi: GEMINI_API_KEY không hợp lệ

**Triệu chứng**: `AllKeysExhaustedError`, 401, hoặc 403 trong log

**Kiểm tra**:
1. `.env` có dòng `GEMINI_API_KEY_1=AIza...` (không có khoảng trắng)
2. Key không phải `your_key_here`
3. Key còn hạn và chưa hết quota

**Lấy key mới**: https://aistudio.google.com/app/apikey

---

### Lỗi: Kết nối PostgreSQL thất bại

**Triệu chứng**: `psycopg2.OperationalError: could not connect to server`

**Kiểm tra**:
```powershell
# Kiểm tra PostgreSQL service đang chạy
Get-Service postgresql*

# Khởi động nếu đang dừng
Start-Service postgresql-x64-16   # Thay 16 = version bạn cài

# Test kết nối
psql -U postgres -d chatbot_nongnghiep -c "SELECT 1;"
```

**Hay gặp**: Sai `POSTGRES_PASSWORD` trong `.env`

---

### Lỗi: Model embedding không tải được

**Triệu chứng**: Lỗi `OSError`, `ConnectionError` khi lần đầu khởi động

**Giải pháp**:
1. Đảm bảo có kết nối Internet
2. Model tải tự động vào `.model_cache/` (~1.5 GB, mất 5-10 phút)
3. Nếu mạng chậm/yếu, tải thủ công trước:

```powershell
# Cài huggingface_hub nếu chưa có
pip install huggingface_hub

# Tải model thủ công
python -c "
from huggingface_hub import snapshot_download
snapshot_download('intfloat/multilingual-e5-large', cache_dir='.model_cache')
print('Done!')
"
```

---

### Lỗi: ChromaDB không tìm thấy kết quả

**Triệu chứng**: Chat hỏi về nông nghiệp nhưng trả lời "không tìm thấy"

**Nguyên nhân thường gặp**:
1. Chưa upload tài liệu nào
2. Thư mục `chroma_db/` bị hỏng

**Giải pháp**:
```powershell
# Kiểm tra số chunks đã có
python -c "
from backend.layers.layer3_docs import get_chunk_count
print(f'Chunk count: {get_chunk_count()}')
"

# Nếu = 0, upload tài liệu qua Admin Dashboard

# Nếu lỗi ChromaDB bị corrupt, reset (MẤT TOÀN BỘ DATA):
Remove-Item -Recurse -Force .\chroma_db
# Rồi upload lại tài liệu
```

---

### Lỗi: BM25 không tìm thấy document mới

**Triệu chứng**: Sau khi upload tài liệu, BM25 vẫn không tìm thấy

**Giải pháp**: BM25 index tự rebuild khi chunk count thay đổi. Nếu không tự rebuild:
```powershell
# Restart server để force rebuild
# Ctrl+C rồi:
python -m uvicorn backend.app:app --reload --port 8000
```

---

### Lỗi: Rate limit Gemini

**Triệu chứng**: `429 RESOURCE_EXHAUSTED` xuất hiện thường xuyên trong log

**Giải pháp**:
1. Thêm nhiều key vào `.env`:
   ```
   GEMINI_API_KEY_2=AIza...
   GEMINI_API_KEY_3=AIza...
   ```
2. Key manager tự động cooldown 10s và rotate sang key khác
3. Kiểm tra trạng thái keys: `http://localhost:8000/api/admin/key-status?username=admin`
4. Đợi quota reset (thường reset mỗi phút)

---

### Lỗi: Server khởi động nhưng chat không phản hồi

**Debug bằng Swagger UI**:
1. Mở `http://localhost:8000/docs`
2. Thử endpoint `POST /api/chat` với câu hỏi đơn giản

**Xem log chi tiết**:
```powershell
python -m uvicorn backend.app:app --reload --port 8000 --log-level debug
```

**Test trực tiếp qua PowerShell**:
```powershell
$body = @{
    question = "lúa OM5451 thích hợp đất gì?"
    session_id = "test_session"
} | ConvertTo-Json

Invoke-RestMethod -Method POST `
    -Uri "http://localhost:8000/api/chat" `
    -ContentType "application/json" `
    -Body $body
```

---

### Lỗi: Import lỗi khi khởi động

**Triệu chứng**: `ModuleNotFoundError`, `ImportError` khi chạy

**Kiểm tra**:
```powershell
# Đảm bảo virtualenv đang active
.venv\Scripts\activate

# Cài lại dependencies
pip install -r requirements.txt --upgrade

# Chạy từ đúng thư mục gốc
cd e:\vi_no_ngon\chatbot
python -m uvicorn backend.app:app --reload --port 8000
```

---

## 📝 Changelog phiên bản

| Phiên bản | Thay đổi chính |
|---|---|
| **v2.2** | Monitoring Gemini cost/token, Tool API Router (`/api/tools/*`), Admin Key Status, Benchmark LLM-as-Judge |
| **v2.1** | BM25 + RRF Hybrid Retrieval, Fast-path Rule Router (< 5ms), Guardrail Validator, Structure-aware Chunker |
| **v2.0** | Multi-source Retrieval Plan (asyncio.gather), IAM Farm Authorization, NextFarm IoT Tools, Freshness Policy |
| **v1.x** | Kiến trúc 3 tầng RAG, PostgreSQL (thay Neo4j), ChromaDB vector store, LLM Router Gemini |

---

