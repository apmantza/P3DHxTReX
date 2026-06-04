# BBIRR

Bank business planning and stress testing toolkit for EU commercial banks.

## Core principles

- Keep implementation modular; avoid monolithic files.
- Keep assumptions and mappings in YAML under `config/`.
- Prefer filesystem-based raw/processed data over unnecessary database layers.
- Only use SQLite where it adds clear value for app state or curated outputs.
- Keep large data artifacts out of git.

## Project structure

- `config/` - YAML defaults, mappings, and download targets.
- `modules/` - calculation, ingestion, fetch, and VBM modules.
- `scripts/` - operational scripts for browser automation, API capture, and ingestion helpers.
- `data/raw/` - downloaded source files and API extracts; ignored by git.
- `data/processed/` - normalized outputs used by the app; ignored by git.
- `db/` - SQLite models and app database code.

## Environment

- Python 3.11+ in `.venv/`
- Run Python with `.venv/Scripts/python`
- Install packages with `.venv/Scripts/pip install <package>`
- Windows 11 + Git Bash
- Use UTF-8 explicitly, especially for EU names/characters:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python <script>
```

## Config-driven calculation engine

- Plan defaults live in `config/plan_defaults.yaml`.
- Data mappings and SDD codes live in `config/data_mappings.yaml`.
- Config loading helpers live in `config/loader.py`.
- Hardcoded calculation parameters should live in YAML where practical.

## P3DH Data Point downloads

The preferred P3DH path is direct Power BI `QueryExecution` API replay. Chrome/CDP is used only to discover report slicers and capture the token/query from the embedded EDAP Power BI report.

### Launch Chrome debugging

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/launch_chrome_debug.py
```

### Parallel full-date downloader

Use this for full date packages:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/download_p3dh_parallel.py --date "31/12/2025" --workers 5
```

Current observed clean run for `31/12/2025`:

- Portal templates discovered: `114`
- Successful API template downloads: `113`
- Skipped: `K_83.01`
- Failed: `0`
- Raw rows: `30,942`
- Runtime with 5 workers: ~18-26 seconds after token capture

`K_83.01` currently fails through API replay because the EBA Power BI model returns a semantic query error for `dm_Module[ENT_NAM]`. Treat this as an EBA-side issue unless the model changes.

### Sequential fallback / one template

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/download_via_api.py --date "31/12/2025"
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/download_via_api.py --date "31/12/2025" --template K_73.00
```

`download_via_api.py` now raises all `Binding.DataReduction` `Count` values, not only the primary window count.

### Verify portal coverage

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/verify_p3dh_completeness.py
```

### Clean P3DH SQLite rebuild from one raw package

To rebuild only from a fresh `31/12/2025` raw package:

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

Latest clean rebuild from the fresh `20251231` raw package produced:

- Normalized numeric rows: `30,610`
- SQLite inserted rows: `25,539`
- Raw CSV templates: `113`
- SQLite entities: `237`
- SQLite NULL-template rows: `144`

## P3DH data timing

- P3DH publishes full data only twice per year: `31/12` and `30/06`.
- Q1 (`31/03`) and Q3 (`30/09`) releases contain only a subset of templates.
- Expected availability:
  - `31/12`: complete by end-March.
  - `30/06`: complete by end-November.

## Supporting scripts

- `scripts/launch_chrome_debug.py` - starts Chrome with remote debugging on port `9222`.
- `scripts/download_p3dh_parallel.py` - preferred concurrent API downloader.
- `scripts/download_via_api.py` - sequential API downloader / one-template fallback.
- `scripts/verify_p3dh_completeness.py` - compares portal-discovered templates with local raw downloads.
- `scripts/download_all_templates.py` - older UI-driven prototype, kept as possible fallback for broken API templates.
- `scripts/fetch_edap_data.py` - early CDP exploration flow.

## Notes

- Large raw/processed data files and SQLite databases are intentionally ignored from git.
- Use `AGENTS.md` for coding-agent operating guidance.
