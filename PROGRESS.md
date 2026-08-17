# 📋 TIẾN ĐỘ TRIỂN KHAI — Chatbot Nông Nghiệp AI (Phiên bản V2.0)

> **Cập nhật lần cuối:** 2026-08-16 (Phiên Nâng Cấp V2.0)  
> **Mục đích:** Theo dõi toàn bộ tiến độ dự án. Khi mở lại máy tính hoặc sau khi mất điện, đọc file này để tiếp tục làm việc hoặc vận hành hệ thống.  
> **Trạng thái hiện tại:** 🟢 **HOÀN THÀNH NÂNG CẤP HỆ THỐNG PHIÊN BẢN V2.0** (Theo file `nang_cap.md`)

---

## 🔧 CẤU HÌNH & CHỨC NĂNG ĐÃ CHỐT V2.0

| Mục | Giá trị |
|-----|---------|
| Scope Dữ liệu | **Tổng quát Ngành Nông Nghiệp** (hỗ trợ đa dạng nông sản: lúa, cà phê, cây ăn quả, rau màu...) |
| Data Pipeline | **`marker-master`** + parser dự phòng (xử lý tự động PDF, DOCX, TXT, MD, JSON thô thành chunks) |
| Authentication | Đăng nhập, Đăng ký (xác nhận mật khẩu), Khởi tạo sẵn tài khoản `admin` / `admin` |
| Admin Dashboard | Trang Quản lý Hệ thống (Upload dữ liệu thô + Quản lý User chặn/xoá tài khoản) |
| User Chat Scope | **Lịch sử trò chuyện riêng biệt** cho từng tài khoản người dùng |
| Chat Interface UI | Đã loại bỏ hoàn toàn các câu hỏi gợi ý mặc định & nút Like/Dislike |
| LLM Provider | Google Gemini (API từ Google AI Studio) |
| Embedding Model | intfloat/multilingual-e5-large (tiếng Việt) |
| Vector Store | ChromaDB (local) |
| Database | PostgreSQL (bảng `users`, `chat_sessions`, `chat_messages`, `facts`, `kg_triples`, `documents`) |

---

## 📁 CẤU TRÚC DỰ ÁN V2.0

```
e:\vi_no_ngon\chatbot\
├── PROGRESS.md                         <- File tiến độ (đọc trước khi tắt/bật máy!)
├── nang_cap.md                         <- Yêu cầu nâng cấp ban đầu
├── marker-master\                      <- Công cụ chuyển đổi PDF/Docx sang Markdown thô
├── backend\
│   ├── app.py                          <- FastAPI Backend V2.0 (Auth, Admin, Chat API)
│   ├── config.py                       <- Cấu hình hệ thống (API Key, DB URL, Upload path)
│   ├── db\
│   │   ├── postgres.py                 <- Quản lý User DB & Session DB PostgreSQL
│   │   └── chroma_db.py                <- Quản lý ChromaDB Vector Collection
│   ├── ingestion\
│   │   └── data_pipeline.py            <- Pipeline xử lý dữ liệu thô với marker-master
│   ├── layers\
│   │   ├── layer1_facts.py             <- Tầng 1: Structured Fact Store
│   │   ├── layer2_kg.py                <- Tầng 2: Knowledge Graph
│   │   └── layer3_docs.py              <- Tầng 3: Document Store / RAG ChromaDB
│   ├── router\
│   │   └── query_router.py             <- Gemini Router nông nghiệp tổng quát
│   └── preprocessing\
│       └── vietnamese_nlp.py           <- Chuẩn hóa tiếng Việt
├── frontend\
│   ├── index.html                      <- Giao diện Auth Modal + Chat Interface + Admin Dashboard
│   ├── style.css                       <- CSS thiết kế hiện đại, chuyên nghiệp
│   └── app.js                          <- Logic Auth, Admin Upload, Quản lý User, Chat
├── scripts\
│   ├── setup_db.py                     <- Khởi tạo DB & seed user admin/admin
│   ├── ingest_chunks.py                <- Script nạp chunks
│   └── check_system.py                 <- Kiểm tra kết nối hệ thống
└── data\
    └── raw_uploads\                    <- Nơi lưu trữ tài liệu thô do Admin upload
```

---

