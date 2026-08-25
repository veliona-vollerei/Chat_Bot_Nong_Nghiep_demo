# 📋 TIẾN ĐỘ TRIỂN KHAI — Chatbot Nông Nghiệp AI 

> **Cập nhật lần cuối:** 2026-08-26 (Phiên Nâng Cấp — Nâng Cấp Gemini Models 3.x, Tối Ưu Bất Đồng Bộ & Benchmark Theo Ngữ Cảnh)  
> **Mục đích:** Theo dõi toàn bộ tiến độ dự án. Đọc file này để tiếp tục làm việc, vận hành hoặc khôi phục hệ thống khi cần.  
> **Trạng thái hiện tại:** 🟢 **HOÀN THÀNH CẬP NHẬT VÀ NÂNG CẤP HỆ THỐNG **

---

## 🔧 CẤU HÌNH & CHỨC NĂNG ĐÃ CHỐT 

| Mục | Giá trị & Mô tả chi tiết |
|-----|--------------------------|
| **Scope Dữ liệu** | **Tổng quát Ngành Nông Nghiệp** (Hỗ trợ đa dạng nông sản: lúa, cà phê, cây ăn quả, rau màu, sâu bệnh, kỹ thuật canh tác, mùa vụ, đất đai...) |
| **LLM Provider & Models** | **Google Gemini Thế Hệ Mới** với cơ chế **Key Rotation Pool** (`GEMINI_API_KEY_1..4`). Router: `gemini-3.1-flash-lite`, Synthesis: `gemini-3.6-flash` |
| **Gemini Key Pool Manager** | Tự động xoay vòng Round-Robin qua tối đa 4 API Keys; phân loại chính xác lỗi 429/Rate-limit (cooldown 10s tự khôi phục), lỗi `404 NOT_FOUND` (ngưng hỗ trợ model) và lỗi `401/403` invalid key; endpoint giám sát real-time `/api/admin/key-status` |
| **Bất đồng bộ Async & Tối ưu Hiệu năng** | Đưa các tác vụ nặng (gọi LLM Gemini API, mô hình Embedding CPU, tìm kiếm ChromaDB) chạy trên ThreadPool (`asyncio.to_thread`), giải phóng hoàn toàn Event Loop chính của FastAPI, loại bỏ tình trạng đơ/lag trang web |
| **Đo lường Hiệu suất (Benchmark)** | Đánh giá **LLM-as-a-Judge** tự động kích hoạt ngầm khi có người dùng hỏi câu trùng/tương đương với bộ câu hỏi chuẩn trong `Q&E.txt`. Chấm điểm chi tiết Factual (60%), Semantic (40%), nhận xét Retrieval, Generation và lý do xếp loại |
| **Data Ingestion Pipeline** | Tối ưu hóa đọc PDF điện tử bằng **PyMuPDF (`fitz`)**, loại bỏ hoàn toàn OCR scan tốn chi phí; hỗ trợ các định dạng: PDF, DOCX, TXT, MD, JSON |
| **Xử lý Upload Thông minh (5 Cases)** | Phân loại upload bằng **SHA-256 Content Hash**:<br>1. `process_new`: Tài liệu mới → Ingest bình thường<br>2. `auto_continue`: File dở dang → Ingest tự động lại từ đầu<br>3. `confirm_duplicate_content`: Nội dung trùng, tên mới → Báo Admin (409 Conflict) thêm Alias tên file mà không cần ingest lại<br>4. `confirm_content_changed`: Cùng tên, nội dung mới → Báo Admin (409 Conflict) duyệt thay thế, cập nhật bản mới và đánh dấu `superseded` bản cũ<br>5. `already_complete`: Nội dung + Tên file đã đầy đủ → Bỏ qua (200 OK) |
| **Dọn dẹp Tự động** | Tự động xóa file và pending confirmation quá hạn 24 giờ khi server khởi động; hỗ trợ endpoint `/favicon.ico` (204 No Content) tránh rác log |
| **Authentication & Phân quyền** | Đăng ký, Đăng nhập (kiểm tra tài khoản khóa `is_blocked`), Khởi tạo tài khoản `admin` / `admin` mặc định |
| **Admin Dashboard** | Trang Quản lý Hệ thống độc lập (`/admin` hoặc `admin.html`) gồm các tab: Upload Dữ liệu thô (Data Pipeline), Quản lý Người dùng (Chặn/Bỏ chặn/Xoá tài khoản), Giám sát Gemini Key Pool & **Bảng Đo lường Hiệu năng Benchmark** |
| **User Chat History** | Lịch sử trò chuyện riêng biệt cho từng tài khoản người dùng trong PostgreSQL |
| **Chat Interface UI** | Giao diện hiện đại, sạch sẽ; hiển thị rõ nguồn tri thức theo tầng (Layer 1 Fact, Layer 2 Knowledge Graph, Layer 3 RAG ChromaDB) |
| **Embedding Model** | `intfloat/multilingual-e5-large` (1024 chiều, chuyên dụng tiếng Việt) |
| **Vector Store** | **ChromaDB** (lưu trữ local tại `chroma_db/`, collection `nongnghiep_chunks`) |
| **Database (PostgreSQL)** | Database `chatbot_nongnghiep` gồm các bảng: `users`, `chat_sessions`, `chat_messages`, `documents`, `document_aliases`, `pending_confirmations`, `facts`, `kg_triples`, `answer_feedback` |

