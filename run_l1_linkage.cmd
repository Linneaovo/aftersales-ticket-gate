@echo off
REM L1 一键：Compose joint + 契约联调验收（无 Ollama）
setlocal
cd /d "%~dp0"

echo === L1 Compose up ===
docker compose -f docker-compose.joint.yml up --build -d
if errorlevel 1 exit /b 1

echo === wait health ===
timeout /t 8 /nobreak >nul

docker compose -f docker-compose.joint.yml exec -T api python scripts/reset_demo_state.py
if errorlevel 1 exit /b 1

docker compose -f docker-compose.joint.yml exec -T api python scripts/run_l1_linkage.py
set RC=%ERRORLEVEL%
echo === L1 done exit=%RC% (live_verified must be false; see l1_verified) ===
exit /b %RC%
