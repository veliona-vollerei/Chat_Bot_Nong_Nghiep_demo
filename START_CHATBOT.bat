@echo off
REM ============================================
REM  CHATBOT NONG NGHIEP — Khoi dong nhanh
REM  Chay file nay de bat dau he thong
REM ============================================

cd /d e:\vi_no_ngon\chatbot

echo Kich hoat moi truong Python...
call .venv\Scripts\activate
set PYTHONIOENCODING=utf-8

echo.
echo Khoi dong Chatbot Nong Nghiep...
echo Truy cap: http://localhost:8000
echo Nhan Ctrl+C de dung
echo.

python -m uvicorn backend.app:app --reload --port 8000
