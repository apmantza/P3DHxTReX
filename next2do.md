# Next to do

## Current priority

Produce a clean, validated `31/12/2025` P3DH package using the robust downloader with:

- full 453-entity discovery;
- entity-level restart-token (`RT`) detection;
- row-level fallback for entity partitions that still have `RT`;
- conservative global rate limiting and jitter;
- local dictionary/schema validation after extraction.

## 1. Run clean robust extraction

Command:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/download_p3dh_robust.py \
  --date "31/12/2025" \
  --workers 4 \
  --refresh-minutes 8 \
  --request-delay-ms 150 \
  --max-requests-per-minute 60 \
  --refresh-discovery \
  --clean
```

Expected high-level result:

- 114 templates accounted for;
- 113 complete;
- 1 skipped: `K_83.01` known EBA/Power BI issue;
- 0 failed templates;
- 0 partial templates;
- 0 failed entities;
- 0 row-partition restart tokens remaining.

## 2. Review run manifest

Review:

```text
data/runs/p3dh/20251231_manifest.json
```

Check:

- status counts;
- `template_restart_token` fields;
- `entity_restart_token_count` fields;
- `row_partition_restart_token_count` fields;
- `failed_entities` is empty for completed templates;
- `K_83.01` is skipped explicitly.

## 3. Validate against local EBA dictionary/schema

Run:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/validate_p3dh_against_dictionary.py --date "31/12/2025"
```

Outputs:

```text
data/validation/p3dh_20251231_dictionary_validation.csv
data/validation/p3dh_20251231_dictionary_validation.json
```

Review:

- missing downloads;
- extra downloads;
- malformed facts;
- unmapped facts;
- duplicate fact keys;
- open-row templates noted separately.

## 4. NBG spot check

Verify National Bank of Greece specifically after the clean run.

Known entity:

```text
National Bank of Greece, S.A.
LEI: 5UMCZOEYKCVFAW8ZLO05
```

Check:

- NBG appears in downloaded raw files;
- NBG row counts are much higher than the previous incomplete 14-row package;
- NBG entity partitions with RT are resolved by row-level fallback;
- selected direct entity query counts match raw output for important templates.

## 5. Normalize and load SQLite after validation is clean

Run normalization only after the extraction and dictionary validation are acceptable:

```bash
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

## 6. Remaining improvements

- Make open-row template validation deeper using typed dimensions.
- Add direct row/cell partition fallback for open-row templates where row dictionary codes are unavailable.
- Add run-level validation summary combining manifest + dictionary validation + NBG spot checks.
- Split `scripts/download_p3dh_robust.py` into package modules once correctness is proven.
- Keep using conservative defaults (`workers=4`, `max_requests_per_minute=60`) to avoid hammering EDAP/Power BI.
