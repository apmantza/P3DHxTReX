@echo off
rem Start the P3DH dashboard. Open http://localhost:8765
"%~dp0.venv\Scripts\python.exe" -m streamlit run "%~dp0Overview.py" --server.port 8765
