import asyncio
import logging
import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Literal
# pyrefly: ignore [missing-import]
from fastapi import FastAPI, HTTPException, UploadFile, File, Header, Depends, Response
# pyrefly: ignore [missing-import]
from fastapi.staticfiles import StaticFiles
# pyrefly: ignore [missing-import]
from fastapi.responses import FileResponse, JSONResponse
# pyrefly: ignore [missing-import]
from fastapi.middleware.cors import CORSMiddleware
# pyrefly: ignore [missing-import]
from pydantic import BaseModel

from backend.config import APP_HOST, APP_PORT, DEBUG, validate_config, BASE_DIR
from backend.preprocessing.vietnamese_nlp import normalize_input, extract_season, extract_soil_type, extract_variety_name
from backend.router.query_router import route_question, synthesize_answer
from backend.layers.layer1_facts import get_fact, get_rice_variety, get_all_rice_varieties
from backend.layers.layer2_kg import find_suitable_varieties, find_pest_info, find_technique_info
from backend.layers.layer3_docs import semantic_search, get_chunk_count
from backend.utils.versioning import get_version_context, version_log_prefix, SYSTEM_VERSION
from backend.iam.iam import build_farm_context, check_farm_access
from backend.retrieval.retrieval_plan import execute_retrieval_plan
from backend.db.postgres import (
    save_chat_message, get_chat_history, get_all_sessions, get_user_sessions, delete_chat_session, save_feedback,
    create_user, get_user_by_username, get_user_by_id, get_all_users, update_user_block_status,
    delete_user, hash_password,
    link_alias_filename, save_pending_confirmation, get_pending_confirmation,
    delete_pending_confirmation, cleanup_expired_pending, mark_document_superseded,
    update_document_status,
)
from backend.ingestion.data_pipeline import (
    process_and_ingest_document, RAW_UPLOADS_DIR,
    check_upload_status, compute_content_hash, PENDING_UPLOADS_DIR,
)

logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Chatbot Nông Nghiệp AI — NextFarm v2.2",
    description="Hệ thống Chatbot Nông Nghiệp — Tư vấn đa dạng nông sản & Quản lý tri thức",
    version=SYSTEM_VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = BASE_DIR / "frontend"

# ─── GĐ2: Đăng ký Tool API Router ─────────────────────────────────────────
try:
    from backend.tools.tool_router import router as tool_api_router
    app.include_router(tool_api_router)
    logger.info("✅ Tool API Router đã đăng ký (/api/tools/*)")
except Exception as _tool_router_err:
    logger.warning(f"Tool API Router không khởi tạo được: {_tool_router_err}")


