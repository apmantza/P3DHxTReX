# AGENTS.md — BBIRR / P3DHxTReX Coding Agent Guide

## Project

This repository is focused on EBA Pillar 3 Data Hub (P3DH) extraction, validation, dictionary generation, normalization, and SQLite loading. EBA Transparency Exercise (TrEx) support is secondary.

## Environment

- Python: use the project virtual environment only.
- Run Python with `.venv/Scripts/python`.
- Install packages with `.venv/Scripts/pip install <package>`.
- Do not install globally.
- Shell: Git Bash on Windows.
- Use UTF-8 explicitly.
  - Python file IO: `encoding="utf-8"` or `encoding="utf-8-sig"` for Excel-compatible CSV.
  - Bash/Python commands: prefer `PYTHONIOENCODING=utf-8`.

## Data policy

- Large local data artifacts are not tracked in git.
- `data/`, SQLite DBs, CSV/XLSX exports, logs, screenshots, browser profiles, and agent caches are ignored.
- Code, docs, config, and small operational scripts are tracked.

## P3DH notes

- P3DH full packages are expected twice per year:
  - `31/12`: complete around end-March.
  - `30/06`: complete around end-November.
- `31/03` and `30/09` are lighter quarterly subsets.
- The EDAP report is a Power BI embedded report.
- Preferred download path is direct Power BI `QueryExecution` API replay, not UI export.
- Chrome remote debugging is used only to discover slicer values and capture the API token/query.
- Treat any DSR restart token (`RT`) as a truncation/completeness warning.

## P3DH stable workflow

Launch Chrome if needed:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/launch_chrome_debug.py
```

Robust date download:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/download_p3dh_robust.py \
  --date "31/12/2025" \
  --workers 8 \
  --refresh-minutes 8 \
  --request-delay-ms 100 \
  --max-requests-per-minute 0 \
  --partition-chunk-size 50 \
  --partition-timeout 30 \
  --partition-retries 1 \
  --resume
```

Build dictionary:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/build_p3dh_data_dictionary.py
```

Build normalized SQLite:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/build_p3dh_sqlite.py --date "31/12/2025" --replace
```

Verify portal template coverage:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/verify_p3dh_completeness.py
```

## Known P3DH limitation

- `K_83.01` currently fails via direct API replay due to an EBA/Power BI semantic model issue.
- Treat it as an EBA-side issue unless the portal/API model changes.
- Omit it from automated completeness expectations for now.

## Coding conventions

- Prefer small, focused modules and scripts.
- Keep assumptions/mappings in `config/` where practical.
- Do not commit generated data/log artifacts.
- Run relevant scripts with `.venv/Scripts/python` before committing.