---

## 📁 CẤU TRÚC DỰ ÁN 

```
e:\vi_no_ngon\chatbot\
├── PROGRESS.md                         <- File tiến độ hệ thống (xem trước khi làm việc!)
├── START_CHATBOT.bat                   <- Script khởi chạy nhanh Web Server
├── requirements.txt                    <- Danh sách các thư viện Python cần thiết
├── Q&E.txt                             <- Bộ câu hỏi & đáp án chuẩn dùng cho đo lường hiệu suất
├── benchmark_results.json              <- File tự động lưu trữ kết quả đánh giá LLM-as-a-Judge
├── backend\
│   ├── app.py                          <- FastAPI Server (Auth, Admin APIs, Chat API, Key Status, Benchmark APIs)
│   ├── config.py                       <- Cấu hình hệ thống (Gemini Models 3.x, Key Pool 1..4, DB URL, Paths)
│   ├── db\
│   │   ├── postgres.py                 <- Khởi tạo Schema & CRUD (Users, Chat, Docs, Aliases, Pending)
│   │   └── chroma_db.py                <- Quản lý ChromaDB Vector Collection
│   ├── ingestion\
│   │   └── data_pipeline.py            <- Pipeline xử lý PDF/Docx/TXT/MD với SHA-256 Hash & 5-Case logic
│   ├── layers\
│   │   ├── layer1_facts.py             <- Tầng 1: Structured Fact Store (Số liệu định lượng)
│   │   ├── layer2_kg.py                <- Tầng 2: Knowledge Graph (Quan hệ sâu bệnh, kỹ thuật, giống)
│   │   └── layer3_docs.py              <- Tầng 3: Document Store / RAG ChromaDB
│   ├── router\
│   │   └── query_router.py             <- Gemini Router phân loại câu hỏi & định tuyến 3 tầng
│   ├── preprocessing\
│   │   └── vietnamese_nlp.py           <- Chuẩn hóa tiếng Việt, trích xuất mùa vụ, loại đất, giống
│   └── utils\
│       ├── gemini_client.py            <- GeminiKeyManager (Pool 4 keys, auto-retry, rate-limit cooldown, not_found check)
│       └── text_utils.py               <- Tiện ích xử lý văn bản
├── frontend\
│   ├── index.html                      <- Màn hình Đăng nhập/Đăng ký & Giao diện Chat chính
│   ├── admin.html                      <- Trang Quản lý Hệ thống (Admin Dashboard chuyên biệt kèm bảng Benchmark)
│   ├── style.css                       <- CSS thiết kế giao diện hiện đại, responsive
│   └── app.js                          <- Logic Auth, Chat Stream, Admin Upload, User Mgr & Benchmark UI
├── scripts\
│   ├── setup_db.py                     <- Khởi tạo PostgreSQL DB & seed tài khoản admin
│   ├── ingest_chunks.py                <- Script nạp chunks thủ công
│   └── check_system.py                 <- Kiểm tra toàn bộ kết nối hệ thống
├── data\
│   ├── raw_uploads\                    <- Lưu trữ file tài liệu thô được upload
│   └── pending_uploads\                <- Lưu trữ file tạm chờ Admin duyệt (Case 3, Case 4)
├── chroma_db\                          <- Thư mục lưu trữ dữ liệu Vector ChromaDB
└── marker-master\                       
```

