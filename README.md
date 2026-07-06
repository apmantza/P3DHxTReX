# BBIRR

BBIRR is now focused on extracting, validating, and normalizing public EBA disclosure data.

## Scope

- **Primary:** EBA Pillar 3 Data Hub (P3DH)
- **Secondary:** EBA Transparency Exercise (TrEx)

Legacy business-planning/stress-testing code has been removed from the active repository history going forward.

## Core commands

Launch Chrome with remote debugging:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/launch_chrome_debug.py
```

Build the local P3DH dictionary:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/build_p3dh_data_dictionary.py
```

Download P3DH data:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/download_p3dh_robust.py --date "31/12/2025" --resume
```

Build normalized SQLite:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/build_p3dh_sqlite.py --date "31/12/2025" --replace
```

Verify coverage:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/verify_p3dh_completeness.py
```

## Notes

- Use `.venv/Scripts/python`; do not use global Python.
- `data/` is ignored and contains raw/processed local artifacts.
- P3DH extraction uses EDAP + embedded Power BI query replay.
- `K_83.01` is currently a known EBA/Power BI model failure.

See `docs/p3dh_extraction.md` for implementation details.
