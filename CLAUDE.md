# BBIRR / P3DHxTReX

This repository is focused on extracting, validating, and normalizing public EBA disclosure data.

## Scope

- Primary: EBA Pillar 3 Data Hub (P3DH)
- Secondary: EBA Transparency Exercise (TrEx)

## Environment

- Use the project virtual environment only.
- Run Python with `.venv/Scripts/python`.
- Install packages with `.venv/Scripts/pip install <package>`.
- Use UTF-8 explicitly: `PYTHONIOENCODING=utf-8` for shell-launched Python.

## Key commands

Launch Chrome with remote debugging:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/launch_chrome_debug.py
```

Download P3DH robustly:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/download_p3dh_robust.py --date "31/12/2025" --resume
```

Build normalized SQLite:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/build_p3dh_sqlite.py --date "31/12/2025" --replace
```

Generated data/logs stay local under `data/` and are ignored by git.