---

## ✅ CHECKLIST TIẾN ĐỘ ĐÃ HOÀN THÀNH

### 🟢 1. Tối Ưu Data Pipeline & Quản Lý Duplicate File Thông Minh (SHA-256)
- [x] Chuyển sang trích xuất văn bản PDF bằng **PyMuPDF (`fitz`)**, loại bỏ OCR scan gây chậm và tốn API.
- [x] Tích hợp kiểm tra **SHA-256 Content Hash** để phân loại upload thành **5 Cases**:
  - `process_new`: Upload file mới thành công.
  - `auto_continue`: Tự động nạp lại nếu lần xử lý trước bị dở dang.
  - `confirm_duplicate_content`: Trùng nội dung nhưng đổi tên file → Trả về HTTP 409, hỗ trợ Admin tạo tên gợi nhớ (Alias) mà không tốn công nạp lại.
  - `confirm_content_changed`: Cùng tên file nhưng nội dung đã thay đổi → Trả về HTTP 409, cho phép Admin xác nhận ghi đè và tự động đánh dấu bản cũ `superseded`.
  - `already_complete`: File trùng cả tên và nội dung → Bỏ qua xử lý.
- [x] Tự động thu dọn các yêu cầu xác nhận pending bị quá hạn 24 giờ khi ứng dụng khởi động.

### 🟢 2. Quản Lý Pool Gemini API Key (Key Rotation Pool) & Cập Nhật Model 3.x
- [x] Thiết lập `GeminiKeyManager` đọc từ `GEMINI_API_KEY_1..4` trong `.env`.
- [x] Xoay vòng Round-Robin tự động giữa các API key khi gọi LLM.
- [x] Cập nhật các Gemini Model thế hệ mới nhất: Router dùng `gemini-3.1-flash-lite`, Synthesis & Judge dùng `gemini-3.6-flash`.
- [x] Phân loại lỗi chính xác: lỗi 429/Rate Limit (tự động cooldown 10 giây), lỗi `404 NOT_FOUND` cho model ngưng hỗ trợ (quăng lỗi trực tiếp thay vì gây nhầm lẫn hạn mức), lỗi key không hợp lệ 401/403 (cách ly vĩnh viễn).
- [x] Endpoint API `/api/admin/key-status` cho Admin theo dõi trạng thái real-time.

### 🟢 3. Tối Ưu Bất Đồng Bộ Async Non-Blocking
- [x] Chuyển các hàm xử lý tính toán nặng và gọi Gemini API (`route_question`, `semantic_search`, `synthesize_answer`) sang luồng phụ với `asyncio.to_thread`.
- [x] Giải phóng hoàn toàn Event Loop chính của FastAPI, loại bỏ tình trạng lag/đơ giao diện web khi chờ LLM phản hồi.
- [x] Bổ sung handler `/favicon.ico` trả về HTTP 204 No Content, sạch log terminal.

### 🟢 4. Hệ Thống Đo Lường Hiệu Suất Theo Ngữ Cảnh (Match-Triggered Benchmark)
- [x] Đánh giá bằng **LLM-as-a-Judge** tự động kích hoạt ngầm khi người dùng hỏi các câu trùng/tương đương với bộ câu hỏi chuẩn trong `Q&E.txt`.
- [x] Không chạy tự động hàng loạt gây tốn kém API key; các câu chưa được hỏi duy trì ở trạng thái `Chờ kích hoạt`.
- [x] Thuật toán `_is_question_match` kết hợp SequenceMatcher và Token Overlap nhận diện chuẩn xác câu hỏi tương đương.
- [x] Tự động lưu trữ kết quả chấm điểm vào `benchmark_results.json`.
- [x] Giao diện Admin Benchmark hiển thị bảng điểm chi tiết, nút **"🔄 Cập nhật bảng"** và **"🗑️ Xoá kết quả"**.

