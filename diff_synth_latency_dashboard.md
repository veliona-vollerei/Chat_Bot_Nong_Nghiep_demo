# Diff — Hiển Thị Latency THẬT Của Chatbot Trên Dashboard

> Tách riêng "latency thật người dùng trải nghiệm" (chỉ synthesis) khỏi "latency benchmark tổng" (gồm cả AI-Judge chấm điểm ngầm). Áp dụng bằng `git apply` hoặc copy tay.

---

## 1. `backend/app.py`

Mục đích: Endpoint `/api/admin/acceptance-status` giờ tính thêm p50/p90/p95 của `synth_latency_ms` (đọc từ `expert_review_queue.json` — đầy đủ 80 câu, không bị cắt còn 10 như trong `acceptance_results.json`).

```diff
diff --git a/backend/app.py b/backend/app.py
index f88acf4..bbc7427 100644
--- a/backend/app.py
+++ b/backend/app.py
@@ -1394,9 +1394,44 @@ async def get_acceptance_status(username: Optional[str] = None):
     except Exception as e:
         raise HTTPException(status_code=500, detail=f"Lỗi đọc file nghiệm thu: {e}")
 
+    # ─── Tính latency THẬT của chatbot (chỉ synthesis, không gồm AI-Judge) ───
+    # Lấy từ expert_review_queue.json vì file này lưu ĐẦY ĐỦ (không bị cắt còn 10
+    # như judge_stats.details trong acceptance_results.json).
+    real_latency_stats = None
+    try:
+        queue_path = BASE_DIR / "data" / "expert_review_queue.json"
+        if queue_path.exists():
+            queue_data = json.loads(queue_path.read_text(encoding="utf-8"))
+            synth_latencies = [
+                item["synth_latency_ms"]
+                for item in queue_data.get("items", [])
+                if isinstance(item.get("synth_latency_ms"), (int, float))
+            ]
+            if synth_latencies:
+                synth_latencies.sort()
+                n = len(synth_latencies)
+                def _pct(p):
+                    idx = min(n - 1, int(round(p * (n - 1))))
+                    return round(synth_latencies[idx], 1)
+                real_latency_stats = {
+                    "sample_size": n,
+                    "p50_ms": _pct(0.50),
+                    "p90_ms": _pct(0.90),
+                    "p95_ms": _pct(0.95),
+                    "note": "Latency THẬT người dùng trải nghiệm (chỉ trả lời, không gồm AI-Judge chấm điểm ngầm)",
+                }
+    except Exception as e:
+        logger.warning(f"Không tính được real_latency_stats: {e}")
+
     return {
         "source_file": chosen_path.name,
         "is_latest_fix": chosen_path == post_fix_path,
+        "real_chatbot_latency": real_latency_stats or {
+            "note": (
+                "Chưa có dữ liệu synth_latency_ms (bản benchmark này chạy trước khi tách "
+                "riêng latency thật). Chạy lại: python -m backend.simulator.benchmark_evaluator"
+            )
+        },
         **data,
     }
 

```

---

## 2. `frontend/admin.html`

Mục đích: Hiển thị khối "⚡ Latency THẬT người dùng trải nghiệm" ngay dưới bảng tổng kết nghiệm thu, có ghi chú so sánh rõ ràng với latency benchmark gộp để không ai hiểu nhầm.

```diff
diff --git a/frontend/admin.html b/frontend/admin.html
index 3add061..6807c89 100644
--- a/frontend/admin.html
+++ b/frontend/admin.html
@@ -133,6 +133,7 @@
                         <span id="acceptanceStatusBadge" style="padding:4px 12px;border-radius:8px;font-weight:600"></span>
                     </div>
                     <div class="benchmark-summary" id="acceptanceSummaryGrid"></div>
+                    <div id="realLatencyBox" style="margin-top:12px;padding:10px 14px;border-radius:8px;background:rgba(59,130,246,0.08);border:1px solid rgba(59,130,246,0.25)"></div>
                 </div>
                 <!-- Banner phân biệt rõ ràng: Đây là dữ liệu batch tĩnh -->
                 <div id="evaluationStaticBanner" style="
@@ -748,6 +749,32 @@
                     <div class="summary-item"><span class="summary-label">Chế độ đánh giá</span><span class="summary-value">${d.evaluation_mode}</span></div>
                     <div class="summary-item"><span class="summary-label">Đánh giá lúc</span><span class="summary-value" style="font-size:11px">${new Date(d.evaluated_at).toLocaleString('vi-VN')}</span></div>
                 `;
+
+                // ─── Latency THẬT của chatbot (tách khỏi latency benchmark gộp cả AI-Judge) ───
+                const rl = d.real_chatbot_latency;
+                const latencyBox = document.getElementById("realLatencyBox");
+                if (rl && rl.p50_ms !== undefined) {
+                    latencyBox.innerHTML = `
+                        <div style="font-size:12px;font-weight:600;color:#60a5fa;margin-bottom:6px">
+                            ⚡ Latency THẬT người dùng trải nghiệm (mẫu ${rl.sample_size} câu, không gồm AI-Judge chấm ngầm)
+                        </div>
+                        <div style="display:flex;gap:20px;font-size:13px">
+                            <span>p50: <b>${(rl.p50_ms/1000).toFixed(1)}s</b></span>
+                            <span>p90: <b>${(rl.p90_ms/1000).toFixed(1)}s</b></span>
+                            <span>p95: <b>${(rl.p95_ms/1000).toFixed(1)}s</b></span>
+                        </div>
+                        <div style="font-size:11px;color:var(--text-muted);margin-top:6px">
+                            (So sánh: latency "${d.p90_latency_ms ? (d.p90_latency_ms/1000).toFixed(1)+'s' : '-'}"
+                            ở trên là TỔNG benchmark gồm cả bước AI-Judge chấm điểm, không phải cái người dùng thật chờ)
+                        </div>
+                    `;
+                } else {
+                    latencyBox.innerHTML = `
+                        <div style="font-size:12px;color:var(--text-muted)">
+                            ⚠️ ${rl ? rl.note : 'Chưa có dữ liệu latency thật.'}
+                        </div>
+                    `;
+                }
             } catch (e) {
                 sourceFile.textContent = "Lỗi tải dữ liệu: " + e.message;
             }

```

---

## Lưu ý quan trọng trước khi dùng

Dữ liệu hiện tại (`data/acceptance_results.json` và `data/expert_review_queue.json`) được sinh ra **TRƯỚC KHI** field `synth_latency_ms` được thêm vào code — nên lúc đầu vào trang dashboard, phần "Latency THẬT" sẽ hiện cảnh báo:
> ⚠️ Chưa có dữ liệu synth_latency_ms...

**Cần chạy lại benchmark 1 lần** để có số liệu thật:
```bash
python -m backend.simulator.benchmark_evaluator
```

Sau khi chạy xong, mở tab Benchmark trong admin dashboard → sẽ thấy khối latency thật hiện ra với số liệu cụ thể (dự kiến sẽ thấy con số **thấp hơn nhiều** so với 19-26s hiện tại, vì giờ chỉ đo phần trả lời, không cộng thêm AI-Judge).

## Cách áp dụng

```bash
git apply 01_app.patch     # nội dung diff mục 1
git apply 02_admin.patch   # nội dung diff mục 2
python -m py_compile backend/app.py   # kiểm tra không lỗi
python -m backend.simulator.benchmark_evaluator   # chạy lại để có dữ liệu thật
```
