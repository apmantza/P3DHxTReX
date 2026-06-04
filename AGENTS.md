# AGENTS.md — BBIRR Coding Agent Guide

## Project

BBIRR is a bank business planning and stress-testing toolkit for EU commercial banks. It combines P3DH public disclosure data, TrEx transparency exercise data, ECB rates/yield curves, and planning assumptions.

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
- `data/`, SQLite DBs, CSV/XLSX exports, logs, and screenshots are ignored.
- Code, docs, config, and small operational scripts are tracked.

## P3DH notes

- P3DH full packages are expected twice per year:
  - `31/12`: complete around end-March.
  - `30/06`: complete around end-November.
- `31/03` and `30/09` are lighter quarterly subsets.
- The EDAP report is a Power BI embedded report.
- Preferred download path is direct Power BI `QueryExecution` API replay, not UI export.
- Chrome remote debugging is used only to discover slicer values and capture the API token/query.

## P3DH stable workflow

Launch Chrome if needed:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/launch_chrome_debug.py
```

Download a full P3DH date package in parallel:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/download_p3dh_parallel.py --date "31/12/2025" --workers 5
```

Sequential fallback / single-template download:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/download_via_api.py --date "31/12/2025"
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/download_via_api.py --date "31/12/2025" --template K_73.00
```

Verify portal template coverage:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/verify_p3dh_completeness.py
```

Clean rebuild of P3DH SQLite from a single fresh raw package:

```bash
rm -f data/processed/p3dh.sqlite data/processed/p3dh_normalized.csv
PYTHONIOENCODING=utf-8 .venv/Scripts/python - <<'PY'
from pathlib import Path
from modules.ingestion.p3dh_normalize import normalize_all_p3dh, upsert_p3dh_sqlite

processed = Path('data/processed')
raw_date = Path('data/raw/P3DH/20251231')
normalized = normalize_all_p3dh(raw_date)
normalized.to_csv(processed / 'p3dh_normalized.csv', index=False, encoding='utf-8-sig')
inserted, skipped = upsert_p3dh_sqlite(normalized, processed / 'p3dh.sqlite')
print(f'normalized={len(normalized):,} inserted={inserted:,} skipped={skipped:,}')
PY
```

## Known P3DH limitation

- `K_83.01` currently fails via direct API replay due to an EBA/Power BI semantic model error involving `dm_Module[ENT_NAM]`.
- Treat it as an EBA-side issue unless the portal/API model changes.
- UI export may be used as a manual fallback if that template is required.

## Coding conventions

- Prefer small, focused modules and scripts.
- Keep assumptions/mappings in `config/` where practical.
- Do not commit generated data/log artifacts.
- Run relevant scripts with `.venv/Scripts/python` before committing.
