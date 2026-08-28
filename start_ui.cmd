@echo off
cd /d %~dp0
call .venv\Scripts\activate.bat
set COPILOT_BASE_URL=http://127.0.0.1:8002
streamlit run app\ui\streamlit_app.py --server.port 8502