### 🟢 5. Hệ Thống Xác Thực & Quản Lý Tài Khoản (Authentication & Admin)
- [x] Màn hình Đăng ký (Register) & Đăng nhập (Login) mượt mà với ô xác nhận mật khẩu.
- [x] Bảng `users` trong PostgreSQL quản lý thông tin tài khoản, phân quyền (`admin`/`user`), trạng thái khóa (`is_blocked`).
- [x] Khởi tạo sẵn tài khoản mặc định `admin` / `admin`.
- [x] Trang Admin Dashboard độc lập (`admin.html`) với tính năng:
  - Upload dữ liệu thô (có modal hỗ trợ xử lý HTTP 409 Conflict cho Case 3 & Case 4).
  - Quản lý người dùng: Xem danh sách, Chặn/Bỏ chặn (`is_blocked`), Xóa tài khoản.
  - Quản lý Gemini API Key Status Pool.
  - Quản lý Đo lường Hiệu năng Chatbot (Benchmark).

### 🟢 6. Giao Diện Người Dùng & Trải Nghiệm Chatbot (Chat Interface)
- [x] Yêu cầu đăng nhập trước khi truy cập Chatbot.
- [x] Lưu trữ **lịch sử trò chuyện riêng biệt** cho từng tài khoản người dùng trong PostgreSQL.
- [x] Hiển thị chi tiết tầng tri thức phản hồi (Tầng 1 — Fact Store, Tầng 2 — Knowledge Graph, Tầng 3 — Document Store RAG ChromaDB).

### 🟢 7. Kiến Trúc Tri Thức 3 Tầng (3-Layer Hybrid Architecture)
- [x] **Tầng 1 (Structured Fact Store):** Truy vấn bảng `facts` cho các thông số số liệu định lượng (năng suất, lượng phân bón, độ PH, thời gian sinh trưởng...).
- [x] **Tầng 2 (Knowledge Graph):** Truy vấn bảng `kg_triples` cho các mối quan hệ nguyên nhân - kết quả (sâu bệnh, kỹ thuật xử lý, sự phù hợp với mùa vụ/thổ nhưỡng).
- [x] **Tầng 3 (Document Store / RAG ChromaDB):** Tìm kiếm ngữ nghĩa trong ChromaDB (`nongnghiep_chunks`) với embedding `multilingual-e5-large`.

---

## 🔄 HƯỚNG DẪN VẬN HÀNH & KHỞI CHẠY HỆ THỐNG

### Bước 1: Mở môi trường làm việc
Mở terminal PowerShell trong thư mục dự án:
```powershell
cd e:\vi_no_ngon\chatbot
.venv\Scripts\Activate
```

### Bước 2: Kiểm tra cấu hình .env
Đảm bảo file `.env` đã điền đầy đủ Gemini API Keys (hỗ trợ tối đa 4 key) và password PostgreSQL:
```env
GEMINI_API_KEY_1=AIzaSy...
GEMINI_API_KEY_2=AIzaSy...
GEMINI_API_KEY_3=AIzaSy...
GEMINI_API_KEY_4=AIzaSy...
GEMINI_ROUTER_MODEL=gemini-3.1-flash-lite
GEMINI_SYNTHESIS_MODEL=gemini-3.6-flash
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_postgres_password
POSTGRES_DB=chatbot_nongnghiep
```

### Bước 3: Đảm bảo PostgreSQL & Cơ sở dữ liệu hoạt động
Khởi tạo hoặc kiểm tra cấu trúc cơ sở dữ liệu:
```powershell
python scripts/setup_db.py
```

### Bước 4: Khởi chạy Web Server
Khởi chạy FastApi server bằng command line:
```powershell
uvicorn backend.app:app --reload --port 8000
```
Hoặc nhấp đúp trực tiếp vào file **`START_CHATBOT.bat`**.

### Bước 5: Truy cập Ứng dụng
- **Giao diện Chatbot Người dùng:** [http://localhost:8000](http://localhost:8000)
- **Trang Quản lý Hệ thống (Admin):** [http://localhost:8000/admin](http://localhost:8000/admin)
- **Tài khoản Admin mặc định:** `admin` / `admin`
- **Đăng ký tài khoản người dùng mới:** Truy cập trang chủ và bấm vào "Đăng ký ngay".


#### Link:  https://github.com/datalab-to/marker.git