@app.on_event("startup")
async def startup_cleanup():
    """Dọn rác pending_confirmations hết hạn & pre-warm embedding model khi server khởi động."""
    try:
        n = cleanup_expired_pending(pending_uploads_dir=PENDING_UPLOADS_DIR)
        if n:
            logger.info(f"🧹 Startup cleanup: đã dọn {n} pending_confirmations hết hạn")
    except Exception as e:
        logger.warning(f"Startup cleanup lỗi (không ảnh hưởng hoạt động): {e}")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Tránh lỗi 404 Not Found khi trình duyệt tự động xin icon."""
    return Response(status_code=204)


# ─── Pydantic Models ──────────────────────────────────────────
class RegisterRequest(BaseModel):
    username: str
    password: str
    confirm_password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class BlockUserRequest(BaseModel):
    is_blocked: bool


class ChatRequest(BaseModel):
    session_id: Optional[str] = "default_session"
    username: Optional[str] = None
    question: str
    conversation_history: Optional[list] = []
    # GĐƆ2: Farm context cho tool calls
    farm_id: Optional[str] = None    # farm_id do frontend truyền — KHÔNG để LLM tự sinh
    zone_id: Optional[str] = None    # zone_id trong farm


class FeedbackRequest(BaseModel):
    session_id: Optional[str] = "default_session"
    question: str
    answer: str
    rating: int  # 1 hoặc -1
    feedback_text: Optional[str] = None



class UploadConfirmRequest(BaseModel):
    temp_id: str
    decision: Literal["accept", "reject"]


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    source: Optional[str] = None
    is_partial_match: bool = False
    partial_match_warning: Optional[str] = None
    question_type: Optional[str] = None
    layer_used: Optional[str] = None
    clarification_needed: bool = False
    clarification_question: Optional[str] = None
    # GĐƆ2: Thêm thông tin nguồn và cảnh báo
    tool_sources: Optional[list] = None          # Danh sách tool đã gọi
    retrieval_sources: Optional[list] = None     # Danh sách nguồn dữ liệu đã dùng
    freshness_warnings: Optional[list] = None    # Cảnh báo freshness từ sensor
    requires_clarification: bool = False         # Fail-closed: cần thêm điều kiện


# ─── Auth Endpoints ───────────────────────────────────────────
@app.post("/api/auth/register")
async def register(req: RegisterRequest):
    """Đăng ký tài khoản mới."""
    username = req.username.strip()
    password = req.password.strip()
    confirm = req.confirm_password.strip()

    if not username or not password:
        raise HTTPException(status_code=400, detail="Vui lòng điền đầy đủ tài khoản và mật khẩu.")
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="Tài khoản phải có ít nhất 3 ký tự.")
    if username.lower() == "admin":
        raise HTTPException(status_code=400, detail="Tài khoản 'admin' đã được tạo sẵn từ trước (mật khẩu mặc định: admin), không cần đăng ký.")
    if password != confirm:
        raise HTTPException(status_code=400, detail="Mật khẩu nhập lại không trùng khớp.")

    existing = get_user_by_username(username)
    if existing:
        raise HTTPException(status_code=400, detail="Tên tài khoản này đã tồn tại.")

    try:
        user = create_user(username=username, password=password, role="user")
        return {
            "status": "success",
            "message": "Đăng ký tài khoản thành công!",
            "user": {"username": user["username"], "role": user["role"]}
        }
    except Exception as e:
        logger.error(f"Lỗi đăng ký user: {e}")
        raise HTTPException(status_code=500, detail="Lỗi hệ thống khi đăng ký tài khoản.")


@app.post("/api/auth/login")
async def login(req: LoginRequest):
    """Đăng nhập tài khoản."""
    username = req.username.strip()
    password = req.password.strip()

    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=400, detail="Tài khoản hoặc mật khẩu không chính xác.")

    if hash_password(password) != user["password_hash"]:
        raise HTTPException(status_code=400, detail="Tài khoản hoặc mật khẩu không chính xác.")

    if user.get("is_blocked"):
        raise HTTPException(status_code=403, detail="Tài khoản của bạn đã bị khóa. Vui lòng liên hệ Admin.")

    token = f"token_{user['username']}_{user['user_id']}"
    return {
        "status": "success",
        "message": "Đăng nhập thành công!",
        "token": token,
        "user": {
            "user_id": user["user_id"],
            "username": user["username"],
            "role": user["role"]
        }
    }


@app.get("/api/auth/me")
async def get_me(username: Optional[str] = None):
    """Lấy thông tin tài khoản hiện tại."""
    if not username:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng")
    return {
        "user_id": user["user_id"],
        "username": user["username"],
        "role": user["role"],
        "is_blocked": user["is_blocked"]
    }


# ─── Admin Dashboard Endpoints ────────────────────────────────
@app.get("/api/admin/users")
async def admin_list_users(username: Optional[str] = None):
    """Admin: Danh sách người dùng."""
    if username != "admin":
        user = get_user_by_username(username) if username else None
        if not user or user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Yêu cầu quyền Quản trị viên (Admin).")

    users = get_all_users()
    return {"users": users}


@app.post("/api/admin/users/{user_id}/block")
async def admin_block_user(user_id: int, req: BlockUserRequest, username: Optional[str] = None):
    """Admin: Chặn hoặc bỏ chặn tài khoản."""
    if username != "admin":
        user = get_user_by_username(username) if username else None
        if not user or user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Yêu cầu quyền Admin.")

    target_user = get_user_by_id(user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng.")
    if target_user["username"] == "admin":
        raise HTTPException(status_code=400, detail="Không thể chặn tài khoản admin hệ thống.")

    ok = update_user_block_status(user_id, req.is_blocked)
    if not ok:
        raise HTTPException(status_code=500, detail="Lỗi khi cập nhật trạng thái người dùng.")
    action_text = "chặn" if req.is_blocked else "bỏ chặn"
    return {"status": "success", "message": f"Đã {action_text} tài khoản {target_user['username']}."}


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(user_id: int, username: Optional[str] = None):
    """Admin: Xoá tài khoản người dùng."""
    if username != "admin":
        user = get_user_by_username(username) if username else None
        if not user or user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Yêu cầu quyền Admin.")

    target_user = get_user_by_id(user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng.")
    if target_user["username"] == "admin":
        raise HTTPException(status_code=400, detail="Không thể xoá tài khoản admin hệ thống.")

    ok = delete_user(user_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Lỗi khi xoá người dùng.")
    return {"status": "success", "message": f"Đã xoá tài khoản {target_user['username']}."}


@app.post("/api/admin/upload-data")
async def admin_upload_data(file: UploadFile = File(...), username: Optional[str] = None):
    """Admin: Upload file dữ liệu thô (PDF, Word, TXT, MD, JSON) -> pipeline -> chunks -> DB.

    Phân loại 5 case theo content hash:
    - Case 1 'process_new'              : Tài liệu mới — xử lý bình thường.
    - Case 2 'auto_continue'            : Nội dung đã có, dở dang — ingest lại từ đầu.
    - Case 3 'confirm_duplicate_content': Nội dung trùng, tên khác — hỏi admin (HTTP 409).
    - Case 4 'confirm_content_changed'  : Cùng tên, nội dung khác — hỏi admin (HTTP 409).
    - Case 5 'already_complete'         : Nội dung + tên đã có — bỏ qua (HTTP 200).
    """
    if username != "admin":
        user = get_user_by_username(username) if username else None
        if not user or user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Yêu cầu quyền Admin.")

    if not file.filename:
        raise HTTPException(status_code=400, detail="Vui lòng chọn file dữ liệu.")

    file_bytes = await file.read()
    filename = file.filename

    # Kiểm tra trạng thái upload trước khi lưu file
    status_info = check_upload_status(file_bytes, filename)
    action = status_info["action"]

    # ─── Case 5: Đã tồn tại hoàn toàn (tên + nội dung) ───
    if action == "already_complete":
        return JSONResponse(status_code=200, content={
            "status": "already_complete",
            "doc_id": status_info["doc_id"],
            "note": "Tài liệu này đã tồn tại đầy đủ (tên đã được ghi nhận trước đó), không cần xử lý lại.",
        })

    # ─── Case 2: Tiếp tục xử lý dở dang ───
    if action == "auto_continue":
        doc_id = status_info["doc_id"]
        # Lưu file vào RAW_UPLOADS (ghi đè nếu đã có)
        save_path = RAW_UPLOADS_DIR / filename
        with open(save_path, "wb") as f:
            f.write(file_bytes)
        try:
            content_hash = status_info.get("content_hash") or compute_content_hash(file_bytes)
            result = process_and_ingest_document(
                str(save_path),
                custom_title=filename,
                content_hash=content_hash,
                original_filename=filename,
            )
            result["note"] = "Tiếp tục xử lý tài liệu dở dang (ingest lại từ đầu — không còn retry OCR)."
            return result
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            logger.error(f"Lỗi auto_continue: {e}")
            raise HTTPException(status_code=500, detail=f"Lỗi tiếp tục xử lý: {str(e)}")

    # ─── Case 3 & 4: Cần xác nhận từ admin ───
    if action in ("confirm_duplicate_content", "confirm_content_changed"):
        temp_id = str(uuid.uuid4())
        temp_file_path = PENDING_UPLOADS_DIR / f"{temp_id}.pdf"
        with open(temp_file_path, "wb") as f:
            f.write(file_bytes)

        expires_at = datetime.utcnow() + timedelta(hours=24)
        context = {
            **status_info,
            "filename": filename,
            "temp_file_path": str(temp_file_path),
        }
        save_pending_confirmation(temp_id, action, context, expires_at)

        if action == "confirm_duplicate_content":
            detail_msg = (
                f"Nội dung file này đã tồn tại trong hệ thống (doc_id: {status_info['doc_id']}) "
                f"với các tên: {status_info.get('existing_filenames', [])}. "
                f"Gọi POST /api/admin/upload-data/confirm để thêm alias hoặc hủy."
            )
        else:
            detail_msg = (
                f"File cùng tên nhưng nội dung đã thay đổi so với bản đã có "
                f"(old_doc_id: {status_info['old_doc_id']}). "
                f"Gọi POST /api/admin/upload-data/confirm để thay thế hoặc giữ nguyên."
            )

        return JSONResponse(status_code=409, content={
            "status": action,
            "temp_id": temp_id,
            "detail": detail_msg,
            **{k: v for k, v in status_info.items() if k != "action"},
            "expires_at": expires_at.isoformat(),
        })

    # ─── Case 1: Tài liệu mới hoàn toàn ───
    save_path = RAW_UPLOADS_DIR / filename
    try:
        with open(save_path, "wb") as f:
            f.write(file_bytes)

        content_hash = status_info.get("content_hash") or compute_content_hash(file_bytes)
        result = process_and_ingest_document(
            str(save_path),
            custom_title=filename,
            content_hash=content_hash,
            original_filename=filename,
        )

        if result.get("status") == "partial_failure":
            return JSONResponse(status_code=207, content=result)

        return result
    except Exception as e:
        logger.error(f"Lỗi upload dữ liệu: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi xử lý file: {str(e)}")


@app.post("/api/admin/upload-data/confirm")
async def admin_confirm_upload(req: UploadConfirmRequest, username: Optional[str] = None):
    """Admin: Xác nhận hoặc từ chối tài liệu đang chờ (case 3, 4).

    Body: { "temp_id": str, "decision": "accept" | "reject" }

    Case 3 (confirm_duplicate_content):
      - accept : Thêm tên file mới vào alias, không OCR lại.
      - reject : Hủy, không lưu gì thêm.

    Case 4 (confirm_content_changed):
      - accept : Ingest bản mới trước; nếu thành công thì xoá chunk cũ và đánh dấu
                 bản cũ là superseded. Nếu partial_failure thì GIỮ bản cũ, báo admin retry.
      - reject : Giữ nguyên dữ liệu cũ, không thay đổi gì.
    """
    if username != "admin":
        user = get_user_by_username(username) if username else None
        if not user or user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Yêu cầu quyền Admin.")

    pending = get_pending_confirmation(req.temp_id)
    if not pending:
        raise HTTPException(
            status_code=404,
            detail="Yêu cầu không tồn tại hoặc đã hết hạn (24h). Vui lòng upload lại file."
        )

    action_type = pending["action_type"]
    context = pending["context_json"]
    if not isinstance(context, dict):
        import json as _json
        context = _json.loads(context)

    temp_file_path = Path(context.get("temp_file_path", ""))
    filename = context.get("filename", "")

    def _cleanup_temp():
        """Xoá file tạm và pending record sau khi xử lý xong."""
        if temp_file_path.exists():
            try:
                temp_file_path.unlink()
            except Exception as e:
                logger.warning(f"Không xoá được file tạm {temp_file_path}: {e}")
        delete_pending_confirmation(req.temp_id)

    # ═══ CASE 3: confirm_duplicate_content ═══
    if action_type == "confirm_duplicate_content":
        doc_id = context.get("doc_id")

        if req.decision == "reject":
            _cleanup_temp()
            return {"status": "rejected_duplicate", "message": "Hủy upload. Dữ liệu không được thay đổi."}

        # accept: chỉ thêm alias, không OCR lại
        ok = link_alias_filename(doc_id, filename)
        _cleanup_temp()
        if ok:
            return {
                "status": "success",
                "action": "alias_added",
                "doc_id": doc_id,
                "new_filename": filename,
                "message": f"Tên '{filename}' đã được liên kết với tài liệu đã có. Không có OCR nào được gọi thêm.",
            }
        else:
            raise HTTPException(status_code=500, detail="Lỗi khi lưu alias. Vui lòng thử lại.")

    # ═══ CASE 4: confirm_content_changed ═══
    if action_type == "confirm_content_changed":
        old_doc_id = context.get("old_doc_id")

        if req.decision == "reject":
            _cleanup_temp()
            return {
                "status": "update_cancelled",
                "message": "Hủy cập nhật. Dữ liệu cũ không được thay đổi.",
            }

        # accept: ingest bản mới TRƯỚC, xoá cũ SAU khi xác nhận thành công
        if not temp_file_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"File tạm không tìm thấy. Vui lòng upload lại."
            )

        try:
            new_content_hash = compute_content_hash(temp_file_path.read_bytes())
            # Lưu vào RAW_UPLOADS và ingest bản mới
            new_save_path = RAW_UPLOADS_DIR / filename
            import shutil
            shutil.copy2(str(temp_file_path), str(new_save_path))

            new_result = process_and_ingest_document(
                str(new_save_path),
                custom_title=filename,
                content_hash=new_content_hash,
                original_filename=filename,
            )

            new_status = new_result.get("status")
            new_doc_id = new_result.get("doc_id")

            if new_status == "success":
                # Ingest thành công — bây giờ mới an toàn xoá dữ liệu cũ
                try:
                    from backend.db.chroma_db import get_collection
                    collection = get_collection()
                    collection.delete(where={"source_document_id": old_doc_id})
                    logger.info(f"🗑️ Đã xoá chunk cũ của {old_doc_id} trong ChromaDB")
                except Exception as e:
                    logger.error(f"Lỗi xoá chunk cũ ChromaDB: {e}")

                mark_document_superseded(old_doc_id)
                _cleanup_temp()

                return {
                    "status": "success",
                    "action": "content_replaced",
                    "new_doc_id": new_doc_id,
                    "old_doc_id_superseded": old_doc_id,
                    "message": f"Tài liệu đã được thay thế thành công. Bản cũ ({old_doc_id}) đã được đánh dấu superseded.",
                    "extract_stats": new_result.get("extract_stats"),
                }

            elif new_status == "partial_failure":
                # Ingest mới thất bại giữa chừng — GIỮ NGUYÊN bản cũ
                # Giữ lại file tạm (có thể cần cho retry-ocr tiếp)
                # CHỈ xoá pending record để giải phóng slot (admin sẽ upload lại khi cần)
                delete_pending_confirmation(req.temp_id)
                logger.warning(
                    f"⚠️ Ingest bản mới partial_failure. Bản cũ {old_doc_id} vẫn đang hoạt động."
                )
                return JSONResponse(status_code=207, content={
                    "status": "new_version_partial_failure",
                    "new_doc_id": new_doc_id,
                    "old_doc_id_still_active": old_doc_id,
                    "message": (
                        "Ingest phiên bản mới thất bại. Bản cũ vẫn đang được sử dụng. "
                        f"Vui lòng upload lại file '{filename}' để thử lại."
                    ),
                })

            else:
                # error kác
                _cleanup_temp()
                raise HTTPException(status_code=500, detail=f"Lỗi ingest: {new_result.get('message', 'Không rõ')}")

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Lỗi confirm_content_changed accept: {e}")
            raise HTTPException(status_code=500, detail=f"Lỗi xử lý: {str(e)}")

    raise HTTPException(status_code=400, detail=f"action_type không hợp lệ: {action_type}")



@app.get("/api/admin/key-status")
async def admin_key_status(username: Optional[str] = None):
    """Admin: Xem trạng thái pool Gemini API Keys theo thời gian thực.

    Trả về danh sách tất cả keys với:
    - key_index    : Số thứ tự key (1-based)
    - key_preview  : 6 ký tự cuối của key (để nhận dạng, không lộ key đầy đủ)
    - status       : 'active' | 'rate_limited' | 'invalid'
    - cooldown_remaining_seconds: Giây còn lại trước khi key rate_limited được phục hồi
    - total_calls  : Tổng số lần gọi thành công
    - total_errors : Tổng số lần gặp lỗi
    - rotations_caused: Số lần key này gây ra rotation sang key khác
    - is_current   : Key này đang được dùng không?
    """
    if username != "admin":
        user = get_user_by_username(username) if username else None
        if not user or user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Yêu cầu quyền Admin.")

    from backend.utils.gemini_client import key_manager, AllKeysExhaustedError
    if key_manager is None:
        raise HTTPException(
            status_code=503,
            detail="GeminiKeyManager chưa khởi tạo. Kiểm tra GEMINI_API_KEY_1..4 trong .env"
        )

    key_statuses = key_manager.status()
    total_keys = len(key_statuses)
    active_count = sum(1 for k in key_statuses if k["status"] == "active")
    rate_limited_count = sum(1 for k in key_statuses if k["status"] == "rate_limited")
    invalid_count = sum(1 for k in key_statuses if k["status"] == "invalid")

    return {
        "summary": {
            "total_keys": total_keys,
            "active": active_count,
            "rate_limited": rate_limited_count,
            "invalid": invalid_count,
            "pool_healthy": active_count > 0,
        },
        "keys": key_statuses,
    }


# ─── Benchmark / Đo lường ──────────────────────────────────────────────────
class BenchmarkRunRequest(BaseModel):
    questions: list  # [{id, question, ground_truth}, ...]


def _parse_qe_file() -> list:
    """
    Parse file Q&E.txt tại thư mục gốc chatbot.
    Format:
        N,câu hỏi: <nội dung>
         trả lời: <nội dung> (có thể nhiều dòng)
    Trả về list[{id, question, ground_truth}]
    """
    qe_path = BASE_DIR / "Q&E.txt"
    if not qe_path.exists():
        return []

    text = qe_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()

    pairs = []
    current_id = None
    current_q = None
    current_a_lines = []

    def flush():
        if current_id is not None and current_q:
            pairs.append({
                "id": current_id,
                "question": current_q.strip(),
                "ground_truth": " ".join(current_a_lines).strip(),
            })

    import re
    q_pattern = re.compile(r"^(\d+)\s*,\s*câu\s*hỏi\s*:\s*(.+)", re.IGNORECASE)
    a_pattern = re.compile(r"^\s*trả\s*lời\s*:\s*(.+)", re.IGNORECASE)
    a_continue = re.compile(r"^\s+(.+)")

    for line in lines:
        qm = q_pattern.match(line)
        if qm:
            flush()
            current_id = int(qm.group(1))
            current_q = qm.group(2)
            current_a_lines = []
            continue

        am = a_pattern.match(line)
        if am:
            current_a_lines = [am.group(1)]
            continue

        # Continuation line (indented) — ghép vào answer đang xây dựng
        if current_a_lines and (line.startswith(" ") or line.startswith("\t")):
            cont = line.strip()
            if cont:
                current_a_lines.append(cont)

    flush()
    return pairs


JUDGE_PROMPT_TEMPLATE = """Bạn là giám khảo AI chuyên đánh giá chất lượng câu trả lời của chatbot nông nghiệp.

