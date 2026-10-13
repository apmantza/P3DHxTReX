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
3. TREA must agree with the same quarter in other filings. A factor of 1,000 or 1,000,000 shows a column in the wrong unit (a tolerance of 8% allows for the FX effect). A column without TREA uses leverage exposure, CET1, total capital, or Tier 1 as the anchor, in this order. The vote of one column then applies to the other columns of the same filing, including a column T that no other filing covers.
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

## The generic engine (all other templates)

`scripts/clean_engine.py` cleans every template that has amounts and that is not handled by `clean_p3dh.py` or `clean_templates.py`. It uses no rule for a single template. It finds the rule in the data at each run.

An audit on 2026-10-13 tested the first version. About 14% of its repairs were wrong. The cause was that several anchors measure the size of the bank, so they vote as one, and that a real small value looks like a unit error. The engine now has four stages.

**Stage A. A candidate for each template.**

1. A cell is an amount, a ratio, or other. A label with a non-monetary word (tonnes, CO2, number of, years) is never an amount. Financed emissions (K_41.00 columns 0090 and 0100) are excluded.
2. The size of a filing is the 90th percentile of its non-zero amounts (the median for 2 or 3 cells). A filing with one amount cell has no size.
3. The size is compared with a clean quantity of the same bank and period: total assets, leverage exposure, TREA, Tier 1, CET1, OV1 RWEA by risk type, or the size of an earlier template. Each anchor has a main mode of log10(size / anchor). Filings 3 or 6 units away are unit-shifted. No other factor is allowed.
4. The filings of one bank with sizes that agree form a cluster with one unit. Each anchor votes once for the cluster. A tight base anchor has weight 2. A position between two modes is a vote for no shift. No unit error is the default. A shift needs a weight of at least 3, one tight base anchor, 1.5 times the weight of no shift, and a tight weight that is not below the tight weight of no shift.
5. Chain anchors (the size of another template) come only from unshifted filings. They are added at the end of a round, so the result does not depend on the order of the templates.

**Stage B. One filing at a time, across templates.**

6. A figure that is identical to a KM1 or OV1 cell of the same filing has the unit of that cell. Table `clean_cell_unit` holds the unit of each KM1 and OV1 cell. Figures of EUR 1 million or more match to the EUR. If the figures of one template match cells of different units, the template is removed.
7. Templates that share at least 3 figures (2 figures above EUR 100,000, or 1 figure above EUR 1 million) have one unit. The unit with at least twice the weight wins. A conflict removes the group.
8. A shift of a template with no identity partner stands only if the KM1 unit of the filing agrees (it then takes the exact KM1 factor, for example the Bulgarian lev peg) or at least 3 other templates of the filing have the same shift. Otherwise the filing is removed.

**Stage C. Bounds.** A shifted filing, or a filing that an identity rescued, with a maximum above 3 times total assets (or leverage exposure) is not shifted. A cell above 1,000 times total assets is reverted to its raw value or removed.

**Stage D. Neighbouring filings.** The same cells (row, column, key, sheet) in the filings of one bank must be of one size. A filing that jumps by 1,000 or more against agreeing neighbours is rescaled to match them, when a factor of 1,000 or 1,000,000 fits within 0.75 decades. Otherwise it is removed. Two filings that disagree: the one farther from the size of the bank is odd, or both are removed.

Other rules:

- A filing of ratio cells in percentage points is found by the median of its cells against the population median of the same cells.
- An all-zero filing is removed only if the same bank has amounts for the template in another filing.
- A filing without an anchor is removed only if its own KM1 was removed (`scale_unresolved`). Otherwise it stays `unverified`.

Quality values in `clean_fact`: `ok`, `ok_wide` (ratio to the anchor outside the usual range), `ok_history`, `ok_tie` (identical figures decide), `rescaled`, `rescaled_tie`, `rescaled_nb` (neighbouring filings decide), `cell_reverted`, `converted`, `suspect`, `unverified`, `untested` (not an amount), and `quarantined` (value removed).

Limits that the engine cannot solve:

- A template with cells of two units in one filing (for example Zagrebacka banka K_71.00, APS Bank K_66.02). The engine removes the filing when neighbours show the jump, or leaves it when no neighbour exists.
- A bank that files in thousand or million in every filing and in every template (La Banque Postale, DLR Kredit). KM1 is removed (`suspect_scale`), so all templates of these filings are `scale_unresolved`. An external value of total assets (Bloomberg `BS_TOT_ASSET`) can set the unit.
- A single weak vote with no partner (NLB K_03.00). The filing is removed, although the raw values are probably right.

## New data

Rule: test every new filing again. Do not assume that a bank repeats its unit.

- Unit errors belong to a filing. SocGen, Raiffeisen Bank International, Zagrebacka banka, AL Sydbank, and Citibank Europe each changed unit between filings.
- The Hub changes layouts. The sub-table letters of OV1 changed from 31/03/2026.
- `scripts/refresh_p3dh.py` runs all steps for all data at each refresh. The steps are idempotent.
- The engine fails closed. A filing that cannot be tested, or that two tests judge differently, has its amounts removed (`quarantined`). It is not passed.
- A new filing is tested against the history of the bank (stage D). The history confirms or contradicts. It never sets the unit by copying. In a test on a copy, copying the unit of the previous filing was wrong for every injected error, because a new unit error is not the unit of the old filing.
- A refresh can change the decision for old filings, because the calibration of a template uses all filings. The table `clean_release_diff` lists every filing whose state changed since the last run. Review it before you use the new numbers. The engine prints the number of changes and the templates whose calibration moved (`clean_run_log`).
- `scripts/verify_clean.py` runs after each refresh. It tests: (1) the same cells in neighbouring filings, (2) the arithmetic (value = raw value times factor), (3) a list of known cases, (4) identity: identical figures in two templates have one unit, (5) the bound of 3 times total assets, and (6) 15 fixtures from the audit.
- `scripts/injection_test.py` multiplies the newest filing of 40 banks by 0.001 in a copy of the database, runs the clean steps, and counts the injected filings that stay silent. Run it after each change of the rules. It needs about 25 minutes and 4 GB.
  Result of 2026-10-13: of 659 injected filings of the generic engine, 533 were repaired, 121 were removed, and 5 stayed silent (0.8%; all of Kommunalbanken, a public lender with no TREA). Of 39 injected KM1 filings, 38 were repaired and 1 was removed (0% silent). The limits are 5% silent and 80% handled. A first run found 2 silent KM1 filings of banks that file no TREA in the new column. The anchor rule of rule 3 closed this gap.
- Review the removed filings after each refresh: `SELECT * FROM dq_flag WHERE action = 'quarantine'`.

## Coverage by date

- A missing bank has no data. It does not have the value 0.
- At 30/06/2026 about 60 of the 162 quarterly KM1 filers of 31/03/2026 are absent. Alpha Bank and Eurobank are among them. Peer sets at this date are biased.
- Eurobank is absent at 30/06/2025 and 30/09/2025. Later filings supply those quarters through T-2 and T-3.
- The filing of 31/10/2025 holds 4 banks with an October year end. It is not a quarter end.
- Open tables (K_26.00, K_67.01, K_95.00 to K_98.00) have a blank key for one member of each cell group. Do not pivot these facts by key.

## Known limits

- The OV1 total of Piraeus is 1% to 2% above the KM1 TREA. OV1 includes the TREA equivalent of the 1250% deduction. The difference is exact.
- OV1 T-1 is not in the period views. The Sep-25 OV1 values come from the 30/09/2025 filing.
- Cells that are not amounts (ratios, counts) get only the percent test. Counts that carry the FX rate (CCR1 alpha, OR1 counts) are not repaired.
- Open tables have a blank key for one member of each cell group. The engine tests the size of the whole filing and does not repair single rows.
- K_83.01 is not downloaded. The server times out.
- The ratio cells of KM2 (K_90.01) are in fractions for some banks and in percentage points for others. They have the quality `untested`. The M&A model tests the unit of each filing with own funds divided by TREA.
- K_67.01 (CCyB1, exposures by country) is an open table. It has no clean layer, so the M&A model has no country split of exposures.
- NBG and Alpha Bank use different profit-recognition bases for CET1 in some quarters. Both values are valid.