## ✅ CHECKLIST TIẾN ĐỘ ĐÃ HOÀN THÀNH (V2.0)

### 🟢 1. Mở rộng Nền tảng Dữ liệu & Pipeline Xử lý
- [x] Loại bỏ sự phụ thuộc vào file `chunks_enriched_doc_001.json` duy nhất.
- [x] Mở rộng phạm vi hỗ trợ sang **ngành nông nghiệp tổng quát** (đa dạng nông sản).
- [x] Tích hợp công cụ **`marker-master`** trong `backend/ingestion/data_pipeline.py` tự động chuyển đổi PDF/Word/TXT thành Chunks nạp vào ChromaDB & Postgres.

### 🟢 2. Hệ thống Xác thực Tài khoản (Authentication)
- [x] Tạo màn hình Đăng nhập (Login).
- [x] Tạo màn hình Đăng ký (Register - có ô xác nhận mật khẩu).
- [x] Thêm bảng `users` trong PostgreSQL.
- [x] Khởi tạo tài khoản Quản trị mặc định: `admin` / `admin`.

### 🟢 3. Trang Quản lý Hệ thống (Admin Dashboard)
- [x] Phân quyền truy cập (chỉ tài khoản `admin` mới thấy và vào được Admin Dashboard).
- [x] Chức năng **Cập nhật Dữ liệu**: Upload file tài liệu thô -> tự động chạy `marker-master` pipeline -> cập nhật tri thức.
- [x] Chức năng **Quản lý Người dùng**: Hiển thị bảng tài khoản, hỗ trợ **chặn (block)** và **xoá (delete)** tài khoản.

### 🟢 4. Giao diện Giao tiếp Chatbot (Chat Interface)
- [x] Yêu cầu đăng nhập trước khi sử dụng.
- [x] Thanh tiện ích có nút **Đăng xuất** (Logout), **Đoạn chat mới** (New Chat), User Info Badge.
- [x] Lưu trữ **lịch sử trò chuyện riêng biệt** cho từng tài khoản.
- [x] **Loại bỏ hoàn toàn** các gợi ý câu hỏi mặc định.
- [x] **Loại bỏ** nút Like (👍) và Dislike (👎) dưới mỗi câu trả lời.

### 🟢 5. Dọn dẹp Dữ liệu Cũ
- [x] Xoá file dữ liệu cũ `data/chunks_enriched_doc_001.json`.
- [x] Chuẩn hoá hệ thống sẵn sàng nhận tri thức mới từ Admin Dashboard.

---

## 🔄 HƯỚNG DẪN KHÔI PHỤC & KHỞI CHẠY SAU KHI TẮT MÁY / MẤT ĐIỆN

Nếu máy tính bị ngắt điện hoặc tắt máy, lần tới bật lên hãy thực hiện các bước sau để khởi chạy lại hệ thống:

### Bước 1: Mở môi trường làm việc
Mở terminal PowerShell trong thư mục dự án:
```powershell
cd e:\vi_no_ngon\chatbot
.venv\Scripts\Activate
```

### Bước 2: Kiểm tra cấu hình .env
Đảm bảo file `.env` đã có đầy đủ API Key và password:
```env
GEMINI_API_KEY=<API Key của bạn>
POSTGRES_PASSWORD=<Mật khẩu PostgreSQL của bạn>
```

### Bước 3: Đảm bảo PostgreSQL dịch vụ đang chạy
Kiểm tra kết nối DB:
```powershell
python scripts/setup_db.py
```
*(Nếu đã chạy trước đó, lệnh trên sẽ bỏ qua các mục đã tồn tại và seed tài khoản admin/admin nếu chưa có).*

### Bước 4: Khởi chạy Web Server
Chạy lệnh bắt đầu server:
```powershell
uvicorn backend.app:app --reload --port 8000
```
Hoặc nhấp đúp vào file `START_CHATBOT.bat` ngoài thư mục chính.

### Bước 5: Truy cập ứng dụng
- Mở trình duyệt truy cập: **`http://localhost:8000`**
- **Tài khoản Admin mặc định:** `admin` / `admin`
- **Đăng ký tài khoản mới:** Bấm vào liên kết "Đăng ký ngay" trên màn hình Đăng nhập.