Câu hỏi: {question}

Đáp án chuẩn (Ground Truth):
{ground_truth}

Đáp án của Chatbot:
{chatbot_answer}

Hãy chấm điểm theo 2 tiêu chí và trả về JSON thuần túy (không markdown, không giải thích ngoài):

{{
  "factual_score": <số nguyên 0-100, mức độ chính xác số liệu, tên gọi, thông số kỹ thuật>,
  "semantic_score": <số nguyên 0-100, mức độ đúng ý nghĩa và trọng tâm>,
  "retrieval_note": "<nhận xét ngắn gọn về khả năng tìm kiếm và lấy dữ liệu đúng>",
  "generation_note": "<nhận xét ngắn gọn về chất lượng tổng hợp và diễn đạt>",
  "reasoning": "<lý do xếp loại tổng thể trong 1-2 câu>"
}}

Lưu ý:
- factual_score: 100 = tất cả số liệu/thông số hoàn toàn chính xác; 0 = sai hoàn toàn hoặc bịa đặt.
- semantic_score: 100 = trả lời đúng trọng tâm, đủ ý; 0 = lạc đề hoặc không liên quan.
- Chỉ trả về JSON, không có text nào khác."""


def _grade_score(score: float) -> tuple:
    """Trả về (tên xếp loại, css class key)"""
    if score >= 90:
        return ("Xuất sắc", "excellent")
    if score >= 80:
        return ("Tốt", "good")
    if score >= 70:
        return ("Khá", "fair")
    if score >= 50:
        return ("Chưa đạt", "poor")
    return ("Kém", "fail")

BENCHMARK_RESULTS_FILE = BASE_DIR / "benchmark_results.json"


def _normalize_question(q: str) -> str:
    """Chuẩn hoá câu hỏi để so sánh: thường hoá, cắt whitespace."""
    return " ".join(q.lower().strip().split())


def _question_similarity(a: str, b: str) -> float:
    """Tính độ tương đồng giữa 2 chuỗi (0.0 - 1.0)."""
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio()


def _load_benchmark_results() -> dict:
    """Nạp kết quả benchmark từ file JSON."""
    if BENCHMARK_RESULTS_FILE.exists():
        try:
            return json.loads(BENCHMARK_RESULTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"results": {}}


def _save_benchmark_results(data: dict):
    """Lưu kết quả benchmark ra file JSON."""
    BENCHMARK_RESULTS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def _is_question_match(user_q: str, qe_q: str) -> tuple[bool, float]:
    """
    So sánh câu hỏi của user và câu trong Q&E.txt:
    dùng kết hợp SequenceMatcher ratio và token set overlap ratio.
    """
    import difflib
    u_norm = _normalize_question(user_q)
    q_norm = _normalize_question(qe_q)
    
    ratio = difflib.SequenceMatcher(None, u_norm, q_norm).ratio()
    if ratio >= 0.70:
        return True, ratio
        
    u_words = set(u_norm.split())
    q_words = set(q_norm.split())
    if not u_words or not q_words:
        return False, 0.0
        
    jaccard = len(u_words & q_words) / len(u_words | q_words)
    contain_ratio = len(u_words & q_words) / min(len(u_words), len(q_words))
    
    if jaccard >= 0.55 or contain_ratio >= 0.75:
        return True, max(ratio, jaccard)
        
    return False, ratio


async def _check_and_record_qe_match(question: str, answer: str):
    """
    Background: nếu câu hỏi của user trùng với một câu trong Q&E.txt,
    tự động chấm điểm duy nhất cho câu trùng đó và lưu kết quả.
    """
    try:
        pairs = _parse_qe_file()
        if not pairs:
            return

        best_match = None
        best_sim = 0.0

        for pair in pairs:
            matched, sim = _is_question_match(question, pair["question"])
            if matched and sim > best_sim:
                best_sim = sim
                best_match = pair

        if not best_match:
            return

        logger.info(f"ℹ️  Q&E match: câu #{best_match['id']} (sim={best_sim:.2f}) — bắt đầu chấm điểm...")

        from backend.utils.gemini_client import call_with_rotation, AllKeysExhaustedError
        # pyrefly: ignore [missing-import]
        from google import genai as _genai
        from backend.config import GEMINI_SYNTHESIS_MODEL

        judge_prompt = JUDGE_PROMPT_TEMPLATE.format(
            question=best_match["question"],
            ground_truth=best_match["ground_truth"],
            chatbot_answer=answer,
        )

        def _call_judge(client: _genai.Client) -> str:
            resp = client.models.generate_content(
                model=GEMINI_SYNTHESIS_MODEL,
                contents=judge_prompt,
                config={
                    "temperature": 0.1,
                    "max_output_tokens": 1024,
                    "response_mime_type": "application/json",
                },
            )
            return resp.text.strip() if resp.text else ""

        judge_raw = await asyncio.to_thread(call_with_rotation, _call_judge)
        judge_text = judge_raw.strip()
        if judge_text.startswith("```"):
            judge_text = "\n".join(judge_text.split("\n")[1:])
            judge_text = judge_text.rsplit("```", 1)[0].strip()

        judge_data = json.loads(judge_text)

        factual = max(0.0, min(100.0, float(judge_data.get("factual_score", 0))))
        semantic = max(0.0, min(100.0, float(judge_data.get("semantic_score", 0))))
        answer_correctness = round(factual * 0.6 + semantic * 0.4, 1)
        grade_label, grade_key = _grade_score(answer_correctness)

        data = _load_benchmark_results()
        qid = str(best_match["id"])
        data["results"][qid] = {
            "id": best_match["id"],
            "question": best_match["question"],
            "ground_truth": best_match["ground_truth"],
            "user_question": question,          # câu người dùng đã hỏi thực sự
            "chatbot_answer": answer,
            "factual_score": round(factual, 1),
            "semantic_score": round(semantic, 1),
            "answer_correctness": answer_correctness,
            "grade_label": grade_label,
            "grade_key": grade_key,
            "retrieval_note": judge_data.get("retrieval_note", ""),
            "generation_note": judge_data.get("generation_note", ""),
            "reasoning": judge_data.get("reasoning", ""),
            "triggered_at": datetime.now().isoformat(),
            "similarity_score": round(best_sim, 3),
        }
        _save_benchmark_results(data)
        logger.info(f"✅ Benchmark: câu #{best_match['id']} được lưu — điểm={answer_correctness}%")

    except Exception as e:
        logger.warning(f"Benchmark auto-check lỗi (không ảnh hưởng chat): {e}")


def _enqueue_benchmark_check(question: str, answer: str):
    """
    GĐ1 Mục 10: Ghi benchmark job vào DB thay vì asyncio.create_task.
    Durable: không mất task khi worker restart.
    Background worker định kỳ poll bảng benchmark_jobs và xử lý.
    Fallback: nếu DB lỗi thì gọi asyncio.create_task như cũ.
    """
    import uuid as _uuid
    from backend.db.postgres import get_cursor
    from backend.utils.versioning import SYSTEM_VERSION, ROUTER_PROMPT_VERSION

    try:
        job_id = f"bm_{_uuid.uuid4().hex[:12]}"
        payload = {
            "question": question,
            "answer": answer,
            "system_version": SYSTEM_VERSION,
            "router_version": ROUTER_PROMPT_VERSION,
        }
        with get_cursor() as cur:
            cur.execute("""
                INSERT INTO benchmark_jobs (job_id, status, questions, created_at, updated_at)
                VALUES (%s, 'pending', %s, NOW(), NOW())
            """, (job_id, json.dumps(payload, ensure_ascii=False)))
        logger.debug(f"Benchmark job enqueued: {job_id}")

        # Vẫn chạy async ngay để không trễ (ưu tiên speed hơn durability trong PoC)
        asyncio.create_task(_check_and_record_qe_match(question, answer))

    except Exception as e:
        logger.warning(f"_enqueue_benchmark_check DB error, falling back to create_task: {e}")
        raise  # Để caller dùng fallback


async def _get_chatbot_answer(question: str) -> str:
    """Lấy câu trả lời từ chatbot bằng cách gọi thẳng hàm chat() endpoint."""
    try:
        req = ChatRequest(
            session_id="benchmark_internal",
            username="admin",
            question=question,
            conversation_history=[],
        )
        resp = await chat(req)
        return resp.answer
    except Exception as e:
        logger.error(f"Lỗi _get_chatbot_answer: {e}")
        return f"[Lỗi xử lý: {str(e)}]"


@app.get("/api/admin/benchmark/results")
async def benchmark_get_results(username: Optional[str] = None):
    """
    Admin: Lấy kết quả đánh giá benchmark theo các câu hỏi trong Q&E.txt.
    Các câu chưa được người dùng hỏi trùng sẽ có trạng thái 'pending'.
    Các câu đã được hỏi trùng sẽ có điểm số và xếp loại chi tiết ('evaluated').
    """
    if username != "admin":
        user = get_user_by_username(username) if username else None
        if not user or user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Yêu cầu quyền Admin.")

    pairs = _parse_qe_file()
    if not pairs:
        raise HTTPException(status_code=404, detail="Không tìm thấy hoặc không parse được file Q&E.txt.")

    saved_data = _load_benchmark_results().get("results", {})

    combined = []
    evaluated_count = 0
    total_score = 0.0

    for pair in pairs:
        qid = str(pair["id"])
        if qid in saved_data:
            res = saved_data[qid]
            evaluated_count += 1
            total_score += res.get("answer_correctness", 0.0)
            combined.append({
                "id": pair["id"],
                "question": pair["question"],
                "ground_truth": pair["ground_truth"],
                "status": "evaluated",
                **res
            })
        else:
            combined.append({
                "id": pair["id"],
                "question": pair["question"],
                "ground_truth": pair["ground_truth"],
                "status": "pending",
                "chatbot_answer": None,
                "factual_score": None,
                "semantic_score": None,
                "answer_correctness": None,
                "grade_label": "Chưa kích hoạt",
                "grade_key": "pending",
                "retrieval_note": None,
                "generation_note": None,
                "reasoning": "Chưa có người dùng hỏi câu trùng với câu này.",
            })

    avg_score = round(total_score / evaluated_count, 1) if evaluated_count > 0 else 0.0

    return {
        "total_questions": len(pairs),
        "evaluated_count": evaluated_count,
        "average_score": avg_score,
        "questions": combined,
    }


@app.delete("/api/admin/benchmark/results")
async def benchmark_reset_results(username: Optional[str] = None):
    """Admin: Reset xoá toàn bộ kết quả benchmark đã lưu."""
    if username != "admin":
        user = get_user_by_username(username) if username else None
        if not user or user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Yêu cầu quyền Admin.")

    if BENCHMARK_RESULTS_FILE.exists():
        try:
            BENCHMARK_RESULTS_FILE.unlink()
        except Exception as e:
            logger.error(f"Lỗi xoá file benchmark_results.json: {e}")
            raise HTTPException(status_code=500, detail="Không thể xoá file kết quả.")
    return {"status": "success", "message": "Đã xoá toàn bộ kết quả đo lường."}


@app.get("/api/admin/benchmark/questions")
async def benchmark_get_questions(username: Optional[str] = None):
    """Admin: Lấy danh sách câu hỏi từ Q&E.txt để benchmark."""
    if username != "admin":
        user = get_user_by_username(username) if username else None
        if not user or user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Yêu cầu quyền Admin.")

    pairs = _parse_qe_file()
    if not pairs:
        raise HTTPException(status_code=404, detail="Không tìm thấy hoặc không parse được file Q&E.txt.")

    return {"questions": pairs, "total": len(pairs)}


@app.post("/api/admin/benchmark/run")
async def benchmark_run(req: BenchmarkRunRequest, username: Optional[str] = None):
    """
    Admin: Chạy benchmark — đánh giá chatbot theo từng câu hỏi.
    Trả về NDJSON streaming: mỗi dòng là 1 JSON kết quả của 1 câu.
    """
    # pyrefly: ignore [missing-import]
    from fastapi.responses import StreamingResponse
    import asyncio

    if username != "admin":
        user = get_user_by_username(username) if username else None
        if not user or user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Yêu cầu quyền Admin.")

    questions = req.questions
    if not questions:
        raise HTTPException(status_code=400, detail="Danh sách câu hỏi rỗng.")

    from backend.utils.gemini_client import call_with_rotation, AllKeysExhaustedError

    async def generate():
        for item in questions:
            qid = item.get("id", 0)
            question = item.get("question", "")
            ground_truth = item.get("ground_truth", "")

            result = {
                "id": qid,
                "question": question,
                "ground_truth": ground_truth,
                "chatbot_answer": "",
                "factual_score": 0,
                "semantic_score": 0,
                "answer_correctness": 0.0,
                "grade_label": "Kém",
                "grade_key": "fail",
                "retrieval_note": "",
                "generation_note": "",
                "reasoning": "",
                "error": None,
            }

            try:
                # Bước 1: Lấy câu trả lời từ chatbot
                chatbot_answer = await _get_chatbot_answer(question)
                result["chatbot_answer"] = chatbot_answer

                # Bước 2: Chấm điểm bằng LLM
                judge_prompt = JUDGE_PROMPT_TEMPLATE.format(
                    question=question,
                    ground_truth=ground_truth,
                    chatbot_answer=chatbot_answer,
                )

                # pyrefly: ignore [missing-import]
                from google import genai as _genai
                from backend.config import GEMINI_SYNTHESIS_MODEL

                def _call_judge(client: _genai.Client) -> str:
                    resp = client.models.generate_content(
                        model=GEMINI_SYNTHESIS_MODEL,
                        contents=judge_prompt,
                        config={
                            "temperature": 0.1,
                            "max_output_tokens": 400,
                            "response_mime_type": "application/json",
                        }
                    )
                    return resp.text.strip()

                judge_raw = call_with_rotation(_call_judge)

                # Parse JSON từ judge response
                judge_text = judge_raw.strip()
                # Bỏ markdown code fences nếu có
                if judge_text.startswith("```"):
                    judge_text = "\n".join(judge_text.split("\n")[1:])
                    judge_text = judge_text.rsplit("```", 1)[0].strip()

                judge_data = json.loads(judge_text)

                factual = float(judge_data.get("factual_score", 0))
                semantic = float(judge_data.get("semantic_score", 0))
                # Clamp [0, 100]
                factual = max(0.0, min(100.0, factual))
                semantic = max(0.0, min(100.0, semantic))

                answer_correctness = round(factual * 0.6 + semantic * 0.4, 1)
                grade_label, grade_key = _grade_score(answer_correctness)

                result.update({
                    "factual_score": round(factual, 1),
                    "semantic_score": round(semantic, 1),
                    "answer_correctness": answer_correctness,
                    "grade_label": grade_label,
                    "grade_key": grade_key,
                    "retrieval_note": judge_data.get("retrieval_note", ""),
                    "generation_note": judge_data.get("generation_note", ""),
                    "reasoning": judge_data.get("reasoning", ""),
                })

            except AllKeysExhaustedError:
                result["error"] = "Đã cạn API key Gemini. Vui lòng thử lại sau."
            except json.JSONDecodeError as e:
                result["error"] = f"Không parse được kết quả chấm điểm: {e}"
            except Exception as e:
                logger.error(f"Benchmark lỗi câu {qid}: {e}")
                result["error"] = str(e)

            yield json.dumps(result, ensure_ascii=False) + "\n"
            # Nhường vòng lặp event loop để không block
            await asyncio.sleep(0)

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"X-Content-Type-Options": "nosniff"},
    )



@app.get("/health")
async def health_check():
    """Kiểm tra trạng thái hệ thống."""
    from backend.db.postgres import test_connection as pg_test
    from backend.db.chroma_db import test_connection as chroma_test

    pg_ok = False
    chroma_ok = False

    try:
        pg_ok = pg_test()
    except Exception:
        pass

    try:
        chroma_ok = chroma_test()
    except Exception:
        pass

    chunk_count = 0
    try:
        chunk_count = get_chunk_count()
    except Exception:
        pass

    status = "ok" if (pg_ok and chroma_ok) else "degraded"
    config_errors = validate_config()

    return {
        "status": status,
        "postgresql": "connected" if pg_ok else "disconnected",
        "chromadb": "connected" if chroma_ok else "disconnected",
        "chunks_loaded": chunk_count,
        "config_errors": config_errors,
        "message": "Hệ thống sẵn sàng" if status == "ok" else "Một số thành phần chưa kết nối"
    }


# ─── Monitoring & Stats Endpoints ─────────────────────────────────────────────

@app.get("/api/monitoring/stats")
async def monitoring_stats(username: Optional[str] = None):
    """
    Lấy toàn bộ metric giám sát vận hành hệ thống:
    - Tool failure rate, latency p95 từng tool
    - IAM cross-farm deny rate và log gần nhất
    - Sensor quality distribution (fresh/stale/missing)
    - Calibration results (từ calibration_results.json)
    - Acceptance benchmark status (từ acceptance_results.json)

    Yêu cầu quyền admin.
    """
    if username != "admin":
        user = get_user_by_username(username) if username else None
        if not user or user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Yêu cầu quyền Admin.")

    try:
        from backend.monitoring import get_monitoring_stats
        stats = get_monitoring_stats()
        return stats
    except Exception as e:
        logger.error(f"monitoring_stats error: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi thu thập metric: {e}")


@app.get("/api/monitoring/audit_log")
async def monitoring_audit_log(username: Optional[str] = None, limit: int = 50):
    """
    Lấy log audit các lần cross-farm bị chặn (IAM deny).
    Log này không thể bị xóa qua API — đảm bảo tính toàn vẹn kiểm toán.
    Yêu cầu quyền admin.
    """
    if username != "admin":
        user = get_user_by_username(username) if username else None
        if not user or user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Yêu cầu quyền Admin.")

    try:
        from backend.monitoring import _cross_farm_denies, _iam_total_checks, _iam_deny_count
        return {
            "total_iam_checks": _iam_total_checks,
            "total_deny_count": _iam_deny_count,
            "deny_rate_pct": round(_iam_deny_count / _iam_total_checks * 100, 1) if _iam_total_checks else 0.0,
            "recent_denies": _cross_farm_denies[-limit:],
            "note": "Log này không thể xóa qua API. In-memory — reset khi server restart.",
        }
    except Exception as e:
        logger.error(f"monitoring_audit_log error: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi đọc audit log: {e}")


# ─── Chat Endpoint ────────────────────────────────────────────
@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Xử lý câu hỏi với xác thực tài khoản & lưu lịch sử cá nhân hóa.
    """
    if request.username:
        user = get_user_by_username(request.username)
        if user and user.get("is_blocked"):
            raise HTTPException(status_code=403, detail="Tài khoản của bạn đã bị khóa. Không thể thực hiện chat.")

    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Câu hỏi không được để trống")
    
    session_id = request.session_id or "default_session"
    logger.info(f"[{session_id} - User: {request.username}] Câu hỏi: {question[:100]}")
    
    # Lưu tin nhắn người dùng vào DB kèm username
    save_chat_message(session_id, "user", question, username=request.username)
    
    # ─── Bước 1: Chuẩn hóa tiếng Việt ───────────────────────
    normalized = normalize_input(question)
    norm_question = normalized["normalized"]
    
    # ─── Bước 2: Router phân loại (truyền conversation_history) ─
    routing = await asyncio.to_thread(route_question, norm_question, history=request.conversation_history)
    question_type = routing.get("question_type", "diễn_giải")
    crop = routing.get("crop") or None  # GĐ1 Mục 1: None nếu không xác định
    season = routing.get("season") or extract_season(norm_question)
    soil_type = routing.get("soil_type") or extract_soil_type(norm_question)
    variety = routing.get("variety") or extract_variety_name(norm_question)
    growth_stage = routing.get("growth_stage")  # GĐ1 Mục 1: thêm mới
    keywords = routing.get("topic_keywords", [])
    confidence = routing.get("confidence", "medium")

    # GĐ1 Mục 13: log kèm version
    ver_prefix = version_log_prefix()
    logger.info(
        f"{ver_prefix} Router: type={question_type}, crop={crop}, season={season}, "
        f"soil={soil_type}, growth_stage={growth_stage}"
    )
    
    # ─── Bước 3: Ngoài phạm vi ────────────────────────────────
    if question_type == "ngoài_phạm_vi":
        ans = (
            "Xin lỗi, câu hỏi của bạn nằm ngoài phạm vi tư vấn về nông nghiệp.\n\n"
            "Tôi hỗ trợ giải đáp về các chủ đề: kỹ thuật canh tác, giống nông sản, phân bón, "
            "quản lý nước, phòng trừ sâu bệnh, quy trình thu hoạch và bảo quản."
        )
        save_chat_message(session_id, "bot", ans, {"layer": "none", "type": question_type}, username=request.username)
        return ChatResponse(
            session_id=session_id,
            answer=ans,
            question_type=question_type,
            layer_used="none",
        )
    
    # ─── Bước 4: Cần hỏi lại ──────────────────────────────────
    if question_type == "cần_làm_rõ" or (confidence == "low" and not keywords):
        clarification = routing.get("clarification_question") or (
            "Bạn có thể bổ sung thêm chi tiết về câu hỏi này không? "
            "(Ví dụ: loại cây trồng/nông sản, loại đất hoặc mùa vụ cụ thể?)"
        )
        save_chat_message(session_id, "bot", clarification, {"layer": "none", "type": question_type}, username=request.username)
        return ChatResponse(
            session_id=session_id,
            answer=clarification,
            question_type=question_type,
            layer_used="none",
            clarification_needed=True,
            clarification_question=clarification,
        )
    
    # ─── Bước 5: Build IAM Farm Context (GĐ2) ───────────────────
    # farm_id do frontend truyền vào — KHÔNG để LLM tự sinh
    farm_ctx = build_farm_context(
        username=request.username or "anonymous",
        user_id=request.username or "0",
        role="user",
        farm_id=request.farm_id,  # None nếu không có farm context
        zone_id=request.zone_id,
    )

    # ─── Bước 6: Định tuyến các tầng ─────────────────────────
    answer_data = None
    layer_used = "none"
    is_partial = False
    partial_warning = None
    source_info = ""
    freshness_warnings: list = []
    tool_sources: list = []
    retrieval_sources: list = []
    requires_clarification_flag = False

    # ─── GĐ2: Thực thi Retrieval Plan Đa Nguồn ───────────────
    # execute_retrieval_plan thu thập song song từ: Facts + KG + Docs + Tools
    # Mỗi nguồn có IAM check, freshness flag, fail-closed policy
    plan_result = None
    try:
        plan_result = await execute_retrieval_plan(
            routing=routing,
            farm_context=farm_ctx,
            norm_question=norm_question,
            keywords=keywords,
        )
    except Exception as _rp_err:
        logger.warning(f"Retrieval plan lỗi (fallback về layer-by-layer): {_rp_err}")

    if plan_result and plan_result.merged_data:
        # ─── Tổng hợp từ retrieval plan ─────────────────────
        answer_data = plan_result.merged_data
        source_info = plan_result.merged_source_info or ""
        layer_used = "RetrievalPlan — " + ", ".join(plan_result.sources_used) if plan_result.sources_used else "RetrievalPlan"
        freshness_warnings = plan_result.warnings or []
        tool_sources = plan_result.tool_calls or []
        retrieval_sources = list(plan_result.sources_used) if plan_result.sources_used else []
        requires_clarification_flag = plan_result.requires_clarification
    else:
        # ─── Fallback: layer-by-layer (nếu retrieval plan fail hoặc trống) ─
        # — Tầng 1: Số liệu định lượng —
        if question_type == "định_lượng":
            layer_used = "Tầng 1 — Structured Fact Store"
            if variety:
                variety_data = get_rice_variety(variety)
                if variety_data:
                    answer_data = f"Thông tin nông sản / giống:\n{json.dumps(variety_data, ensure_ascii=False, indent=2)}"
                    source_info = "doc_001"

            if not answer_data:
                keyword = " ".join(keywords) if keywords else norm_question[:50]
                fact_result = get_fact(
                    attribute=keyword,
                    crop=crop,
                    season=season,
                    soil_type=soil_type,
                    growth_stage=growth_stage,
                )
                if fact_result["found"]:
                    is_partial = fact_result["is_partial_match"]
                    partial_warning = fact_result.get("warning")
                    facts_text = "\n".join([
                        f"- {r['attribute']}: {r['value']} {r.get('unit', '')} "
                        f"({r.get('condition_note', '')})"
                        for r in fact_result["results"]
                    ])
                    answer_data = f"Số liệu cơ sở dữ liệu:\n{facts_text}"
                    source_info = fact_result["results"][0].get("source_document_id", "Kho tri thức")
                elif fact_result.get("requires_clarification"):
                    partial_warning = fact_result.get("warning")
                    is_partial = False
                    requires_clarification_flag = True

        # — Tầng 2: Quan hệ / Phù hợp —
        elif question_type == "phù_hợp/quan_hệ":
            layer_used = "Tầng 2 — Knowledge Graph"
            keyword_str = " ".join(keywords)
            if keywords:
                pest_result = find_pest_info(pest_name=keyword_str)
                if pest_result["found"]:
                    answer_data = f"Thông tin sâu bệnh:\n{json.dumps(pest_result['results'], ensure_ascii=False, indent=2)}"
                    source_info = pest_result["source_info"]
            if not answer_data and keywords:
                tech_result = find_technique_info(technique_name=keyword_str)
                if tech_result["found"]:
                    answer_data = f"Thông tin kỹ thuật:\n{json.dumps(tech_result['results'], ensure_ascii=False, indent=2)}"
                    source_info = tech_result["source_info"]
            if not answer_data and (soil_type or season):
                kg_result = find_suitable_varieties(soil_type=soil_type, season=season)
                if kg_result["found"]:
                    answer_data = f"Kết quả Knowledge Graph:\n{json.dumps(kg_result['results'], ensure_ascii=False, indent=2)}"
                    source_info = kg_result["source_info"]

        # — Tầng 3: Document Store (RAG ChromaDB) —
        if not answer_data:
            layer_used = "Tầng 3 — Document Store"
            search_query = " ".join(keywords) if keywords else norm_question
            doc_result = await asyncio.to_thread(
                semantic_search,
                query=search_query,
                crop=crop,
                season=season,
                top_k=4,
            )
            if doc_result["found"]:
                chunks_text = "\n\n---\n\n".join([
                    f"[Nguồn tệp: {c.get('source', 'Tài liệu')} | Chủ đề: {c.get('topic', 'Nông nghiệp')}"
                    + (f" | Mục: {c.get('heading_path')}" if c.get("heading_path") else "") + f"]\n{c['chunk_text']}"
                    for c in doc_result["chunks"]
                ])
                answer_data = f"Nội dung tổng hợp từ các tài liệu nông nghiệp trong hệ thống:\n{chunks_text}"
                source_info = doc_result["source_info"]

    # ─── Bước 7: Kiểm tra dữ liệu ───────────────────────────
    if requires_clarification_flag and not answer_data:
        clarification_ans = (
            partial_warning or
            "Câu hỏi của bạn liên quan đến dữ liệu nhạy cảm (liều lượng, tưới tiêu...). "
            "Vui lòng cung cấp thêm: mùa vụ, loại đất, và giai đoạn sinh trưởng để tôi tư vấn chính xác."
        )
        save_chat_message(session_id, "bot", clarification_ans,
                          {"layer": layer_used, "type": question_type, "fail_closed": True},
                          username=request.username)
        return ChatResponse(
            session_id=session_id,
            answer=clarification_ans,
            question_type=question_type,
            layer_used=layer_used,
            clarification_needed=True,
            requires_clarification=True,
            freshness_warnings=freshness_warnings or None,
        )

    if not answer_data:
        fallback_ans = (
            "Tôi chưa tìm thấy thông tin phù hợp trong kho dữ liệu nông nghiệp hiện tại. "
            "Hệ thống không suy đoán khi thiếu dữ liệu.\n\n"
            "Quản trị viên có thể tải bổ sung tài liệu liên quan thông qua trang Quản lý Hệ thống."
        )
        save_chat_message(session_id, "bot", fallback_ans, {"layer": layer_used, "type": question_type}, username=request.username)
        return ChatResponse(
            session_id=session_id,
            answer=fallback_ans,
            question_type=question_type,
            layer_used=layer_used,
            freshness_warnings=freshness_warnings or None,
        )

    # ─── Bước 8: Tổng hợp câu trả lời ─────────────────────────
    # Thêm freshness warning vào context tổng hợp
    freshness_note = ""
    if freshness_warnings:
        freshness_note = "\n\n⚠️ Lưu ý dữ liệu: " + " | ".join(freshness_warnings)

    final_answer = await asyncio.to_thread(
        synthesize_answer,
        question=question,
        data=answer_data + freshness_note,
        source=f"Nguồn: {source_info} | Kho tri thức Nông nghiệp"
    )

    save_chat_message(session_id, "bot", final_answer, {
        "layer": layer_used,
        "type": question_type,
        "source": source_info,
        "is_partial": is_partial,
        "system_version": SYSTEM_VERSION,   # GĐ1 Mục 13: versioning
        "farm_id": request.farm_id,         # GĐ2: audit farm context
        "freshness_warnings": freshness_warnings,
    }, username=request.username)

    # ─── Ghi nhận ngầm nếu câu hỏi trùng với Q&E.txt ───
    try:
        _enqueue_benchmark_check(question, final_answer)
    except Exception as _be:
        logger.warning(f"Benchmark enqueue lỗi (không ảnh hưởng chat): {_be}")
        asyncio.create_task(_check_and_record_qe_match(question, final_answer))

    return ChatResponse(
        session_id=session_id,
        answer=final_answer,
        source=source_info,
        is_partial_match=is_partial,
        partial_match_warning=partial_warning,
        question_type=question_type,
        layer_used=layer_used,
        # GĐ2: thêm fields mới
        tool_sources=tool_sources or None,
        retrieval_sources=retrieval_sources or None,
        freshness_warnings=freshness_warnings or None,
        requires_clarification=requires_clarification_flag,
    )


