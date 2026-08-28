@echo off
cd /d %~dp0
if not exist .venv (
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -r requirements.txt -q
if exist .env.example if not exist .env copy .env.example .env >nul
echo Prerequisite: enterprise-rag on :8001 (DEMO_MODE=1, demo-kb)
echo Optional smoke after both up: python scripts\smoke_with_rag.py
echo Starting copilot API on :8002 ...
uvicorn app.main:app --host 127.0.0.1 --port 8002
