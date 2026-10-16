# External statistics by country (ECB and Eurostat)

This part of the database holds public statistics for every EU country. It answers questions about the business model of a bank:
how the spread of new loans moves, how fast loans and deposits grow, how much of a rate change the banks pass to depositors, and how profitable the banks of a country are.
It also lets you compare one bank with its country, the euro area, the EU, and geographic groups.
The data is free. It needs no terminal and no key.

## Sources

| Source | Dataset | What it holds | Frequency | Countries |
|---|---|---|---|---|
| ECB Data Portal | MIR | Rates of banks: new business and outstanding loans, deposits | monthly, from 1999 | 28 areas: the euro area members, and the 6 non-euro countries in their own currency (from 2004 or 2005) |
| ECB Data Portal | BSI | Balance sheet of the banks of a country: stocks, growth rates, and flows of loans and deposits by sector. Counterpart: the euro area, split into the country itself and the other euro area countries | monthly, from 1999 | EU countries (most series: euro area members) |
| ECB Data Portal | BLS | Bank lending survey: credit standards and loan demand (net percentage of banks) | quarterly, from 2003 | euro area members |
| ECB Data Portal | CBD2 | Consolidated banking data of domestic banks: profit and loss, ratios, assets, capital, asset quality | annual and quarterly, from 2007 | EU countries |
| ECB Data Portal | SUP | Supervisory banking statistics of all supervised banks: return on equity, margin, cost-to-income, LCR, NPL, leverage ratio | quarterly, from 2015 | euro area members |
| ECB Data Portal | SSI | Structure of the banking sector: number of banks, employees, concentration | annual, from 1999 | EU countries |
| ECB Data Portal | RAI | Risk assessment indicators of the banking sector: lending margins on new loans, share of interbank loans, leverage ratio, loan-to-deposit ratio, share of variable rate loans, funding structure | monthly and quarterly | EU countries (a few series for each country) |
| ECB Data Portal | IRS | 10-year government bond yield (convergence criterion) of each country, and money market rates in local currency | monthly | yields: all EU countries; money market rate: CZ, HU, PL, RO |
| ECB Data Portal | RESR, RESH | Residential property prices (index and growth) and structural housing indicators, whole country | quarterly, annual | EU countries |
| ECB Data Portal | CLIFS, CISS | Country-level index of financial stress; composite indicator of systemic stress (euro area) and of sovereign stress (large countries) | monthly, daily | CLIFS: all EU countries; CISS: the euro area and about 15 countries |
| ECB Data Portal | EST, FM | Euro short-term rate, 3-month Euribor, deposit facility rate | daily, monthly | euro area |
| Eurostat | prc_hpi_q, namq_10_gdp, une_rt_m, prc_hicp_minr, gov_10q_ggdebt | House prices, GDP, unemployment, inflation, government debt | quarterly, monthly | EU countries |
| Eurostat | irt_st_m, irt_lt_mcby_m | 3-month money market rate (countries with their own currency), 10-year government bond yield | monthly | money market rate: BG, CZ, DK, HR, HU, PL, RO, SE; yield: all EU countries |
| Eurostat | tipspd22, tipspd20, ei_bsco_m, nasq_10_f_bs | Household debt and private sector debt (% of GDP), consumer confidence, deposits and loans of households and of companies (financial accounts) | annual, monthly, quarterly | EU countries |
| EBA | EU-wide Transparency Exercise (TE2025) | Bank-by-bank data of 119 banks: P&L, capital, leverage, assets, liabilities, sovereign exposures by country, market risk, credit risk and asset quality by country and sector | quarterly: 30 Sep 2024 to 30 Jun 2025 | 25 EU and EEA countries (see "EBA Transparency Exercise") |

Data sets that were checked and are not loaded: SEC (securities issues: the ECB data stops in March 2022), KRI (EBA key risk indicators on the ECB portal: 24 aggregate series that end in Q2-2024), and SAFE (survey of SMEs on access to finance: large, no data for Luxembourg).

Domestic banks (CBD2) are the banks that have their head office in the country. A foreign bank in the country is not in these numbers.
In a country where foreign banks dominate, the domestic banks are a small part of the sector (see "Limits of the benchmark").

## Two ways to load the data