# ─── Sessions & History Endpoints ─────────────────────────────
@app.get("/api/sessions")
async def list_sessions(username: Optional[str] = None):
    """Lấy danh sách các phiên trò chuyện của user."""
    if username:
        sessions = get_user_sessions(username)
    else:
        sessions = get_all_sessions()
    return {"sessions": sessions}


@app.get("/api/sessions/{session_id}/messages")
async def get_session_messages_api(session_id: str, username: Optional[str] = None):
    """Lấy lịch sử tin nhắn phiên trò chuyện."""
    messages = get_chat_history(session_id, username=username, limit=100)
    return {"session_id": session_id, "messages": messages}


@app.delete("/api/sessions/{session_id}")
async def delete_session_api(session_id: str, username: Optional[str] = None):
    """Xoá một phiên trò chuyện."""
    if not username:
        raise HTTPException(status_code=401, detail="Yêu cầu tài khoản")
    ok = delete_chat_session(session_id, username=username)
    if not ok:
        raise HTTPException(status_code=500, detail="Không thể xoá phiên trò chuyện")
    return {"status": "success", "message": "Đã xoá phiên trò chuyện"}


@app.post("/feedback")
async def submit_feedback(req: FeedbackRequest):
    """Lưu đánh giá người dùng."""
    ok = save_feedback(req.session_id, req.question, req.answer, req.rating, req.feedback_text)
    if not ok:
        raise HTTPException(status_code=500, detail="Không thể lưu đánh giá")
    return {"status": "success", "message": "Đã ghi nhận phản hồi!"}


# ─── Serve Frontend ───────────────────────────────────────────
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
    
    @app.get("/")
    async def serve_frontend():
        return FileResponse(str(FRONTEND_DIR / "index.html"))

    @app.get("/admin")
    @app.get("/admin.html")
    async def serve_admin():
        return FileResponse(str(FRONTEND_DIR / "admin.html"))
else:
    @app.get("/")
    async def root():
        return {"message": "Chatbot Nông Nghiệp AI API đang chạy", "docs": "/docs"}


if __name__ == "__main__":
    # pyrefly: ignore [missing-import]
    import uvicorn
    uvicorn.run("backend.app:app", host=APP_HOST, port=APP_PORT, reload=DEBUG)
