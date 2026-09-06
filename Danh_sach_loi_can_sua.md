# Danh sách lỗi cần sửa — Chat_Bot_Nong_Nghiep_demo

Repo: `veliona-vollerei/Chat_Bot_Nong_Nghiep_demo`
Ngày kiểm tra: 07/09/2026
Phương pháp: compile toàn bộ backend (54 file, không lỗi cú pháp) + static analysis (pyflakes) + chạy 78 unit test + đọc code thủ công các module trọng yếu.

**Thứ tự ưu tiên sửa: 1 → 2 → 3 → 4 → 5**

---

## 🔴 1. [NGHIÊM TRỌNG] Retrieval plan bỏ sót 4/6 tool IoT — chatbot thật không trả lời được câu hỏi thiết bị/lịch tưới

**File:** `backend/retrieval/retrieval_plan.py`, hàm `_fetch_tools()` (dòng ~203-260)

**Vấn đề:**
Hàm này là nơi chatbot thật lấy dữ liệu IoT để trả lời user, nhưng chỉ gọi:
```python
from backend.tools.nextfarm_tools import get_latest_sensor, get_alerts
```
Bỏ hoàn toàn `get_device_status`, `get_irrigation_schedule`, `get_irrigation_history`, `get_command_history` — dù các hàm này đã implement đầy đủ trong `nextfarm_tools.py`.

**Hậu quả:** User hỏi "van tưới zone A có hoạt động không?" hoặc "lịch tưới tuần này thế nào?" → chatbot không có dữ liệu để trả lời đúng → LLM bịa hoặc từ chối trả lời sai chỗ.

**Cách sửa:**
- Mở rộng `_fetch_tools()` để nhận diện loại câu hỏi (device/irrigation schedule/irrigation history/command) và gọi tool tương ứng, tương tự cách đang làm với `get_latest_sensor`.
- Đưa `zone_id`/`device_id` cần thiết vào tham số hàm (hiện `_fetch_tools` chỉ nhận `farm_id`, `zone_id`, `sensor_types`).

**File liên quan cần sửa cùng lúc:** `backend/tools/tool_router.py` — `get_command_history` được import (dòng 29) nhưng **không có route REST nào expose nó** (khác với sensor/device/irrigation/alerts đều có endpoint riêng). Cần thêm `@router.get("/command-history")`.

---

## 🔴 2. [NGHIÊM TRỌNG] Benchmark KHÔNG phát hiện được lỗi #1 — báo cáo nghiệm thu có thể "pass" giả

**File:** `backend/simulator/benchmark_evaluator.py`, dòng ~325-360

**Vấn đề:**
Chấm điểm cho category `latest_sensor`, `missing_stale_sensor`, `device_state` bằng cách **gọi thẳng hàm tool** (`get_latest_sensor()`, `get_device_status()`) để kiểm tra hàm chạy được — không đi qua pipeline thật (route → `retrieval_plan._fetch_tools()` → LLM synthesis) mà chatbot dùng khi trả lời user thật.

**Hậu quả:** Có thể chạy `build_benchmark()` + evaluator và nhận báo cáo "260/260 pass", nhưng chatbot thật vẫn trả lời sai cho ~60 câu (3 category: `device_state`, `irrigation_schedule`, `irrigation_history`) vì lỗi #1 ở trên. Đây là **false confidence** — nguy hiểm nhất nếu dùng báo cáo này để nghiệm thu với NextFarm.

**Cách sửa:**
- Với category `device_state`, `irrigation_schedule`, `irrigation_history`, `latest_sensor`: đổi sang gọi qua `_synthesize_answer_for_eval()` (pipeline thật, giống cách đang làm với `agricultural_factual_qa`) thay vì gọi tool trực tiếp.
- `_synthesize_answer_for_eval()` (dòng ~164) hiện cũng chỉ dùng Fact Store + doc hybrid_search, **chưa gọi `retrieval_plan._fetch_tools()`** — cần bổ sung nhánh gọi tool IoT vào chính hàm này trước, để nó thực sự phản ánh pipeline sản xuất.

---

## 🟠 3. [TRUNG BÌNH] Bug định dạng ngày trong Open-Meteo fallback

**File:** `backend/simulator/open_meteo_client.py`, dòng 112, hàm `generate_synthetic_weather()`

```python
times.append(f"2026-09-0{1 + (h // 24):02d}T{hour:02d}:00")
```

