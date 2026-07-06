# Repository cleanup plan

The repository is being narrowed from a bank business-planning/stress-testing toolkit to a P3DH-first data extraction toolkit.

## Active focus

- P3DH download from EDAP/Power BI replay
- P3DH EBA dictionary generation from annotated table layouts
- P3DH normalization and SQLite loading
- P3DH completeness/quality validation
- TrEx ingestion as secondary support

## Archived legacy scope

Legacy business-planning modules, rate/yield-curve utilities, rating/VBM calculations, and old planning docs have been moved to:

```text
archive/business_planning/
```

This keeps the code available for reference without presenting it as active product code.

## Next refactor

Split the large downloader into focused modules:

```text
src/p3dh/browser.py
src/p3dh/query_capture.py
src/p3dh/query_modify.py
src/p3dh/parse_powerbi.py
src/p3dh/download.py
src/p3dh/dictionary.py
src/p3dh/validate.py
```

Then convert scripts into thin CLIs.
