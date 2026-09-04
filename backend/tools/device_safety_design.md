# Safety Design — Điều Khiển Thiết Bị (GĐ1 Mục 12)

> **PoC hiện tại READ-ONLY** — tài liệu này thiết kế trước cho bước điều khiển sau.  
> Không cần code ngay. Chỉ cần thiết kế và review trong GĐ1.

---

## 1. Nguyên Tắc Bất Biến

- **Không bao giờ** gửi lệnh điều khiển thiết bị mà không có xác nhận 2 bước
- **LLM không được** tự quyết định gửi lệnh — chỉ đề xuất, người dùng phải confirm
- **IAM/Farm authorization** áp dụng cho cả lệnh ghi (write commands), không chỉ đọc
- **Audit log** cho mọi lệnh: ai, farm nào, lúc nào, kết quả — không tắt được
- **Timeout/rollback** khi thiết bị không phản hồi trong thời gian quy định

---

## 2. Luồng 2 Bước (Dry-Run → Confirm)

```
User: "Bật van tưới zone A trong 30 phút"
          │
          ▼
[IAM Check] → farm_id ∈ allowed_farm_ids? → DENY nếu không
          │
          ▼
[DRY-RUN] Chatbot trả về:
  "Sẽ thực hiện: Bật valve_A tại farm_001/zone_A trong 30 phút.
   Lượng nước ước tính: ~100 lít.
   Trạng thái van hiện tại: [online/offline/stale].
   ⚠️ Xác nhận? Gõ 'xác nhận' hoặc 'hủy'"
          │
          ▼
[User: "xác nhận"] → POST /api/tools/command
          │          Body: { farm_id, device_id, command, params, confirm_token }
          ▼
[IAM Check lần 2] → xác nhận lại quyền
          │
          ▼
[Execute] → Gửi lệnh tới NextFarm API
          │
          ├─ Success → Audit log + response
          ├─ Timeout (30s) → Rollback + alert + audit log
          └─ Error → Giữ nguyên trạng thái cũ + audit log
```

---

## 3. Audit Log Schema

```sql
CREATE TABLE IF NOT EXISTS device_command_audit (
    cmd_id          TEXT PRIMARY KEY,          -- UUID
    farm_id         TEXT NOT NULL,
    zone_id         TEXT,
    device_id       TEXT NOT NULL,
    command_type    TEXT NOT NULL,             -- 'irrigate', 'stop', 'toggle'
    params          JSONB,                     -- {duration_minutes, flow_rate...}
    requested_by    TEXT NOT NULL,             -- username
    requested_at    TIMESTAMP NOT NULL,
    confirmed_at    TIMESTAMP,                 -- NULL nếu còn pending
    executed_at     TIMESTAMP,
    result_status   TEXT,                      -- 'success', 'timeout', 'error', 'cancelled'
    result_detail   JSONB,
    system_version  TEXT,                      -- GĐ1 Mục 13: versioning
    router_version  TEXT,
    dry_run_shown   BOOLEAN DEFAULT false      -- dry-run đã được hiển thị chưa
);
```

---

## 4. IAM Extension cho Write Commands

```python
def check_device_write_access(
    farm_context: FarmContext,
    farm_id: str,
    device_id: str,
    command_type: str,
) -> AuthorizationResult:
    """
    Kiểm tra quyền ghi (write) cho lệnh điều khiển thiết bị.
    Cần role >= 'manager' (không chấp nhận 'viewer').
    """
    # Viewer không được điều khiển thiết bị
    if farm_context.role == "viewer":
        return AuthorizationResult(
            allowed=False,
            reason="Quyền 'viewer' không được phép điều khiển thiết bị"
        )
    # Tiếp tục check farm access như bình thường
    return check_farm_access(farm_context, farm_id, tool_name=f"write:{command_type}")
```

---

## 5. Timeout / Rollback Policy

| Tình huống | Hành động |
|-----------|-----------|
| Thiết bị không phản hồi trong 30s | Gửi lệnh `stop` + alert admin |
| Mất kết nối giữa chừng | Rollback về trạng thái trước + ghi audit |
| User không confirm sau 5 phút | Hủy dry-run, không thực thi |
| Partial failure (một số van OK, một số không) | Dừng toàn bộ + alert + audit |

---

## 6. API Endpoints (Thiết Kế Tương Lai)

```
POST /api/tools/command/dry-run
  Body: { farm_id, device_id, command, params }
  Response: { preview, dry_run_token, estimated_impact }

POST /api/tools/command/confirm
  Body: { dry_run_token, confirm: true }
  Response: { cmd_id, status, executed_at }

GET /api/tools/command/{cmd_id}/status
  Response: { status, result, audit_url }

GET /api/admin/device-audit
  Response: { commands: [...], total }
```

---

## 7. Checklist Trước Khi Kích Hoạt (Production)

- [ ] IAM write permission đã test: viewer bị chặn 100%
- [ ] Dry-run hiển thị đúng thông tin thiết bị (không stale > 10 phút)
- [ ] Audit log đã test: ghi đầy đủ mọi lệnh kể cả lệnh bị hủy
- [ ] Timeout mechanism đã test với mock device offline
- [ ] Rollback mechanism đã test
- [ ] Admin notification khi có lệnh thực thi
- [ ] Rate limit: tối đa N lệnh/phút/user
