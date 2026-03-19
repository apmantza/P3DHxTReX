BBIRR

Bank business planning and stress testing toolkit for EU commercial banks.

Core principles
- Keep implementation modular; avoid monolithic files.
- Keep assumptions and mappings in YAML under `config/`.
- Prefer filesystem-based raw/processed data over unnecessary database layers.
- Only use SQLite where it adds clear value for app state or curated outputs.

Project structure
- `config/` - YAML defaults, mappings, and download targets.
- `modules/` - calculation, ingestion, fetch, and VBM modules.
- `scripts/` - operational scripts for browser automation, API capture, and ingestion helpers.
- `data/raw/` - downloaded source files and API extracts.
- `data/processed/` - normalized outputs used by the app.
- `db/` - SQLite models and app database code.

Environment
- Python 3.11+ in `.venv/`
- Run Python with `.venv/Scripts/python`
- Install packages with `.venv/Scripts/pip install <package>`
- Windows 11 + Git Bash

Config-driven calculation engine
- Plan defaults live in `config/plan_defaults.yaml`
- Data mappings and SDD codes live in `config/data_mappings.yaml`
- Config loading helpers live in `config/loader.py`
- Hardcoded calculation parameters have been moved into YAML where practical

P3DH Data Point downloads
- One-shot downloader: `scripts/download_via_api.py`
- It launches/uses Chrome remote debugging, opens the EDAP Data Points report, captures the Power BI `MWCToken`, discovers the latest available date, scrolls the virtualized Template slicer, and replays the Power BI QueryExecution API directly.
- Outputs are written to `data/raw/P3DH/<yyyymmdd>/`

Run the one-shot downloader
```bash
.venv/Scripts/python scripts/download_via_api.py
```

Optional flags
```bash
.venv/Scripts/python scripts/download_via_api.py --date 31/12/2025
.venv/Scripts/python scripts/download_via_api.py --template K_73.00
```

Current downloader status
- Latest-date discovery works.
- Virtualized template discovery works.
- Power BI QueryExecution replay works.
- Most templates download directly to CSV without UI export.
- Current automated coverage is 88 templates for the latest `31/12/2025` date.
- `K_83.01` remains excluded from the stable automated path because its query shape is different and the full query times out.

Supporting scripts
- `scripts/launch_chrome_debug.py` - starts Chrome with remote debugging on port `9222`
- `scripts/download_all_templates.py` - older UI-driven prototype, superseded by API replay
- `scripts/fetch_edap_data.py` - early CDP exploration flow

Notes
- P3DH public data is date-sensitive; complete `31/12` data is typically available by end-March and `30/06` by end-November.
- The EDAP Power BI frontend uses a virtualized slicer and hidden export UI; browser clicking is unreliable at scale. API replay is the preferred path.
- Large raw/processed data files and local SQLite databases are intentionally ignored from git; this repo tracks code, config, and docs only.
