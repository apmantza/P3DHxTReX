# P3DH data pipeline

This repository downloads disclosures from the Pillar 3 Data Hub (P3DH) of the European Banking Authority (EBA). It stores them in SQLite and verifies them.

The data source is the EBA data portal (EDAP). The P3DH report on EDAP is an embedded Power BI report.

## Setup

Use the project virtual environment. Do not install packages globally.

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/playwright install chromium
```

## Commands

Download all templates for one reference date:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/download_p3dh.py --date "31/12/2025" --all
```

Download selected templates:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/download_p3dh.py --date "31/12/2025" --template K_61.00 K_60.00
```

Load the files into SQLite. The loader is incremental. It reloads only files whose hash changed.

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/build_p3dh_db.py
```

Verify the files, the manifest, and the raw archive:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/verify_p3dh.py
```

Rebuild the CSV files from the raw archive after a decoder change. This command needs no network:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/redecode_p3dh.py
```

The downloader opens a browser window (Playwright Chromium) to capture the report query. Set `P3DH_HEADLESS=1` to hide the window.

## Reference dates

The portal lists its reference dates. The downloader stops if you request a date that is not listed. Each date has its own template list.

## Output

| Path | Content |
|------|---------|
| `data/raw/P3DH/<yyyymmdd>/K_xx.xx_data_points.csv` | One row per fact |
| `data/raw/P3DH_json/<yyyymmdd>/K_xx.xx.jsonl.gz` | Raw responses from the portal |
| `data/runs/p3dh/<yyyymmdd>_manifest_v2.json` | Status, counts, and checks for each template |
| `data/runs/p3dh/<yyyymmdd>_templates.json` | Templates that the portal lists for the date |
| `data/processed/p3dh.sqlite` | The database |

The `data/` directory is not tracked in git.

CSV columns: `reference_date`, `entity_lei`, `entity_name`, `country`, `module_name`, `module_code`, `cell_code`, `key_descriptor`, `template`, `row_code`, `row_label`, `column_code`, `column_label`, `sheet`, `fact_value`, `fact_text`.

- `cell_code` is the Data Point Model (DPM) cell, for example `{K_61.00, r0050, c0010}`.
- A fact has a number in `fact_value` or text in `fact_text`. It never has both.
- The pair (`entity_lei`, `entity_name`) identifies a reporting entity. One LEI can appear under two names.

## Database

Tables: `filing` (one row per date and template), `dim_template`, `entity`, `fact`.

Views:

- `v_fact`: facts with entity name, country, and `entity_key`.
- `v_coverage`: every template that the portal lists, with its download status.
- `v_period_fact`: facts in columns that are labelled `T` or `T-n`, with `period_end`.
- `v_latest_period_fact`: for each entity, quarter, row, and measure, the value from the latest filing.

Later filings restate earlier quarters. Use `v_latest_period_fact` when you need the latest value.

The meaning of `T-n` differs between templates. For example, OR1 uses years. Only the templates in the table `period_template` (now KM1 and OV1, both quarterly) appear in the two period views. Add a template to that table only after you check what its columns mean.

`entity_key` is the LEI. It is the LEI plus the name only when one filing holds the same LEI under two names (Aareal Bank AG and Atlantic Lux HoldCo). A renamed entity keeps one key across filings.

`fact.seq` is the position of the fact in the file. Facts with a concrete cell code are unique by cell, key descriptor, and sheet. Open-table labels have no cell code and can repeat.

## Download status

The manifest gives each template one status:

| Status | Meaning |
|--------|---------|
| `complete` | Paging finished, no restart token remains, and the entity cross-check agrees |
| `partial` | The result has a known gap, or it came from the entity-list fallback (completeness not proven) |
| `empty` | The portal answered completely and has no rows |
| `failed_server` | The portal returned an error for every request |
| `skipped_slow` | The template is known to time out on the server (`K_83.01`) |
| `error` | The download stopped with an exception |

A new attempt that is not `complete` never replaces files from an earlier `complete` download.

Example: CET1 ratio of one bank for each quarter.

```sql
SELECT period_end, value
FROM v_latest_period_fact
WHERE template_code = 'K_61.00' AND row_code = '0050'
  AND entity_name LIKE 'National Bank of Greece%'
ORDER BY period_end;
```

## Rules

- Run one downloader process at a time. A lock file in `data/runs/p3dh` enforces this. The default limit is 60 requests per minute.
- Do not delete `data/raw/P3DH_json`. It is the only source from which the CSV files can be rebuilt without the network.
- Run `scripts/verify_p3dh.py` after each download.

## More information

`docs/p3dh_extraction.md` describes the response format, the paging method, and the defects that earlier versions had.
