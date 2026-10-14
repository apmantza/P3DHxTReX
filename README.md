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

Refresh all derived tables after a download or a load. This runs the four steps below in order (load, clean KM1 and OV1, classify, clean IRRBB and encumbrance):

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/refresh_p3dh.py
```

The steps can run alone. `clean_p3dh.py` tests KM1 and OV1 for wrong units and zero placeholders and writes `dq_flag` and `clean_period_fact`. `classify_p3dh.py` writes the geography and size classes. `clean_templates.py` cleans IRRBB1 (`K_68.00`) and encumbrance (`K_20.01` to `K_20.03`), writes `clean_fact`, and writes the working note `docs/p3dh_template_status.md`.

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
- `v_period_fact`: facts in columns that are labelled `T` or `T-n`, with `period_end`. It has one row for each filing, so a quarter can appear in several filings.
- `v_latest_period_fact`: for each entity, quarter, row, and measure, the value from the latest filing. The sub-table `.a` wins over `.c` in one filing. It does not test units. Use `clean_period_fact` for panels.

Tables from `scripts/clean_p3dh.py`:

- `clean_period_fact`: the same rows after the unit and zero tests. `value` is the clean value, `value_raw` is the value from the Hub, `quality` is `ok` or `rescaled`, and `factor` is the multiplier.
- `dq_flag`: every cell that the tests changed or removed, with the check name and the factor.

- `clean_fact`: the facts of IRRBB1 and AE1 to AE3 with `value_raw`, `value`, `quality`, `unit_inferred`, and `factor`. The view `v_clean_fact` leaves out the removed values (`quality` is `quarantined`).

Later filings restate earlier quarters. Use `clean_period_fact` when you need the latest valid value.

### Geography and size

Each entity has a country group and a size class. `classify_p3dh.py` computes them.

- `v_entity_class`: one row for each entity: country, ISO code, region, peer group (greek, periphery, core, other), euro area flag, current total assets in EUR, `size_basis` (`total_assets` or `leverage_exposure`), and `size_class`.
- `v_entity_assets_class`: the same for each entity and period end (total assets over time).
- `dim_country` and `dim_size_class`: lookup tables. Edit them with SQL. The views read them at query time.
- `entity_assets` and `entity_size_current`: total assets of the published financial statements, with the test result of each value.

Size classes (total assets in EUR): Small below 10bn, Medium 10bn to 100bn, Large 100bn to 250bn, Very large 250bn and above. An entity with no total assets uses the leverage exposure of KM1 (`size_basis`). An entity with neither value is `Unclassified`.

```sql
SELECT size_class, peer_group, COUNT(*) FROM v_entity_class GROUP BY 1, 2;
```

The meaning of `T-n` differs between templates. For example, OR1 uses years. Only the templates in the table `period_template` appear in the period views. KM1 uses columns T to T-4 (quarters). OV1 uses column T only, because OV1 T-1 is the previous disclosure date (3, 6, or 12 months back). Add a template to that table only after you check what its columns mean. A filing with a reference date that is not a quarter end (31/10/2025) is not in the period views.

`docs/p3dh_data_quality.md` is the data dictionary. It lists the source problems and the rules of the clean layer.

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

## Dashboard

The dashboard is a local Streamlit app. It opens the database read-only and listens on `localhost` only. It needs no account, no registration, and no network. Usage statistics are off (`dashboard/.streamlit/config.toml`).

```bash
python -m venv dashboard/.venv
dashboard/.venv/Scripts/pip install -r dashboard/requirements.txt
dashboard/.venv/Scripts/python -m streamlit run dashboard/Overview.py --server.port 8765
```

On Windows, double-click `dashboard/run_dashboard.bat`. Then open `http://localhost:8765`.

Pages: Overview, Peer explorer (KM1 by size and geography), Greek banks (against a cohort median), IRRBB, Encumbrance, Entity browser, Data quality (includes the template status note), M&A scenario. The pages read the clean layer. After `scripts/refresh_p3dh.py` the pages show the new data without a restart.

### M&A scenario

