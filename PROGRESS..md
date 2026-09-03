# 📋 TIẾN ĐỘ TRIỂN KHAI — Chatbot Nông Nghiệp AI

> **Cập nhật lần cuối:** 2026-08-29 (Phiên Kiểm Tra Toàn Hệ Thống — Xác nhận trạng thái & cập nhật tài liệu)
> **Mục đích:** Theo dõi toàn bộ tiến độ dự án. Đọc file này để tiếp tục làm việc, vận hành hoặc khôi phục hệ thống khi cần.
> **Trạng thái hiện tại:** 🟢 **HỆ THỐNG HOÀN CHỈNH — SẴN SÀNG VẬN HÀNH**

---

## 🔧 CẤU HÌNH & CHỨC NĂNG ĐÃ CHỐT

| Mục | Giá trị & Mô tả chi tiết |
|-----|--------------------------|
| **Scope Dữ liệu** | **Tổng quát Ngành Nông Nghiệp** — Hỗ trợ đa dạng: lúa, cà phê, cây ăn quả (dưa hấu, sầu riêng, cam, bưởi, xoài), rau màu, gia súc, sâu bệnh, kỹ thuật canh tác, mùa vụ, đất đai... |
| **LLM Provider & Models** | **Google Gemini** với **Key Rotation Pool** (GEMINI_API_KEY_1..4). Router: gemini-3.1-flash-lite · Synthesis & Judge: gemini-3.6-flash |
| **Gemini Key Pool Manager** | Thread-safe Singleton GeminiKeyManager — Round-Robin qua tối đa 4 API Keys; cooldown 10s tự phục hồi cho rate-limit; cách ly vĩnh viễn key invalid 401/403; retry server_error với backoff (3/6/10s); từ chối ngay lỗi 404 NOT_FOUND (model bị gỡ) |
| **Bất đồng bộ Async** | Toàn bộ tác vụ nặng (Gemini API, Embedding CPU, ChromaDB search) chạy trên ThreadPool via asyncio.to_thread — Event Loop chính FastAPI luôn tự do |
| **Data Ingestion Pipeline** | Sử dụng **marker-master** (lazy-load lần đầu) đọc PDF/DOCX/PPTX/XLSX/EPUB/HTML; TXT/MD/JSON xử lý nội bộ trực tiếp; **OCR tắt hoàn toàn** (disable_ocr=True) |
| **Upload Thông minh (5 Cases)** | Phân loại bằng **SHA-256 Content Hash**: process_new · auto_continue · confirm_duplicate_content (409) · confirm_content_changed (409) · already_complete |
| **Benchmark LLM-as-a-Judge** | Tự động kích hoạt ngầm khi user hỏi câu trùng/tương đương với Q&E.txt — SequenceMatcher >= 0.70 hoặc Jaccard >= 0.55 / Contain-ratio >= 0.75; lưu vào benchmark_results.json |
| **Benchmark Thủ Công** | Admin có thể chọn câu hỏi bất kỳ → POST /api/admin/benchmark/run → Streaming NDJSON kết quả từng câu |
| **Xếp Loại Điểm** | Xuất sắc >=90 · Tốt >=80 · Khá >=70 · Chưa đạt >=50 · Kém <50 — Công thức: Factual x 60% + Semantic x 40% |
| **Authentication** | Register/Login với SHA-256+Salt; kiểm tra is_blocked; seed sẵn admin/admin; token dạng token_{username}_{user_id} |
| **Admin Dashboard** | Trang độc lập /admin — 4 tabs: Upload Data (5 Cases + Modal 409), Quản lý Users, Key Pool Status, Benchmark |
| **Voice Input** | Nhận diện giọng nói tiếng Việt qua **Web Speech API** (lang: vi-VN) trong giao diện Chat |
| **User Chat History** | Lịch sử riêng biệt theo username + session_id; tối đa 30 phiên / người dùng, 100 tin nhắn / phiên |
| **Đa Phiên Chat** | Người dùng có thể tạo mới / chuyển đổi / xóa phiên chat tùy ý; tất cả được lưu PostgreSQL |
| **Embedding Model** | intfloat/multilingual-e5-large — 1024 chiều, chuyên dụng tiếng Việt, cache tại .model_cache/ |
| **Vector Store** | **ChromaDB** local tại chroma_db/, collection nongnghiep_chunks |
| **Database (PostgreSQL)** | DB chatbot_nongnghiep — 9 bảng: users, chat_sessions, chat_messages, documents, document_aliases, pending_confirmations, facts, kg_triples, answer_feedback |
| **Xuất Dữ Liệu Parquet** | Script `convert_parquet.py` tự động xuất toàn bộ 9 bảng PostgreSQL + ChromaDB vector collection sang các file `.parquet` lưu tại `data/parquet/` |
| **Dọn dẹp Tự động** | Startup: xóa pending_confirmations + file tạm hết hạn 24h; handler /favicon.ico → 204 No Content |
| **Health Check** | GET /health — báo cáo PostgreSQL, ChromaDB, chunk count, config errors |

