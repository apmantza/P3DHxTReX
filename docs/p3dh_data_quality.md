# P3DH data quality

This document describes what the P3DH data contains, which source problems exist, and how the clean layer treats them. The assessment ran on 2026-10-09 on the filings of 31/12/2025, 31/03/2026, and 30/06/2026.

## Result of the assessment

The database is a faithful copy of the Hub data. The raw responses, the CSV files, and the SQLite tables hold the same 2,634,769 facts. The decoder and the loader add no errors.

The Hub data itself has errors. The Hub has no unit field. Banks file amounts in euro, thousand, or million. The Hub converts other currencies to euro. Some banks file ratios as percentage points.

For the four Greek banks, 387 of 399 KM1 cells and 171 of 180 OV1 cells equal the bank Pillar 3 reports. Every difference sits in the source.

## Abbreviations

| Term | Meaning |
|------|---------|
| EBA | European Banking Authority |
| P3DH | Pillar 3 Data Hub |
| KM1 | Template K_61.00, key metrics |
| OV1 | Template K_60.00, overview of risk-weighted exposure amounts |
| TREA | Total risk exposure amount (also called RWEA, risk-weighted exposure amount) |
| CET1 | Common Equity Tier 1 |
| LCR | Liquidity coverage ratio |
| NSFR | Net stable funding ratio |
| ECB | European Central Bank |
| LEI | Legal entity identifier |
| pp | Percentage points |

## Data dictionary

| Topic | Rule |
|-------|------|
| Currency | Amounts are in euro. For a bank that files in another currency, the Hub converts at the ECB rate of the filing date. |
| FX effect | The same quarter has a different euro amount in each filing. The factor is the same for every row and every column of one bank. Ratios do not change. |
| Unit | No unit field exists. About 3% of KM1 filings have amounts that are 1,000 or 1,000,000 times too small. |
| Ratios | 97% to 98% of the ratio cells are fractions (0.18 means 18%). About 2% are percentage points or use another factor. |
| T-n in KM1 | T-1 to T-4 are the previous four quarters for quarterly banks. About 25 half-yearly banks fill T-1 with the previous disclosure date (6 months back). The clean layer finds these columns and re-dates them (see rule 5). |
| T-n in OV1 | T-1 is the previous disclosure date. It is 3, 6, or 12 months back. The period views use only column T of OV1. |
| T-n in other templates | The meaning differs by template. Add a template to `period_template` only after you check it. |
| Reference date | A filing has one reference date. Later filings restate earlier quarters. |
| Zero | Some banks file 0 for a missing value. A column with CET1, Tier 1, total capital, and TREA equal to 0 has no data. |
| Sign | The sign of impairments and expenses differs by bank. Do not sum signed impairments across banks. |
| Sub-tables | OV1 has the sub-tables `K_60.00.a`, `.b`, and `.c`. The Hub moved some rows between them. The period views ignore the sub-table. |
| Entity | The key is `entity_key`. One LEI can appear under two names (for example Piraeus Financial Holdings and Piraeus Bank in 2025). Map banks by LEI, never by name. Aareal Bank and Atlantic Lux share one LEI. |
| Population | A filing contains only the banks that report at that frequency. Quarterly reporters are fewer at 30/06/2026 than at 31/03/2026. |

## Source problems that the clean layer handles

| Problem | Example | Treatment |
|---------|---------|-----------|
| Amounts in thousand or million | Eurobank leverage exposure T-1 to T-4 in the 31/12/2025 filing | Rescale when a second source agrees. Otherwise remove. |
| Whole filing in the wrong unit | AL Sydbank 31/03/2026, Aktia 30/06/2026 | Rescale when the same quarter in another filing shows the factor. |
| Ratio in percentage points | Societe Generale, Belfius, La Banque Postale | Rescale when capital divided by TREA confirms the factor. |
| Zero placeholder | Eurobank OV1 total at 31/12/2025 | Remove. The next older filing can supply the quarter. |
| Sentinel value | 999999 in LCR | Remove. |
| Negative capital amount | AL Sydbank CET1 | Remove. |
| Size below EUR 10 million TREA | Banks that file in million in every filing | Remove the amounts. Keep the ratios. |

The clean layer cannot repair a bank that files in million in every filing and every column. No second source exists. La Banque Postale is an example. The amounts of such a bank stay out of the clean layer.

## Rules of the clean layer

Script: `scripts/clean_p3dh.py`. Input: view `v_period_fact`. Output: tables `dq_flag` and `clean_period_fact`.