| Command | What it loads | Use |
|---|---|---|
| `pull_ext.py all` | 60 curated indicators with readable names (for example `mir_cob_nfc`), from 2010 | Quick start and the views `v_country_growth` and `v_country_spreads` |
| `pull_ext.py bulk` | Every series of MIR, BSI, BLS, CBD2, SUP, SSI, RAI, IRS, RESR, RESH, CLIFS, and CISS, with the full history | Benchmark, pass-through, and any new question |
| `pull_ext.py eba` | The EBA Transparency Exercise (4 CSV files, about 230 MB) | Bank-by-bank P&L and exposures (see "EBA Transparency Exercise") |

The database holds about 129,000 series and 8.9 million observations after the bulk pull and the curated pull. The catalogue of a data set gives titles and units. One request for each country gives the observations.
The ECB server sometimes answers with HTTP 504 or a timeout. The fetch function waits 5, 20, and 60 seconds and tries again. A country or a data set that still fails is reported, and the other data sets go on.
To load a failed part again, run `pull_ext.py bulk --flows RAI --areas LV,LU,SE`.
BSI is limited to the sector "monetary financial institutions excluding the central bank", all currencies, and the counterpart areas U2 (the euro area), U6 (the country itself), and U5 (the other euro area countries). It holds stocks, growth rates, and flows.
Lending to residents outside the euro area is not in BSI. For a country such as Luxembourg this is a large part of the balance sheet, so a loan mix from BSI is biased.
RESR and RESH keep only the series of the whole country (REGION `_T`): the regional series are not comparable between countries.
A series that the curated pull stored keeps its curated indicator name. A new series gets its concept as the indicator name.

## Tables

| Table or view | Content |
|---|---|
| `ext_country` | The 27 EU countries and the euro area (`U2`). Greece is `GR` here and `EL` at Eurostat. |
| `ext_series` | One row for each series: source, key, indicator, country, frequency, unit, title, first and last period, number of observations, data set (`flow`), `concept`, `dims`, `unit_mult`. |
| `ext_obs` | One row for each observation: period as the source writes it, last day of the period, value, status flag. |
| `ext_geo_group` | Geographic groups of countries (group name, country). The user can edit it. |
| `ext_passthrough` | Betas by country, product, and rate cycle (see "Pass-through"). |
| `ext_pull_log` | One row for each pull: series, observations, status. A bulk pull is logged as `bulk:<data set>`. |
| `v_ext_obs` | Observations with indicator, concept, country, frequency, unit. Start here. |
| `v_ext_latest` | The last observation of each series. |
| `v_country_growth` | Annual growth of the monthly stocks (`bsi_*`), computed from the stocks. |
| `v_country_spreads` | Each rate (`mir_*`) less the 3-month Euribor of the month. For deposits `deposit_margin` is the opposite. |

The schema is one long table. A new country or a new indicator needs no new column and no new table.

## Concept: one name for the same measure in all countries

The `concept` of a series is its key without the frequency and without the country.
For example `MIR/B.A2I.AM.R.A.2240.EUR.N` is the cost of borrowing of corporations in every country.
A join on the concept compares the countries. The key `MIR.M.LU.B.A2I.AM.R.A.2240.EUR.N` (Luxembourg) and `MIR.M.DE.B.A2I.AM.R.A.2240.EUR.N` (Germany) have the same concept.
The counterpart area of a BSI key (for example `U2`) stays in the concept. Only the country of the series is removed.

A concept can have an annual series and a quarterly series. Always filter on `freq`.

```sql
SELECT country, period, value FROM v_ext_obs WHERE concept = 'MIR/B.L21.A.R.A.2250.EUR.N' AND freq = 'M' AND period >= '2022-01';
```

## Geographic groups

The table `ext_geo_group` holds 11 groups. The groups are seeded once. Edit the table to change them.

| Group | Countries |
|---|---|
| Euro area (members) | AT, BE, BG, HR, CY, EE, FI, FR, DE, GR, IE, IT, LV, LT, LU, MT, NL, PT, SK, SI, ES |
| EU27 | all 27 |
| Non-euro EU | CZ, DK, HU, PL, RO, SE |
| Benelux | BE, NL, LU |
| DACH | DE, AT |
| Nordics | DK, SE, FI |
| Southern Europe | ES, IT, PT, GR, CY, MT |
| Baltics | EE, LV, LT |
| Central and Eastern Europe | PL, CZ, SK, HU, SI, HR, RO, BG |
| Core euro area | DE, FR, NL, AT, BE, LU, FI |
| Periphery | ES, IT, PT, GR, IE, CY |

`modules/ext/analytics.py` has `aggregate(conn, concept, group, weight)`. It gives the weighted mean, the simple mean, the median, the minimum, the maximum, and the number of countries for each month.
The weight is another concept of the same month (for example the deposit stock). A country without a weight is left out of the weighted mean.