---

## 📁 CẤU TRÚC DỰ ÁN

`
e:\vi_no_ngon\chatbot\
├── PROGRESS..md                        <- File tiến độ hệ thống (đọc trước khi làm việc!)
├── START_CHATBOT.bat                   <- Script khởi chạy nhanh Web Server
├── requirements.txt                    <- Danh sách thư viện Python
├── Q&E.txt                             <- 9 cặp câu hỏi/đáp án chuẩn cho Benchmark
├── benchmark_results.json              <- Kết quả LLM-as-a-Judge tự động tích lũy
├── .env                                <- Biến môi trường (API Keys, DB password)
├── backend\
│   ├── app.py                          <- FastAPI Server (1342 dòng) — toàn bộ API endpoints
│   ├── config.py                       <- Cấu hình tập trung (Models, Key Pool, DB URL, Paths)
│   ├── db\
│   │   ├── postgres.py                 <- Schema DDL + CRUD (665 dòng) — Users, Chat, Docs, Aliases, Pending
│   │   └── chroma_db.py                <- Quản lý ChromaDB collection
│   ├── ingestion\
│   │   └── data_pipeline.py            <- Pipeline xử lý tài liệu (360 dòng) — marker-master + 5-Case SHA-256
│   ├── layers\
│   │   ├── layer1_facts.py             <- Tầng 1: Structured Fact Store (số liệu định lượng)
│   │   ├── layer2_kg.py                <- Tầng 2: Knowledge Graph (sâu bệnh, kỹ thuật, giống)
│   │   └── layer3_docs.py              <- Tầng 3: Document Store / RAG ChromaDB
│   ├── router\
│   │   └── query_router.py             <- Gemini Router phân loại 5 loại câu hỏi → định tuyến 3 tầng
│   ├── preprocessing\
│   │   └── vietnamese_nlp.py           <- Chuẩn hóa tiếng Việt, trích xuất mùa vụ/loại đất/giống
│   └── utils\
│       ├── gemini_client.py            <- GeminiKeyManager (355 dòng) — Pool, Round-Robin, Retry, Backoff
│       └── text_utils.py               <- Tiện ích xử lý văn bản
├── frontend\
│   ├── index.html                      <- Màn hình Login/Register + Giao diện Chat chính + Voice Input
│   ├── admin.html                      <- Trang Admin Dashboard (4 tabs)
│   ├── style.css                       <- CSS hiện đại, responsive (31 KB)
│   └── app.js                          <- Logic Auth, Chat, Sessions, Voice, Admin, Benchmark UI (923 dòng)
├── data\
│   ├── raw_uploads\                    <- File tài liệu thô đã upload thành công
│   └── pending_uploads\                <- File tạm chờ Admin xác nhận (Case 3, Case 4, TTL 24h)
├── chroma_db\                          <- Dữ liệu Vector ChromaDB (local)
├── marker-master\                      <- Thư viện đọc tài liệu (PDF/DOCX/PPTX/XLSX/EPUB/HTML)
└── .model_cache\                       <- Cache embedding model multilingual-e5-large
`

---

## 🌐 DANH SÁCH API ENDPOINTS

### Auth
| Method | Path | Mô tả |
|--------|------|-------|
| POST | /api/auth/register | Đăng ký tài khoản mới |
| POST | /api/auth/login | Đăng nhập |
| GET | /api/auth/me | Thông tin tài khoản hiện tại |