The page `M&A scenario` combines NBG with up to three banks of P3DH. It runs the formulas of the Excel file `docs/M&A calc v2.xlsx` (sheets Calc and Merger), so the page and the file give the same numbers. Data: P3DH (capital, buffers, MREL, leverage, liquidity, IRRBB) and the Bloomberg tables of the same database (price, consensus, profit, opex, tax rate, rates). A bank without listed shares (BIL, HCOB) is valued with its nearest listed European peers of P3DH (median P/TBV and P/CET1 of the banks with the closest return). The page shows the first-year analysis, a four-year merger model (2026E to 2029E), the regulatory view, sensitivity grids, the issuance needs (CET1, AT1, Tier 2, and MREL layers, with requirements weighted by RWAs, the AT1 and Tier 2 buckets from the P2R, and a subordination assumption from the filings of other banks), the data used (with the average deposit rate for each year, half year, and quarter), and a review of the original sheet. You can download the file with your inputs.

```bash
dashboard/.venv/Scripts/python scripts/build_ma_workbook.py   # build docs/M&A calc v2.xlsx
dashboard/.venv/Scripts/python scripts/test_ma_workbook.py    # tests (evaluator, identities, data policy, page)
dashboard/.venv/Scripts/python scripts/test_bbg.py            # tests of the Bloomberg modules
```

`docs/ma_model.md` gives the formulas, the sources, and the limits.

### Bloomberg data

The tables `bbg_*` of the database hold rates and curves since 1999, the average deposit rate per month, quarter, half year, and year, the expected deposit rate from the OIS curve, every P3DH bank matched to Bloomberg (by LEI, by a LEI rebuilt from the P3DH code, or by name) with its equity, parent, and debt tickers, prices and fundamentals of the listed banks, consensus, the 20 largest holders of the listed banks with state participation, and the bonds with an outstanding amount above EUR 150m (the universe) with price, yields (maturity, call, worst), I-, Z-, and G-spreads, and a daily history. Pull the data with the Python of the blauto project (it has `blpapi`; the terminal must run):

```bash
C:\Users\E40889\Documents\blauto\.venv\Scripts\python scripts/pull_bloomberg.py rates      # then: entities, equity, ownership, bonds, bondmarket, bondhist, status
```

The data is not in git. Do not publish it. Refresh the data by cadence with `scripts/refresh_bloomberg.py daily | weekly | monthly` (or `refresh_bloomberg.bat`): only the monthly run requests new unique securities. `scripts/mrel_vs_bonds.py --lei <LEI>` compares the MREL templates of P3DH with the bonds of a bank. `docs/bloomberg_db.md` describes the tables, the limit of unique securities, the matching, the market basis, the ownership data, and the limits of the bond data.

### External statistics by country (ECB, Eurostat)

The tables `ext_*` hold public statistics for every EU country in one schema: rates of banks (new loans, the book, deposits), stocks and growth of loans and deposits, the bank lending survey, profit and loss and ratios of the banks of a country, supervisory ratios, the structure of the banking sector, market rates, and the economy (house prices, GDP, unemployment, inflation, government debt). They need no terminal and no key:

```bash
python scripts/pull_ext.py all        # 60 curated indicators, about 75 seconds
python scripts/pull_ext.py bulk       # every series of the ECB sets MIR, BSI, BLS, CBD2, SUP, SSI with the full history (about 5.5 million observations)
python scripts/pull_ext.py status     # what the database holds
```

Each series has a `concept` (its key without frequency and country), so one join compares the same measure in all countries. The table `ext_geo_group` holds 11 geographic groups (Benelux, DACH, Southern Europe, and others).
Two tools use the data:

```bash
python scripts/pass_through.py --group Benelux      # pass-through of the 3-month Euribor to deposit and loan rates, by country, product, and rate cycle (table ext_passthrough)
python scripts/benchmark_bank.py --lei <LEI>        # one bank against its country, the euro area, the EU, and its groups: capital, liquidity, asset quality, income, loan mix, loan growth, rate sensitivity
```

`docs/external_statistics.md` describes the sources, the tables and views, the method and the limits of the pass-through and of the benchmark, and the ECB list of supervised entities (checked, not loaded yet).

## Rules

- Run one downloader process at a time. A lock file in `data/runs/p3dh` enforces this. The default limit is 60 requests per minute.
- Do not delete `data/raw/P3DH_json`. It is the only source from which the CSV files can be rebuilt without the network.
- Run `scripts/verify_p3dh.py` after each download.

## More information

`docs/p3dh_extraction.md` describes the response format, the paging method, and the defects that earlier versions had.
