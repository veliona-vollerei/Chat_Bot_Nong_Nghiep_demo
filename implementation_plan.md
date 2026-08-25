# Module Đo Lường Benchmark — Implementation Plan

## Mô tả

Thêm tab **"📊 Đo lường"** vào trang Admin để đánh giá hiệu năng Chatbot theo chuẩn benchmark từ file `Q&E.txt`.

Pipeline đánh giá:
```
Q&E.txt → Chatbot (POST /chat) → Câu trả lời thực tế
                                          ↓
                              LLM-as-a-Judge (Gemini)
                                          ↓
                    Factual Score + Semantic Score → Answer Correctness %
```

---

## Proposed Changes

---

### Backend — API Endpoint

#### [MODIFY] [app.py](file:///e:/vi_no_ngon/chatbot/backend/app.py)

Thêm 2 endpoint mới ở cuối phần Admin endpoints:

**`GET /api/admin/benchmark/questions`**
- Parse `Q&E.txt` tại root chatbot directory
- Trả về list: `[{id, question, ground_truth}, ...]`
- Xác thực admin role

**`POST /api/admin/benchmark/run`**
- Body: `{ questions: [{id, question, ground_truth}] }` (hoặc `"all"` để chạy hết)
- Với mỗi câu hỏi:
  1. Gọi nội bộ logic chat (tái dùng code từ `/chat` endpoint — trích xuất thành hàm `_process_question`)
  2. Gọi Gemini LLM-as-a-judge để chấm điểm
  3. Trả về kết quả từng câu

> [!NOTE]
> Endpoint `run` trả về `StreamingResponse` (SSE/NDJSON) để UI hiển thị từng câu ngay khi xong, không cần đợi toàn bộ.

**Pydantic Model mới:**
```python
class BenchmarkRunRequest(BaseModel):
    questions: list  # list of {id, question, ground_truth}
```

**Cơ chế chấm điểm (LLM-as-a-judge):**
```
JUDGE_PROMPT:
  Cho câu hỏi: {question}
  Đáp án chuẩn: {ground_truth}
  Đáp án chatbot: {chatbot_answer}

  Chấm 2 tiêu chí (JSON):
  1. factual_score (0-100): Số liệu, tên gọi, thông số kỹ thuật có chính xác không?
  2. semantic_score (0-100): Ý nghĩa, trọng tâm có đúng không?
  3. retrieval_note: Nhận xét ngắn về khả năng tìm kiếm
  4. generation_note: Nhận xét ngắn về chất lượng tổng hợp
  5. reasoning: Lý do xếp loại

  Answer Correctness = (factual_score * 0.6) + (semantic_score * 0.4)
```

---

### Backend — Xếp loại

```python
def grade(score: float) -> tuple[str, str]:
    if score >= 90: return ("Xuất sắc", "excellent")
    if score >= 80: return ("Tốt", "good")
    if score >= 70: return ("Khá", "fair")
    if score >= 50: return ("Chưa đạt", "poor")
    return ("Kém", "fail")
```

---

### Frontend — admin.html

#### [MODIFY] [admin.html](file:///e:/vi_no_ngon/chatbot/frontend/admin.html)

Thêm tab thứ 3 trong `admin-tabs`:
```html
<button class="admin-tab-btn" id="tabBenchmarkBtn" onclick="switchAdminTab('benchmark')">
    📊 Đo lường Hiệu năng
</button>
```

Thêm section mới `adminBenchmarkSection` với layout:
- **Header**: Tóm tắt (tổng câu, điểm TB, phân bố xếp loại)
- **Bảng kết quả**: 5 cột (Câu hỏi, Đáp án chuẩn, Đáp án Chatbot, Điểm & Xếp loại, Chi tiết)
- **Nút "Bắt đầu Đo lường"**: Trigger API và stream kết quả từng dòng
- **Progress bar**: Hiển thị tiến độ đánh giá realtime

---

### Frontend — app.js

#### [MODIFY] [app.js](file:///e:/vi_no_ngon/chatbot/frontend/app.js)

Thêm các hàm JS:

```js
switchAdminTab(tab)     // Thêm case 'benchmark'
loadBenchmarkQuestions()  // GET /api/admin/benchmark/questions
runBenchmark()            // POST /api/admin/benchmark/run + stream results
renderBenchmarkRow(result) // Render 1 dòng kết quả vào bảng
updateBenchmarkSummary()   // Cập nhật header tóm tắt
```

---

### Frontend — style.css

#### [MODIFY] [style.css](file:///e:/vi_no_ngon/chatbot/frontend/style.css)

Thêm styles cho:
- `.benchmark-summary-bar` — thanh tóm tắt tổng quan
- `.benchmark-table` — bảng kết quả rộng
- `.score-badge` với màu theo từng xếp loại (excellent/good/fair/poor/fail)
- `.detail-expand` — phần Chi tiết có thể expand/collapse
- `.progress-benchmark` — progress bar đánh giá

---

## Luồng hoạt động chi tiết

```
[Admin click "Đo lường"] 
    → loadBenchmarkQuestions() → GET /api/admin/benchmark/questions
    → Hiển thị bảng với cột câu hỏi + đáp án chuẩn (cột 3,4,5 còn trống)
    → Admin click "Bắt đầu Đo lường"
    → runBenchmark() → POST /api/admin/benchmark/run (streaming NDJSON)
    → Mỗi line JSON từ stream → renderBenchmarkRow()
    → Progress bar: X/N câu đã đánh giá
    → Khi hoàn tất → updateBenchmarkSummary() (điểm TB, phân bố)
```

---

## Format Q&E.txt (đã parse)

File `Q&E.txt` có format:
```
N,câu hỏi: [nội dung câu hỏi]
 trả lời: [nội dung đáp án chuẩn]
```
Mỗi cặp Q&A có thể trải dài nhiều dòng. Parser sẽ nhận dạng theo pattern số thứ tự.

---

## Verification Plan

### Manual
1. Vào trang admin → thấy tab "📊 Đo lường"
2. Tab load → hiển thị bảng 9 câu hỏi từ Q&E.txt
3. Click "Bắt đầu" → progress bar chạy, từng dòng điền vào bảng
4. Khi xong → thanh tóm tắt hiển thị điểm trung bình + xếp loại
5. Click "Chi tiết" → expand xem Retrieval & Generation notes