### Chat
| Method | Path | Mô tả |
|--------|------|-------|
| POST | /chat | Xử lý câu hỏi → 3-Layer → Gemini Synthesis → lưu lịch sử |

### Sessions & History
| Method | Path | Mô tả |
|--------|------|-------|
| GET | /api/sessions | Danh sách phiên chat (theo username) |
| GET | /api/sessions/{id}/messages | Lịch sử tin nhắn phiên |
| DELETE | /api/sessions/{id} | Xoá phiên chat |

### Admin — Users
| Method | Path | Mô tả |
|--------|------|-------|
| GET | /api/admin/users | Danh sách tất cả người dùng |
| POST | /api/admin/users/{id}/block | Chặn / bỏ chặn tài khoản |
| DELETE | /api/admin/users/{id} | Xoá tài khoản |

### Admin — Upload Data
| Method | Path | Mô tả |
|--------|------|-------|
| POST | /api/admin/upload-data | Upload tài liệu → 5-Case phân loại → ingest |
| POST | /api/admin/upload-data/confirm | Xác nhận Case 3 (alias) / Case 4 (replace) |

### Admin — Gemini Key Pool
| Method | Path | Mô tả |
|--------|------|-------|
| GET | /api/admin/key-status | Trạng thái real-time tất cả API keys |

### Admin — Benchmark
| Method | Path | Mô tả |
|--------|------|-------|
| GET | /api/admin/benchmark/questions | Danh sách câu hỏi từ Q&E.txt |
| GET | /api/admin/benchmark/results | Kết quả đánh giá (evaluated + pending) |
| DELETE | /api/admin/benchmark/results | Reset xoá toàn bộ kết quả |
| POST | /api/admin/benchmark/run | Chạy benchmark thủ công → Streaming NDJSON |

### System
| Method | Path | Mô tả |
|--------|------|-------|
| GET | /health | Kiểm tra PostgreSQL, ChromaDB, chunks, config |
| GET | /favicon.ico | 204 No Content (tránh rác log) |
| GET | / | Serve frontend/index.html |
| GET | /admin | Serve frontend/admin.html |

---

## ✅ CHECKLIST TIẾN ĐỘ ĐÃ HOÀN THÀNH

### 🟢 1. Kiến Trúc Tri Thức 3 Tầng (3-Layer Hybrid RAG)
- [x] **Tầng 1 (Structured Fact Store):** Truy vấn bảng facts — số liệu định lượng (năng suất, phân bón, pH, thời gian sinh trưởng, mật độ gieo sạ...).
- [x] **Tầng 2 (Knowledge Graph):** Truy vấn bảng kg_triples — quan hệ nguyên nhân/kết quả (sâu bệnh, kỹ thuật xử lý, phù hợp mùa vụ/thổ nhưỡng).
- [x] **Tầng 3 (Document Store / RAG ChromaDB):** Tìm kiếm ngữ nghĩa bằng embedding multilingual-e5-large, top-k=4 chunks.
- [x] Router Gemini tự động phân loại câu hỏi → định tuyến đúng tầng (fallback tự động xuống Tầng 3 nếu Tầng trên không có kết quả).
- [x] Router hỗ trợ **Conversation History** — truyền 4 lượt gần nhất để hiểu câu hỏi nối tiếp/đại từ thay thế.
- [x] Router nhận diện ngoai_pham_vi và can_lam_ro — từ chối hoặc hỏi ngược người dùng.

### 🟢 2. Gemini Key Pool Manager (Thread-Safe Singleton)
- [x] Đọc GEMINI_API_KEY_1..4 từ .env, bỏ qua key rỗng/placeholder; backward-compat với key cũ GEMINI_API_KEY.
- [x] Round-Robin tự động; theo dõi total_calls, total_errors, rotations_caused cho từng key.
- [x] Cooldown 10s tự phục hồi cho rate-limit (429); cách ly vĩnh viễn cho invalid key (401/403).
- [x] Retry server-error (500/502/503/504) với backoff 3/6/10s trước khi rotate key.
- [x] Lỗi 404 NOT_FOUND (model bị Google gỡ) → raise ngay, không rotate.
- [x] AllKeysExhaustedError khi pool cạn kiệt.
- [x] API giám sát real-time /api/admin/key-status — preview 6 ký tự cuối key.

