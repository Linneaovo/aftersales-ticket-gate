@echo off
REM 四层责任链 Live 验收（:8001 + :8002 联调档）
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  echo [FAIL] .venv missing
  exit /b 1
)
if exist .env.demo copy /Y .env.demo .env >nul
echo === 责任链命题：检索可信 != 允许开单 ===
echo 宣称：仅 live_verified=true 可称本机 Live；Standalone 绿 != Live
echo.
.\.venv\Scripts\python.exe scripts\run_responsibility_chain_verify.py --pack
exit /b %ERRORLEVEL%
