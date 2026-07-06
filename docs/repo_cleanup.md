# Repository cleanup

The repository has been narrowed from a bank business-planning/stress-testing toolkit to a P3DH-first data extraction toolkit.

## Active focus

- P3DH download from EDAP/Power BI replay
- P3DH EBA dictionary generation from annotated table layouts
- P3DH normalization and SQLite loading
- P3DH completeness/quality validation
- TrEx ingestion as secondary support

## Removed legacy scope

Legacy business-planning modules, rate/yield-curve utilities, rating/VBM calculations, SQLAlchemy projection models, and old planning docs have been removed from the active tree. Generated data/log artifacts remain local and are ignored by git.

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