### 🟢 3. Data Ingestion Pipeline (marker-master + SHA-256)
- [x] Tích hợp **marker-master** (lazy-load lần đầu) hỗ trợ: PDF, DOCX, DOC, PPTX, PPT, XLSX, XLS, EPUB, HTML, HTM.
- [x] TXT, MD, JSON xử lý nội bộ trực tiếp không qua marker.
- [x] OCR tắt hoàn toàn — chỉ lấy văn bản kỹ thuật số; trang scan/ảnh bỏ qua tự động.
- [x] **SHA-256 Content Hash** phân loại 5 Cases upload:
  - process_new: Tài liệu mới → ingest bình thường.
  - auto_continue: Dở dang → ingest lại từ đầu tự động.
  - confirm_duplicate_content: Trùng nội dung, tên mới → 409, Admin thêm Alias.
  - confirm_content_changed: Cùng tên, nội dung mới → 409, Admin duyệt thay thế; ingest mới trước, xóa cũ sau khi success; giữ nguyên bản cũ nếu partial_failure.
  - already_complete: Trùng cả tên & nội dung → 200 bỏ qua.
- [x] Startup tự động dọn pending_confirmations + file tạm hết hạn 24h.

### 🟢 4. Bất Đồng Bộ Async Non-Blocking
- [x] route_question, semantic_search, synthesize_answer, _call_judge → asyncio.to_thread.
- [x] Benchmark auto-check sau mỗi lần chat → asyncio.create_task (fire-and-forget).
- [x] Event Loop chính FastAPI hoàn toàn không bị block bởi tác vụ CPU/IO.

### 🟢 5. Hệ Thống Đo Lường Hiệu Suất Benchmark
- [x] **Auto-trigger ngầm:** Mỗi lần user chat → so sánh với 9 câu trong Q&E.txt — SequenceMatcher >= 0.70, hoặc Jaccard >= 0.55, hoặc Contain-ratio >= 0.75. Chỉ lưu best_match.
- [x] **Benchmark thủ công:** Admin chọn câu → POST /api/admin/benchmark/run → NDJSON streaming từng kết quả.
- [x] Chấm điểm: Factual (0-100) x 60% + Semantic (0-100) x 40% = answer_correctness.
- [x] Lưu vào benchmark_results.json: câu hỏi gốc, câu user hỏi thực, đáp án chatbot, điểm, xếp loại, ghi chú retrieval/generation, reasoning.
- [x] Admin UI: bảng điểm đầy đủ, nút 🔄 Cập nhật, nút 🗑️ Xoá kết quả.

### 🟢 6. Xác Thực & Quản Lý Tài Khoản
- [x] Đăng ký: validate username >= 3 ký tự, không trùng, mật khẩu khớp; hash SHA-256+salt.
- [x] Đăng nhập: kiểm tra is_blocked; token format token_{username}_{user_id}.
- [x] Seed sẵn admin/admin khi init_db().
- [x] Admin có thể: xem danh sách users, chặn/bỏ chặn, xoá (bảo vệ tài khoản admin hệ thống).

### 🟢 7. Giao Diện Frontend (Chat + Admin)
- [x] **Auth modal:** Login / Register form, chuyển đổi mượt mà, hiển thị lỗi inline.
- [x] **User badge:** Hiển thị username, role tag, nút Admin Dashboard (chỉ hiện với admin).
- [x] **Sidebar sessions:** Danh sách phiên chat riêng từng user, tạo mới / chuyển đổi / xoá.
- [x] **Voice Input:** Nút 🎤 nhận diện giọng nói tiếng Việt qua Web Speech API, hiển thị trạng thái recording.
- [x] **Hiển thị nguồn tri thức:** Rõ ràng theo tầng (Tầng 1 Fact / Tầng 2 KG / Tầng 3 RAG).
- [x] **System status indicator:** Dot trạng thái + số chunks loaded (cập nhật mỗi 60 giây).
- [x] **Admin Dashboard** (admin.html) — 4 tabs:
  - 📤 Upload Data: form upload + xử lý modal 409 (Case 3/4 với nút Accept/Reject).
  - 👥 Quản lý Users: bảng danh sách, Chặn/Bỏ chặn, Xoá.
  - 🔑 Key Pool Status: bảng trạng thái real-time từng Gemini key.
  - 📊 Benchmark: bảng điểm, Cập nhật, Xoá kết quả.

