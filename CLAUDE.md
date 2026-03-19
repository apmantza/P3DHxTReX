# BBIRR — Bank Business Plan & Stress Testing Tool

## Project Overview
White-label web application for EU commercial banks — strategic steering + stress testing platform. See `docs/plans/2026-02-21-bank-business-plan-stress-tool-design.md` for full design.

## Environment

- **Python:** Use the project virtual environment at `.venv/`
- **Run Python:** `.venv/Scripts/python` (Windows)
- **Install packages:** `.venv/Scripts/pip install <package>` — NEVER install globally
- **OS:** Windows 11, shell is bash (Git Bash)

## Conventions

- All Python code targets Python 3.11+
- Use `.venv/Scripts/python` for all Python commands
- Keep dependencies in `.venv` only — no global installs
- **Encoding:** Always use UTF-8. Windows defaults to cp1252 which breaks on EU characters (€, ≥, accented names, etc.)
  - Python scripts: `open(..., encoding="utf-8")` on every file open
  - Bash: prefix Python commands with `PYTHONIOENCODING=utf-8`
  - CSV/Excel output: explicit `encoding="utf-8-sig"` for Excel-compatible CSV

## P3DH Data Timing

- P3DH publishes **full data only twice per year**: 31/12 and 30/06
- Q1 (31/03) and Q3 (30/09) releases contain only a subset of templates (lighter files)
- **Expected availability:**
  - 31/12 data: Complete by end of March each year
  - 30/06 data: Complete by end of November each year
- Current 31/12 data is incomplete — files will be re-downloaded in March and re-ingested
- Incremental ingestion handles re-downloads: same keys are skipped, new keys added
- **Run ingestion:** `scripts\run_ingestion_and_db.bat`