## Pass-through of market rates to deposit and loan rates

The beta of a cycle is the change of the bank rate divided by the change of the 3-month Euribor, from the start to the end of the cycle.
Each rate is the average of 3 months. This removes the noise of one month.

| Cycle | Start | End |
|---|---|---|
| hike 2005-08 | 2005-11 | 2008-09 |
| cut 2008-10 | 2008-09 | 2010-06 |
| hike 2022-23 | 2022-06 | 2023-12 |
| cut 2024-25 | 2024-06 | 2025-12 |
| hike 2026 (to date) | 2026-02 | 2026-08 |

The table has 12 products: deposits of households and of corporations (overnight, agreed maturity new business, agreed maturity outstanding, redeemable at notice) and loans (corporations, house purchase, consumer credit; new business and outstanding).
`months_to_half` is the number of months until the bank rate has made half of its move.
A cycle in which the Euribor moves less than 0.5 points has no beta. The cycle that is not finished needs a move of 0.25 points. Its betas are early and can change.

```
python scripts/pass_through.py                       compute and store ext_passthrough, print the euro area
python scripts/pass_through.py --country LU,GR       betas of countries
python scripts/pass_through.py --group Benelux       betas of a group, weighted by the stocks at the start of the cycle
python scripts/pass_through.py --product deposits    only the products that start with this text
```

The euro area betas are in the expected ranges. A household overnight deposit follows less than a quarter of a rate move in the 2022-23 cycle. New deposits with an agreed maturity follow about 70%. The test `scripts/test_ext.py` checks these ranges.

Limits:
- A beta mixes the change of the rate with the change of the mix of the business (new business in a month can be small in a small country).
- The euro area cycles above apply to the members of the euro area. A country that joined late has fewer cycles.

### Countries with their own currency (CZ, DK, HU, PL, RO, SE)

These countries have their own rate cycles. `pass_through_local` (in `modules/ext/analytics.py`) uses, for each country:
- the 3-month money market rate of the country as market rate (Eurostat `irt_st_m`, indicator `es_mm_3m`);
- the bank rates in the local currency (the euro concept with the currency of the country, for example `MIR/B.L21.A.R.A.2250.PLN.N`);
- cycles from the turning points of the local rate: a leg is a move of at least 1 point between a trough and a peak, measured on the average of 3 months.
The cycle name holds its dates, for example `hike 2021-06..2022-07 (local)`. The last leg can be a cycle that is not finished.
The betas of these countries cannot be compared by cycle name with the euro area, and a group beta is not weighted (the stocks are in local currency).
`scripts/pass_through.py` computes both sets and stores them in the table `ext_passthrough`.
- A group beta is the mean weighted by the stock of the sector at the start of the cycle. A group with 2 or 3 countries is sensitive to one country.

## Benchmark of a bank

The benchmark compares one bank with the banks of its country, the euro area, the EU, and the geographic groups of its country.

```
python scripts/benchmark_bank.py --lei <LEI>
python scripts/benchmark_bank.py --lei <LEI> --country LU --groups Benelux,DACH --since 2025
python scripts/benchmark_bank.py --lei <LEI> --xlsx "benchmark.xlsx"
```

The code is in `modules/ext/bank_metrics.py` (figures of the bank) and `modules/ext/benchmark.py` (comparison).
A Bloomberg value can be in the Excel file. Keep the file out of the repository.

### Ratios

| Metric | Bank figure (source) | ECB figure |
|---|---|---|
| CET1, Tier 1, and total capital ratio | capital divided by TREA, each quarter (KM1) | CBD2 I4008, I4002, I4001 |
| Leverage ratio | KM1 | SUP KSV13 (transitional) |
| LCR, NSFR | KM1 | CBD2 I3017, I3214 |
| NPL ratio | non-performing divided by gross loans and advances (CR1, sheet a) | CBD2 I3632 |
| Net interest income, interest income, interest expense, net fees, and operating income, each divided by assets | OR2 (3 years in each filing) | CBD2 I2410, I2411, I2412, I2430, I2400 |
| Net interest income and net fees as a share of operating income | OR2 | CBD2 I2510, I2530 |
| Return on equity and on assets | Bloomberg, last fiscal year | CBD2 I2003, I2004 |
| Cost-to-income, impairment of financial assets / assets, return on assets, return on equity (fiscal year 2024) | EBA Transparency Exercise: P&L of 31 Dec 2024, assets and equity at the end of the year | CBD2 I2100, I2006, I2004, I2003 |