### 🟢 8. Database PostgreSQL (9 Bảng)
- [x] **users**: Tài khoản, mật khẩu hash, role, is_blocked.
- [x] **chat_sessions**: Phiên chat gắn username, title tự động từ tin nhắn đầu.
- [x] **chat_messages**: Tin nhắn với sender, content, metadata JSONB, created_at; indexed theo (session_id, created_at).
- [x] **documents**: Quản lý tài liệu theo content_hash, processing_status (processing/partial_failure/complete/superseded).
- [x] **document_aliases**: Tên file phụ liên kết với cùng một document_id.
- [x] **pending_confirmations**: Context tạm Case 3/4 với expires_at (24h TTL).
- [x] **facts**: Số liệu định lượng nông nghiệp cho Tầng 1.
- [x] **kg_triples**: Quan hệ thực thể cho Tầng 2 Knowledge Graph.
- [x] Migration tự động idempotent chạy mỗi lần startup.

---

## 🔄 HƯỚNG DẪN VẬN HÀNH & KHỞI CHẠY HỆ THỐNG

### Bước 1: Mở môi trường làm việc
`powershell
cd e:\vi_no_ngon\chatbot
.venv\Scripts\Activate
`

### Bước 2: Kiểm tra cấu hình .env
Đảm bảo file .env đã điền đầy đủ (hỗ trợ tối đa 4 Gemini key):
`env
GEMINI_API_KEY_1=AIzaSy...
GEMINI_API_KEY_2=AIzaSy...
GEMINI_API_KEY_3=AIzaSy...
GEMINI_API_KEY_4=AIzaSy...
GEMINI_ROUTER_MODEL=gemini-3.1-flash-lite
GEMINI_SYNTHESIS_MODEL=gemini-3.6-flash
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_postgres_password
POSTGRES_DB=chatbot_nongnghiep
`

### Bước 3: Khởi tạo / kiểm tra Database
`powershell
python scripts/setup_db.py
`

### Bước 4: Khởi chạy Web Server
`powershell
uvicorn backend.app:app --reload --port 8000
`
Hoặc nhấp đúp vào **START_CHATBOT.bat**.

### Bước 5: Truy cập Ứng dụng
| Đường dẫn | Mô tả |
|-----------|-------|
| http://localhost:8000 | Giao diện Chatbot người dùng |
| http://localhost:8000/admin | Trang Quản lý Hệ thống (Admin Dashboard) |
| http://localhost:8000/health | Kiểm tra trạng thái hệ thống |
| http://localhost:8000/docs | Swagger UI — toàn bộ API |
| Admin mặc định | admin / admin |

---

## 📊 CẤU TRÚC DỮ LIỆU Q&E.TXT (9 câu hỏi chuẩn)

| # | Chủ đề |
|---|--------|
| 1 | Biến đổi khí hậu là gì? |
| 2 | Định nghĩa khí nhà kính theo Luật BVMT 2020 |
| 3 | Tín chỉ carbon theo Luật BVMT 2020 |
| 4 | Kỹ thuật 3 giảm 3 tăng trong canh tác lúa |
| 5 | Kỹ thuật 1 phải 5 giảm |
| 6 | Nhiệt độ thích hợp cho lúa thời kỳ đẻ nhánh/làm đòng |
| 7 | Tạo hình đa thân không hãm ngọn cho cà phê |
| 8 | Yêu cầu tầng đất mặt trồng cà phê |
| 9 | Lượng nước tưới cà phê vối so với Arabica/Liberca |

---

## 🔗 TÀI NGUYÊN THAM KHẢO

- **marker-master:** https://github.com/datalab-to/marker.git
- **Swagger UI:** http://localhost:8000/docs (khi server đang chạy)
- **ChromaDB Docs:** https://docs.trychroma.com/
- **Gemini API Docs:** https://ai.google.dev/gemini-api/docs
