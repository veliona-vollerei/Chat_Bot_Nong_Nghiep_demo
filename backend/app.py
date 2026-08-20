import logging
import json
import os
from pathlib import Path
from typing import Optional
# pyrefly: ignore [missing-import]
from fastapi import FastAPI, HTTPException, UploadFile, File, Header, Depends
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
from backend.db.postgres import (
    save_chat_message, get_chat_history, get_all_sessions, get_user_sessions, delete_chat_session, save_feedback,
    create_user, get_user_by_username, get_user_by_id, get_all_users, update_user_block_status,
    delete_user, hash_password
)
from backend.ingestion.data_pipeline import process_and_ingest_document, retry_failed_pages, RAW_UPLOADS_DIR

logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Chatbot Nông Nghiệp AI",
    description="Hệ thống Chatbot Nông Nghiệp — Tư vấn đa dạng nông sản & Quản lý tri thức",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = BASE_DIR / "frontend"


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


class FeedbackRequest(BaseModel):
    session_id: Optional[str] = "default_session"
    question: str
    answer: str
    rating: int  # 1 hoặc -1
    feedback_text: Optional[str] = None


class RetryOcrRequest(BaseModel):
    doc_id: str
    pdf_filename: str


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

    Response:
    - status='success': nạp thành công, kèm ocr_stats (nếu là PDF scan).
    - status='partial_failure' (HTTP 207): OCR thất bại > 15% trang scan, dữ liệu KHÔNG được nạp.
      Gọi POST /api/admin/retry-ocr để xử lý lại các trang lỗi.
    - status='error': không trích xuất được văn bản.
    """
    if username != "admin":
        user = get_user_by_username(username) if username else None
        if not user or user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Yêu cầu quyền Admin.")

    if not file.filename:
        raise HTTPException(status_code=400, detail="Vui lòng chọn file dữ liệu.")

    save_path = RAW_UPLOADS_DIR / file.filename
    try:
        content = await file.read()
        with open(save_path, "wb") as f:
            f.write(content)

        result = process_and_ingest_document(str(save_path), custom_title=file.filename)

        # Trả HTTP 207 Multi-Status khi OCR thất bại quá ngưỡng
        if result.get("status") == "partial_failure":
            return JSONResponse(status_code=207, content=result)

        return result
    except Exception as e:
        logger.error(f"Lỗi upload dữ liệu: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi xử lý file: {str(e)}")


@app.post("/api/admin/retry-ocr")
async def admin_retry_ocr(req: RetryOcrRequest, username: Optional[str] = None):
    """Admin: OCR lại các trang thất bại trong lần ingest trước.

    Đọc danh sách trang lỗi từ cache (data/page_cache/{doc_id}_pages.json),
    OCR lại, re-chunk toàn bộ tài liệu và nạp lại vào ChromaDB.

    Body: { "doc_id": str, "pdf_filename": str }

    Response:
    - status='success': tất cả trang đã OCR thành công.
    - status='partial_failure' (HTTP 207): vẫn còn trang lỗi sau retry.
    """
    if username != "admin":
        user = get_user_by_username(username) if username else None
        if not user or user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Yêu cầu quyền Admin.")

    from backend.ingestion.data_pipeline import RAW_UPLOADS_DIR
    pdf_path = RAW_UPLOADS_DIR / req.pdf_filename

    if not pdf_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Không tìm thấy file '{req.pdf_filename}' trong thư mục uploads."
        )

    try:
        result = retry_failed_pages(str(pdf_path), req.doc_id)

        if result.get("status") == "partial_failure":
            return JSONResponse(status_code=207, content=result)

        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Lỗi retry OCR: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi khi retry OCR: {str(e)}")


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



# ─── System Health ────────────────────────────────────────────
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
    routing = route_question(norm_question, history=request.conversation_history)
    question_type = routing.get("question_type", "diễn_giải")
    crop = routing.get("crop", "nông nghiệp tổng quát")
    season = routing.get("season") or extract_season(norm_question)
    soil_type = routing.get("soil_type") or extract_soil_type(norm_question)
    variety = routing.get("variety") or extract_variety_name(norm_question)
    keywords = routing.get("topic_keywords", [])
    confidence = routing.get("confidence", "medium")
    
    logger.info(f"Router: type={question_type}, crop={crop}, season={season}, soil={soil_type}")
    
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
    
    # ─── Bước 5: Định tuyến các tầng ─────────────────────────
    answer_data = None
    layer_used = "none"
    is_partial = False
    partial_warning = None
    source_info = ""
    
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
                soil_type=soil_type
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
        
        doc_result = semantic_search(
            query=search_query,
            crop=crop,
            season=season,
            top_k=4,
        )
        
        if doc_result["found"]:
            chunks_text = "\n\n---\n\n".join([
                f"[Nguồn tệp: {c.get('source', 'Tài liệu')} | Chủ đề: {c.get('topic', 'Nông nghiệp')}]\n{c['chunk_text']}"
                for c in doc_result["chunks"]
            ])
            answer_data = f"Nội dung tổng hợp từ các tài liệu nông nghiệp trong hệ thống:\n{chunks_text}"
            source_info = doc_result["source_info"]
    
    # ─── Bước 6: Kiểm tra dữ liệu ───────────────────────────
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
        )
    
    # ─── Bước 7: Tổng hợp câu trả lời ─────────────────────────
    final_answer = synthesize_answer(
        question=question,
        data=answer_data,
        source=f"Nguồn: {source_info} | Kho tri thức Nông nghiệp"
    )
    
    save_chat_message(session_id, "bot", final_answer, {
        "layer": layer_used,
        "type": question_type,
        "source": source_info,
        "is_partial": is_partial
    }, username=request.username)
    
    return ChatResponse(
        session_id=session_id,
        answer=final_answer,
        source=source_info,
        is_partial_match=is_partial,
        partial_match_warning=partial_warning,
        question_type=question_type,
        layer_used=layer_used,
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
