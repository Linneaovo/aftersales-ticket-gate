@echo off
cd /d %~dp0

echo === Copilot Standalone (no enterprise-rag required) ===

if not exist .venv (
  python -m venv .venv
)

call .venv\Scripts\activate.bat
pip install -r requirements.txt -q

copy /Y .env.standalone .env >nul
echo Copied .env.standalone -^> .env

rem 释放旧 API/UI 占用的端口，避免 checkpoints.db 被锁、/health.version 仍是旧进程
echo Releasing ports 8002 / 8502 if in use ...
powershell -NoProfile -Command ^
  "$ports = 8002, 8502, 8011; foreach ($p in $ports) { Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue } }"
timeout /t 2 /nobreak >nul

python scripts\reset_demo_state.py
if errorlevel 1 (
  echo [FAIL] reset_demo_state failed — close any Copilot window and retry
  exit /b 1
)

echo Starting Copilot API :8002 ...
start "copilot-standalone" cmd /k "cd /d %~dp0 && call .venv\Scripts\activate.bat && uvicorn app.main:app --host 127.0.0.1 --port 8002 --workers 1"

rem Optional mock WMS：.env.standalone 设 START_MOCK_WMS=1 且 PARTS_LEDGER_URL=http://127.0.0.1:8011
findstr /B /C:"START_MOCK_WMS=1" .env.standalone >nul
if not errorlevel 1 (
  echo Starting optional mock WMS on :8011 ...
  start "mock-parts-wms" cmd /k "cd /d %~dp0 && call .venv\Scripts\activate.bat && python scripts\mock_parts_wms.py"
) else (
  echo Skip mock WMS ^(set START_MOCK_WMS=1 in .env.standalone to enable^)
)

echo Waiting for :8002 /health ...
python scripts\wait_http_ok.py --url http://127.0.0.1:8002/health --timeout-s 45
if errorlevel 1 (
  echo.
  echo [FAIL] API 未就绪，已中止启动（不会打开 UI）。
  echo   1^) 看窗口 copilot-standalone 是否已报错 / STRICT_STARTUP 退出
  echo   2^) 确认已 copy .env.standalone .env
  echo   3^) 手动: curl http://127.0.0.1:8002/health
  exit /b 1
)

echo.
echo Running standalone preflight ...
python scripts\demo_preflight.py --standalone
if errorlevel 1 (
  echo.
  echo ========================================================================
  echo [FAIL] standalone preflight 未通过 — 演示栈未就绪，已中止（不启动 UI）。
  echo   常见原因: :8002 仍是旧进程 / .env 不是 standalone / persistence 脏
  echo   处理: python scripts\reset_demo_state.py
  echo         python scripts\demo_preflight.py --standalone
  echo   通过后再: start_ui.cmd  或  streamlit run app/ui/streamlit_app.py --server.port 8502
  echo ========================================================================
  exit /b 1
)

echo [OK] standalone DoD ritual passed
echo.
echo Starting UI :8502 ...
start "copilot-ui" cmd /k "cd /d %~dp0 && call .venv\Scripts\activate.bat && streamlit run app/ui/streamlit_app.py --server.port 8502"

echo Health: curl http://127.0.0.1:8002/health
echo Expect: runtime_mode=standalone · submit_destination=file_outbox · knowledge_port=fixture · persistence_ok=true
echo UI: http://127.0.0.1:8502
exit /b 0