### Columns of the result

- `bank`: the figure of the bank. `country`: the ECB figure for the domestic banks of the country. `euro_area`: the ECB figure of the euro area.
- `eu_median`: the median of the country figures of the EU (each country counts once). `eu_rank`: the share of the EU countries with a lower figure than the bank.
- A group column: the median of the countries of the group. `bank_less_country`: the difference of the bank and its country.

### Other tables

- Loans by counterparty. The bank figure comes from CR1 (central banks and credit institutions form one group). The ECB figure is the loan stock of all monetary financial institutions of the country to residents of the euro area (BSI).
  A second table leaves out the loans to credit institutions and central banks. The last row says how many countries stand behind each figure.
  When a BSI sector is missing for a country, the sector is derived from other sectors (for example general government = non-MFI less non-MFI without general government).
- Growth of the loans, year on year. The bank figure comes from CR1. The ECB figure is the growth of the loan stock of the country (BSI), at the same month. Two measures: all loans, and loans to non-banks.
- Rate sensitivity. The change of net interest income for a parallel shift of +200 and -200 basis points (IRRBB1) as a percent of net interest income (OR2), against the banks of P3DH with net interest income of 50 million euro or more.
  A peer counts with its latest filing of the 12 months up to the date of the bank. The table gives the median of the country, the euro area, all banks, and the groups, and the share of banks with a lower figure.

### Limits of the benchmark

- The bank is part of the country figure. The context lines of the report show the share of the domestic banks in the banking assets of the country and the concentration. Where the domestic banks are few or small, the country figure says little.
- The country figure of a small country can depend on one or two banks. A comparison with the EU median of country figures compares aggregates, not banks.
- The income ratios of the bank use the interest-earning assets of OR2 (row 1c). The ECB uses total assets. The ratios of the bank are a little high.
- Operating income of the bank is net interest income, dividends, net fees, other operating income, and the result of the trading book and the banking book (OR2). The ECB definition is close but not equal.
- The ECB data for CBD2 and SUP come about two quarters after the quarter. The newest quarters of the bank have no ECB figure.
- The ECB figures of the loan mix and of the loan growth cover the euro area members only. The loan stocks are not adjusted for reclassifications and exchange rates.
- Peers in the rate sensitivity table include subsidiaries and specialised banks. The peer screen of the M&A model does not apply here.

## Indicators of the curated pull

The list is in `modules/ext/specs.py`. The names tell the group:

- `mir_*`: rates (cost of borrowing of corporations and of house purchase, rate on consumer credit, rate on the outstanding book, rates on deposits). `newvol_hp`: new loans for house purchase.
- `bsi_*`: stocks of loans and deposits (EUR million). `growth_*`: annual growth rates of the ECB for the same stocks.
- `bls_std_*` and `bls_dem_*`: credit standards and demand for corporations, house purchase, and consumer credit.
- `cbd_*`: profit and loss and ratios of domestic banks (amounts in EUR thousand). `sup_*`: ratios of all supervised banks.
- `ssi_*`: one indicator for each structural indicator of the ECB.
- `estr_daily`, `euribor_3m`, `ecb_dfr`: market rates of the euro area.
- `es_*`: Eurostat.

## EBA Transparency Exercise

The EBA published the exercise TE2025 in December 2025. The reference dates are 30 Sep 2024, 31 Dec 2024, 31 Mar 2025, and 30 Jun 2025. The last data point is 30 Jun 2025.
The EBA says that the exercise is discontinued and that the Pillar 3 Data Hub (P3DH) replaces it. No later release is expected.
P3DH has more recent capital, liquidity, and exposure data (to 30 Jun 2026). The exercise adds what P3DH lacks: a full P&L, for the fiscal year 2024 and the first half of 2025.

| Table | Content |
|---|---|
| `te_oth` | Sheets Capital, Leverage, Assets, Liabilities, P&L, and RWA OV1. Amounts in EUR million. |
| `te_sov` | Sovereign exposures by country of the issuer and by maturity band. |
| `te_mrk` | Market risk: risk exposure amounts by product and approach. |
| `te_cre` | Credit risk by exposure class, by country, and by sector (NACE), non-performing and forborne exposures, collateral. About 650,000 rows. |

