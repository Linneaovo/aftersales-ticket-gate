@echo off
REM 一键启动：enterprise-rag (:8001) + Copilot (:8002) + Streamlit UI (:8502)
REM 用法：先确保 enterprise-rag 仓库在本机可启动；答辩前 copy .env.demo .env
cd /d %~dp0

if not exist .venv (
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -r requirements.txt -q

if exist .env.demo if not exist .env (
  copy .env.demo .env >nul
  echo 已复制 .env.demo -> .env（答辩模式：RAG_AUTO_FALLBACK=0）
)

set RAG_DIR=%~dp0..\enterprise-rag
if exist "%RAG_DIR%\start.cmd" (
  echo [1/3] 启动 enterprise-rag :8001 ...
  start "enterprise-rag" cmd /c "cd /d %RAG_DIR% && start.cmd"
  timeout /t 5 /nobreak >nul
) else (
  echo [1/3] 跳过 RAG 自动启动（未找到 %RAG_DIR%\start.cmd）
  echo       请手动启动 enterprise-rag :8001，然后按任意键继续 ...
  pause >nul
)

echo [2/3] 启动 Copilot API :8002 ...
start "copilot-api" cmd /c "cd /d %~dp0 && call start_copilot.cmd"

timeout /t 4 /nobreak >nul
echo [3/3] 启动 Streamlit UI :8502 ...
start "copilot-ui" cmd /c "cd /d %~dp0 && call start_ui.cmd"

echo.
echo === 双项目联动检查 ===
echo   curl http://127.0.0.1:8001/health
echo   curl http://127.0.0.1:8002/health   （确认 rag_mode=live）
echo   python scripts\reset_demo_state.py
echo   python scripts\demo_preflight.py --require-rag
echo   python scripts\smoke_with_rag.py --compare-live  （可选，需 RAG live）
echo 演示顺序见 DEMO_SCRIPT.md
echo.
echo 若 RAG 未启动：请先 cd ..\enterprise-rag ^&^& start.cmd
