@echo off
setlocal

set PYTHONIOENCODING=utf-8

pushd %~dp0\..

call .venv\Scripts\python scripts\ingest_raw.py
if errorlevel 1 goto :error

call .venv\Scripts\python scripts\init_db.py
if errorlevel 1 goto :error

call .venv\Scripts\python scripts\load_peerdata_db.py
if errorlevel 1 goto :error

call .venv\Scripts\python scripts\build_base_year.py
if errorlevel 1 goto :error

call .venv\Scripts\python scripts\load_base_year_db.py
if errorlevel 1 goto :error

call .venv\Scripts\python -m modules.historical.ecb_rates
if errorlevel 1 goto :error

call .venv\Scripts\python scripts\load_ecb_rates_db.py
if errorlevel 1 goto :error

call .venv\Scripts\python scripts\rate_assumptions.py
if errorlevel 1 goto :error

call .venv\Scripts\python scripts\export_rates_json.py
if errorlevel 1 goto :error

echo.
echo Ingestion and DB load complete.
popd
pause
exit /b 0

:error
echo.
echo Failed during ingestion or DB load.
popd
pause
exit /b 1