A repair multiplies a cell by a power of 10. The script repairs a cell only when two sources agree:

1. A ratio must agree with the ratio that the same column gives (capital divided by TREA, Tier 1 divided by leverage exposure, ASF divided by RSF, HQLA divided by net outflows).
2. An amount must have a plausible size against TREA of the same column. For example, HQLA divided by TREA must be between 0.3% and 800%. Exactly one factor (1,000 or 1,000,000) must bring a wrong amount into the range. If all amounts of a column are wrong by the same factor, the script rescales TREA.
3. TREA must agree with the same quarter in other filings. A factor of 1,000 or 1,000,000 shows a column in the wrong unit (a tolerance of 8% allows for the FX effect).
4. A cell that is off by 1,000 or 1,000,000 against at least 3 other columns of its filing, which agree with each other, is repaired.
5. A KM1 column T-k is dated by an overlap test. The three capital ratios of the column must match column T of the same bank in the filing k quarters earlier. If they match the filing at another lag, the column gets that period. If the match is unclear, or two columns of one filing get the same period, the script removes the cells.

The script rescales a cell once. It removes a cell that needs a second repair. It also removes a cell that fails a test and has no repair. The table `dq_flag` lists every change with the check name, the factor, and the filing.

The script tests these rows of KM1: CET1, Tier 1, total capital, TREA, TREA before the floor, the three capital ratios and their unfloored companions, leverage exposure, leverage ratio, HQLA, outflows, inflows, net outflows, LCR, ASF, RSF, and NSFR. All other rows pass through without a test. For OV1 the script tests the total and the scale of column T.

After the tests, the script chooses one value for each entity, quarter, row, and measure:

1. The latest filing that has a valid value wins.
2. The main sub-table (`.a`) wins over `.c` in one filing.

A zero in a tested row is not valid and does not enter the clean layer. A zero in another row is a value.

## How to use the data

Use the clean layer for panels and cross-bank statistics.

- Use KM1 row 0040 as the TREA of record. Use OV1 for the split by risk type.
- Use a fixed list of banks for a median. Show the number of banks (N) for each period.
- Do not compare Greek banks at 30/06/2026 with a full peer set. Alpha Bank and Eurobank have not filed that date.
- Do not use alpha, event counts, the output floor percentage, MREL, or LR2 ratios as delivered.
- State the basis of a time series: first reported or latest restated.
- A non-euro bank has an FX effect in its euro amounts. Use ratios for such banks.

## Templates without a clean layer

The clean layer covers KM1 and OV1 only. These templates carry the same unit problems, in 3% to 14% of the entity-dates, and no test covers them:

- Climate risk (K_41.00 to K_45.00), remuneration (K_30.01), IRRBB (K_68.00), insurance (K_62.01), encumbrance (K_20.01 to K_20.03), ranking in insolvency (K_95.00 to K_98.00), CCyB (K_67.01), and G-SIB (K_101.00 to K_113.00).
- Three of 13 G-SIB banks file in million or thousand.
- Non-monetary cells (CCR1 alpha, event counts, output floor percentage) carry the FX rate or the unit factor of the bank.

Do not sum, rank, or average amounts of these templates across banks. Use them for one bank in one filing.

## Coverage by date

- A missing bank has no data. It does not have the value 0.
- At 30/06/2026 about 60 of the 162 quarterly KM1 filers of 31/03/2026 are absent. Alpha Bank and Eurobank are among them. Peer sets at this date are biased.
- Eurobank is absent at 30/06/2025 and 30/09/2025. Later filings supply those quarters through T-2 and T-3.
- The filing of 31/10/2025 holds 4 banks with an October year end. It is not a quarter end.
- Open tables (K_26.00, K_67.01, K_95.00 to K_98.00) have a blank key for one member of each cell group. Do not pivot these facts by key.

## Known limits

- The OV1 total of Piraeus is 1% to 2% above the KM1 TREA. OV1 includes the TREA equivalent of the 1250% deduction. The difference is exact.
- OV1 T-1 is not in the period views. The Sep-25 OV1 values come from the 30/09/2025 filing.
- Two kinds of cells have no check: open tables (K_26.00, K_29.00, K_43.00, K_95.00 to K_98.00) and non-monetary cells (CCR1 alpha, event counts).
- K_83.01 is not downloaded. The server times out.
- NBG and Alpha Bank use different profit-recognition bases for CET1 in some quarters. Both values are valid.