**Vấn đề:**
- Với `total_days` mặc định = 14 (`past_days=7 + forecast_days=7`), từ ngày thứ 10 trở đi chuỗi bị lỗi: `"2026-09-010T00:00"` (thừa số 0, ngày 2 chữ số cộng thêm số 0 có sẵn trong template → 3 chữ số) — timestamp ISO không hợp lệ, `datetime.fromisoformat()` sẽ crash nếu có nơi nào parse.
- Năm/tháng bị hard-code cố định "2026-09" bất kể thời điểm chạy thực tế.

**Hiện trạng:** Chưa gây hại vì `generate_synthetic_weather()`/`fetch_weather_forecast()` chưa được gọi ở đâu trong code sản xuất (chỉ dùng trong `test_simulator.py` với `total_days=3`, chưa chạm bug). Sẽ vỡ ngay khi nối vào `water_balance.py` để tính ET0 thật.

**Cách sửa:**
```python
from datetime import timedelta
current_dt = start_time + timedelta(hours=h)
times.append(current_dt.strftime("%Y-%m-%dT%H:%M"))
```
Dùng `datetime` cộng dồn thay vì tự ghép chuỗi thủ công, và bỏ dòng `dt = start_time.replace(hour=0)` đang không dùng tới.

---

## 🟡 4. [NHẸ] `generation_lower` không được dùng trong phân loại root-cause

**File:** `backend/app.py`, dòng 779-807, hàm phân loại root-cause (`_classify_root_cause_group` hoặc tương đương)

```python
retrieval_lower = (retrieval_note or "").lower()
generation_lower = (generation_note or "").lower()   # ← tính ra nhưng không dùng ở đâu cả
```

**Vấn đề:** Toàn bộ logic phân loại (`CORPUS_GAP`, `ROUTER_ERROR`, `RETRIEVAL_MISS`...) chỉ dựa vào `retrieval_lower`. Tín hiệu lỗi từ bước sinh câu trả lời (generation) bị bỏ qua hoàn toàn, mặc định rơi vào `RETRIEVAL_MISS`.

**Hậu quả:** Không ảnh hưởng câu trả lời user nhận được, nhưng làm sai lệch thống kê nguyên nhân lỗi khi debug/nghiệm thu (báo cáo "bao nhiêu % lỗi do generation vs retrieval" không chính xác).

**Cách sửa:** Thêm nhánh kiểm tra tín hiệu lỗi generation (timeout, response rỗng, LLM error...) trong `generation_lower` trước khi fallback về `RETRIEVAL_MISS`.

---

## 🟢 5. [THẤP] Test benchmark báo 210/260 câu do thứ tự check sai

**File:** `backend/simulator/benchmark_builder.py`, dòng 337, hàm `_build_factual_questions()`

```python
if not rows:              # rows là kết quả cursor.fetchall() — trong test là MagicMock() → truthy
    ...fallback...
rows = list(rows)          # list(MagicMock()) === [] → rows rỗng nhưng đã bỏ qua fallback ở trên
```

**Vấn đề:** Kiểm tra `if not rows` xảy ra **trước** khi ép `rows` về list thật. Khi cursor trả về một đối tượng "truthy nhưng không phải list thật" (đúng tình huống mock trong `conftest.py`), code không nhảy vào nhánh fallback đã thiết kế (`_build_factual_questions_fallback_no_oracle`) mà lặng lẽ sinh ra 0/50 câu → tổng benchmark chỉ còn 210/260.

**Mức độ:** Với Postgres thật, `cursor.fetchall()` luôn trả list thật nên bug này khó xảy ra ở production — chủ yếu là code smell tiềm ẩn và làm test suite hiện tại fail.

**Cách sửa:**
```python
rows = list(rows)   # ép về list TRƯỚC
if not rows:         # rồi mới check rỗng
    ...fallback...
```

---

## 🧹 Dọn dẹp code (không bắt buộc, không ảnh hưởng chức năng)

- Import không dùng: `os`, `Header`, `Depends` trong `app.py`; `field`, `Optional`, `asdict`, `Any`, `dataclass`, `timedelta`, `json`, `re`, `math` rải rác ở `simulator/*.py`, `retrieval/*.py`, `iam/iam.py`, `tools/nextfarm_tools.py`.
- Biến local gán rồi không dùng: `doc_id` (`app.py:315` — vô hại vì `doc_id` được tính lại từ `content_hash` bên trong `process_and_ingest_document`, không phải bug), `a_continue` (`app.py:632`, regex compile thừa), `dt` (`open_meteo_client.py`, sẽ tự hết khi sửa mục 3).
- `logger.debug(f"...")` không có placeholder ở `fast_path_router.py` (5 chỗ), `query_router.py` — chỉ mất cơ hội log hữu ích khi debug, không phải bug.
