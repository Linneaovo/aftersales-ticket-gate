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



  echo [WARN] reset_demo_state failed — close any Copilot window and retry



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



echo Waiting for :8002 ...



timeout /t 8 /nobreak >nul



echo Starting UI :8502 ...



start "copilot-ui" cmd /k "cd /d %~dp0 && call .venv\Scripts\activate.bat && streamlit run app/ui/streamlit_app.py --server.port 8502"



echo.



echo Running standalone preflight ...



python scripts\demo_preflight.py --standalone



if errorlevel 1 (



  echo [WARN] preflight failed — check :8002 started and .env.standalone loaded



) else (



  echo [OK] standalone DoD ritual passed



)



echo Health: curl http://127.0.0.1:8002/health



echo Expect: runtime_mode=standalone · submit_destination=file_outbox · knowledge_port=fixture · persistence_ok=true