- Columns are those of the EBA files in lower case (`Row` is `row_no`, `Column` is `col_no`), plus `period_end` (last day of the quarter) and `vintage` (`TE2025`). The key of a line is its `label` (and `item`), `sheet`, and the dimension columns of the file.
- The P&L amounts are year to date. `n_quarters` says how many quarters the amount covers: 4 at 31 December, 2 at 30 June. A ratio must not mix periods with different `n_quarters`.
- The sample is 119 banks at the highest level of consolidation (108 with a P&L), 25 EU and EEA countries. The four banks of the M&A model are in it. A bank is identified by its LEI.
- The numbers tie to P3DH. For BIL at 31 Dec 2024 the exercise gives CET1 of 1,561.8 and risk exposure of 10,970.0, the same as KM1 of P3DH.
- The ratios agree with the ECB. For the fiscal year 2024, NBG and Alpha Bank are in the exercise. Their return on equity (13.7% and 7.9%), return on assets (1.54% and 0.90%), and cost-to-income ratio (37.0% and 38.7%) bracket the ECB figures for the domestic banks of Greece in CBD2 (11.7%, 1.21%, and 36.3%).
- The files are public EBA data. They are stored in `data/raw/eba_te/TE2025/` (not in git).

```
python scripts/pull_ext.py eba                  download the 4 files (about 230 MB) and load them
python scripts/pull_ext.py eba --flows oth,sov  chosen files only
```

## How to run

```
python scripts/pull_ext.py all                   every curated indicator (about 75 seconds)
python scripts/pull_ext.py all --only euribor_3m,ecb_dfr,eurostat --since 1999   a longer history of chosen indicators
python scripts/pull_ext.py bulk                  every series of MIR, BSI, BLS, CBD2, SUP, SSI with the full history (from 1999)
python scripts/pull_ext.py bulk --flows MIR,BSI --areas LU,DE --since 2010
python scripts/pull_ext.py status                what the database holds, for each data set
python scripts/test_ext.py                       tests (canned answers; the last test reads the real database)
```

An indicator or a country that fails does not stop the others. The run reports the failures and the exit code is 1.
The Euribor series must start before the first cycle (use `--since 1999`) for the cycles before 2010.
Refresh: the monthly series (MIR, BSI) appear about 5 weeks after the month. BLS appears in January, April, July, and October. CBD2 and SUP appear later. Run `bulk` each month.
The database grows by about 0.5 GB after the first bulk pull. Run `PRAGMA wal_checkpoint(TRUNCATE)` after a long pull to shrink the write-ahead log.

## Rules and limits

- Use the growth rates of the ECB (`growth_*`) for loans and deposits. The growth computed from the stocks (`v_country_growth`) is affected by reclassifications, sales of loans, and exchange rates.
  The stocks of countries outside the euro area are not comparable: Romania shows growth of more than 100% from a change of coverage.
- BLS and SUP exist for the members of the euro area only. CBD2, SSI, and Eurostat cover all 27 countries.
- MIR also holds the non-euro countries (CZ, DK, HU, PL, RO, SE), but their rates are in the local currency. The concept of a series ends with the currency, so a join on a euro concept leaves them out.
  The pass-through and the benchmark use euro concepts only, so they do not cover these 6 countries yet. A pass-through for them needs a local reference rate (the ECB set IRS holds money market rates in local currency).
- The source holds back some values for confidentiality. They are not stored. For small countries the significant banks are often blank in SUP. The BSI sectors differ between countries for the same reason.
- The ECB shows costs with a minus sign: the cost-to-income ratio and the interest expense ratio are negative in CBD2. The cost-to-income ratio is positive in SUP.
- Python cannot check the certificate of Eurostat in this setup. The loader runs `curl` (`modules/ext/http.py`) and keeps the certificate check on.
- The spread to Euribor is a simple measure. The loans of a bank can follow another reference rate.

## Checked and not loaded yet: the ECB list of supervised entities

The ECB publishes the list of supervised entities twice a year as an Excel file (`ssm.listofsupervisedentities<yyyymm>.en.xlsx`, page `bankingsupervision.europa.eu/banking/list/who`). No CSV file exists.

- Sheet SIs: the significant banks in groups (a numbered head, then its member entities with LEI, name, type, and country). Sheet LSIs: the less significant banks, by country, with LEI and type. About 2,900 entities.
- It matches 79% of the entities of the P3DH database by LEI. The four banks of the M&A model are significant groups.
- It gives the official status (significant or less significant), the group structure of the significant banks, and the size class. It has no flag for cooperative banks and no group structure for the less significant banks.
- For the peer screen it confirms every bank that the screen calls a subsidiary and is a member of a significant group. It disagrees where Bloomberg shows a parent that is not a bank group (a holding company, a foundation).
