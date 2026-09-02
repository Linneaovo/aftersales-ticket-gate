@echo off
REM 联调档启动 Copilot :8002（须 enterprise-rag :8001 已起）
cd /d %~dp0
if not exist .venv (
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -r requirements.txt -q
if exist .env.demo (
  copy /Y .env.demo .env >nul
  echo 已加载 .env.demo ^(rag_mock_inbox · RAG_AUTO_FALLBACK=0^)
) else (
  echo [WARN] 缺少 .env.demo
)
echo Starting Copilot LIVE on :8002 ...
uvicorn app.main:app --host 127.0.0.1 --port 8002
