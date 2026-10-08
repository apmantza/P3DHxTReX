# AGENTS.md - Guide for coding agents

## Project

This repository downloads, stores, and verifies disclosures from the EBA Pillar 3 Data Hub (P3DH). Transparency Exercise (TrEx) data is out of scope.

## Environment

- Use the project virtual environment: `.venv/Scripts/python`.
- Install packages with `.venv/Scripts/pip install <package>`. Do not install globally.
- The shell is Git Bash on Windows.
- Use UTF-8. Set `PYTHONIOENCODING=utf-8` and pass `encoding="utf-8"` to file functions.
- Native Windows programs do not understand `/tmp` paths from Git Bash. Use Windows paths for scratch files.

## Data policy

- Git does not track `data/`, SQLite files, CSV files, logs, screenshots, or browser profiles.
- Git tracks code, documentation, and small configuration files.
- Never delete `data/raw/P3DH_json`. It is the source for rebuilding the CSV files without the network.

## Workflow

1. Download: `scripts/download_p3dh.py --date "DD/MM/YYYY" --all`
2. Load the database: `scripts/build_p3dh_db.py`
3. Verify: `scripts/verify_p3dh.py`
4. After a decoder change, run `scripts/redecode_p3dh.py`, then steps 2 and 3.

Run one downloader process at a time. The default limit is 60 requests per minute.

## Rules for changes to the download code

- The decoder is `modules/fetch/dsr_decode.py`. It must handle the repeat mask `R` and the null mask for groups and for measures.
- Never accept a response that carries a restart token (`RT`) as complete. Continue with `RestartTokens`, or split the request.
- Never use a stored list as a fallback for portal discovery. A failed discovery must raise an error.
- Identify an entity by its LEI and its name. One LEI can appear under two names.
- Keep text facts. Many templates contain text, dates, and booleans.
- Validate each response against the requested reference date and template.
- A leaf with no value is not a fact. The decoder counts these leaves in `null_measures`.

## Known facts

- Power BI honours a primary window of up to 30000 leaf rows if `Secondary.Top.Count` is 1. If the product of the counts exceeds 25 million, Power BI ignores the counts and returns 500 rows.
- The query for `K_83.01` times out at 120 seconds on the dates that list it. See `docs/p3dh_extraction.md`.
- Entity discovery by scrolling the slicer can miss entities. The downloader pages the whole template and does not depend on the entity list.

## Coding conventions

- Keep modules small. Keep the command-line scripts thin.
- Write comments only for facts that the code cannot show.
- Do not commit data or logs.
