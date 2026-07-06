# BBIRR

BBIRR is now focused on extracting, validating, and normalizing public EBA disclosure data.

## Scope

- **Primary:** EBA Pillar 3 Data Hub (P3DH)
- **Secondary:** EBA Transparency Exercise (TrEx)

Legacy business-planning/stress-testing code is archived under `archive/business_planning/`.

## Core commands

Launch Chrome with remote debugging:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/launch_chrome_debug.py
```

Build the local P3DH dictionary:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/build_p3dh_data_dictionary.py
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/load_p3dh_dict_db.py
```

Download P3DH data:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/download_via_api.py --date "31/12/2025"
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
