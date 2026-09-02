@echo off
REM 一键启动：enterprise-rag (:8001) + Copilot (:8002) + Streamlit UI (:8502)
REM 联调档：copy .env.demo .env；RAG 经 start_demo/demo_env 开 submit token 硬门
cd /d %~dp0

if not exist .venv (
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -r requirements.txt -q

if exist .env.demo (
  copy /Y .env.demo .env >nul
  echo 已强制 .env.demo -^> .env（Live：RAG_AUTO_FALLBACK=0 · rag_mock_inbox）
)

set RAG_DIR=%~dp0..\enterprise-rag
if exist "%RAG_DIR%\start_demo.cmd" (
  echo [1/3] 启动 enterprise-rag :8001（demo_env A档 SUBMIT_REQUIRE_COPILOT_TOKEN=1）...
  start "enterprise-rag" cmd /c "cd /d %RAG_DIR% && start_demo.cmd --no-pause"
  timeout /t 8 /nobreak >nul
) else if exist "%RAG_DIR%\start.cmd" (
  echo [1/3] 启动 enterprise-rag :8001 ...
  start "enterprise-rag" cmd /c "cd /d %RAG_DIR% && start.cmd"
  timeout /t 5 /nobreak >nul
) else (
  echo [1/3] 跳过 RAG 自动启动（未找到 %RAG_DIR%\start_demo.cmd）
  echo       请手动：cd ..\enterprise-rag ^&^& start_demo.cmd，然后按任意键继续 ...
  pause >nul
)

echo [2/3] 启动 Copilot API :8002 ...
start "copilot-api" cmd /c "cd /d %~dp0 && call start_copilot.cmd"

timeout /t 4 /nobreak >nul
echo [3/3] 启动 Streamlit UI :8502 ...
start "copilot-ui" cmd /c "cd /d %~dp0 && call start_ui.cmd"

echo.
echo === 宣称规则（勿混称）===
echo   Standalone 绿  = 门禁仓可独立验收
echo   矩阵/契约齐    = 协同设计已落地（不等于 Live）
echo   live_verified  = 才可说本机 Live 联调通过
echo   token/source   = 演示归属约定，非生产鉴权
echo   Plan B/旧产物  = 只救叙事，禁止冒充当场联调
echo.
echo === 服务起来后建议顺序 ===
echo   1^) RAG侧门禁:  cd ..\enterprise-rag ^&^& .\.venv\Scripts\python.exe scripts\joint_linkage_gate.py --require-live-health
echo   2^) 重置状态:   python scripts\reset_demo_state.py
echo   3^) 预检+矩阵:  python scripts\demo_preflight.py --require-rag --smoke-run --contract --matrix
echo   4^) 证据包:     python scripts\run_joint_verify.py --pack
echo      或一步:     python scripts\demo_preflight.py --require-rag --matrix --pack-matrix
echo.
echo curl http://127.0.0.1:8001/health
echo curl http://127.0.0.1:8002/health   （确认 runtime_mode / rag_mode=live）
echo.
echo 主演示只钉一条缺料路径；冲突/ACL 留给 RAG 单仓，勿双边讲满同一故障码。
