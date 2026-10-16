# Bloomberg data in the P3DH database

The P3DH database (`data/processed/p3dh.sqlite`) holds Bloomberg data in tables with the prefix `bbg_`.
The data covers rates and curves, every P3DH bank (by LEI, with its tickers and ownership), the listed banks, and the outstanding bonds of 201 banks with their market prices.
The data stays in `data/processed`. It is not in git. Do not publish it.

## How to pull

Run the commands with the Python of the blauto project (it has `blpapi`). The Bloomberg terminal must run.

```
C:\Users\E40889\Documents\blauto\.venv\Scripts\python scripts/pull_bloomberg.py rates      # history of rates, curves, FX, indices (from 1999). Then averages and expected deposit rate
...  scripts/pull_bloomberg.py entities   # every P3DH entity: name, parent, tax rate, ratings, fundamentals, debt maturity profile, tickers
...  scripts/pull_bloomberg.py equity     # prices, valuation, fundamentals, consensus of the listed banks. Then the market basis
...  scripts/pull_bloomberg.py ownership  # 20 largest holders and holder types of the listed banks (state participation)
...  scripts/pull_bloomberg.py bonds      # bonds of the universe: census, then static and market data. Default: 7 banks. --all: every bank. --relist: find new issues
...  scripts/pull_bloomberg.py bondmarket # price, yields, and spreads of the outstanding bonds that are in the database
...  scripts/pull_bloomberg.py bondhist   # daily history of the quoted outstanding bonds (--start, default 20240101)
...  scripts/pull_bloomberg.py averages   # averages of the rates (no Bloomberg needed)
...  scripts/pull_bloomberg.py expected   # expected deposit rate from the OIS curve (no Bloomberg needed)
...  scripts/pull_bloomberg.py basis      # market basis and fiscal year of the consensus (no Bloomberg needed)
...  scripts/pull_bloomberg.py tickers    # ticker map of every bank (no Bloomberg needed)
...  scripts/pull_bloomberg.py status     # what is in the tables
```

`scripts/refresh_bloomberg.py daily | weekly | monthly` runs these steps in the right order (see Refresh). Run the single commands only for a test.
The `equity` pull needs the tickers of `entities`. A new `entities` pull keeps the market basis.
`bonds --all --census-only` lists the live bonds of every bank. It needs no unique security.

## Refresh

`scripts/refresh_bloomberg.py` refreshes the data by cadence. `scripts/refresh_bloomberg.bat <level>` calls it with the Python of the blauto project and writes `data/runs/bbg/refresh_<level>.log`.

| Level | Steps | New unique securities |
|---|---|---|
| daily | rates (with averages and expected deposit rate), equity prices, bond market, bond history, basis, tickers | none: the budget of the run is the number used so far |
| weekly | the daily steps, and fundamentals and consensus, ownership | none |
| monthly | rates, entities, equity prices, fundamentals and consensus, ownership, bonds (census of all banks again, then the new candidates of the universe, then market data), bond history, basis, tickers | yes: up to `--budget` (default 4,500) |

- A step that fails does not stop the next ones. The exit code is 0 (all ok), 1 (a step failed), 2 (a limit or the budget stopped a step), or 3 (the terminal is not reachable).
  Each run writes one line `refresh_<level>` to `bbg_pull_log`. `refresh_bloomberg.py status` shows the last run of each kind with its age.
- Run the daily refresh to keep the bond market table: every day adds one row for each bond. Bloomberg keeps the Z-spread and the asset-swap spread for about 60 days only, so the daily rows are the only longer history of these two.
- Run the monthly refresh on the 2nd of a month, after the count of unique securities of Bloomberg has started again. It takes 1 to 2 hours (the census is the long part).
- The Desktop API works only while the terminal runs on this PC and is logged in. Use the Windows Task Scheduler with the option to run a missed task as soon as possible. To register the tasks, run in a console:

```
schtasks /Create /TN "P3DH Bloomberg daily"   /TR "C:\Users\E40889\Documents\P3DHxTReX\scripts\refresh_bloomberg.bat daily"   /SC DAILY /ST 07:30 /F
schtasks /Create /TN "P3DH Bloomberg weekly"  /TR "C:\Users\E40889\Documents\P3DHxTReX\scripts\refresh_bloomberg.bat weekly"  /SC WEEKLY /D MON /ST 07:00 /F
schtasks /Create /TN "P3DH Bloomberg monthly" /TR "C:\Users\E40889\Documents\P3DHxTReX\scripts\refresh_bloomberg.bat monthly" /SC MONTHLY /D 2 /ST 06:30 /F
```

The tasks are not registered by the project. A weekly run replaces the daily run on Monday, so give them different times or start the weekly one first.
After a refresh of P3DH (`scripts/refresh_p3dh.py`), run `scripts/refresh_bloomberg.py monthly --only entities,basis,tickers` for the new entities.

## Limit of unique securities

Bloomberg limits the unique securities that a terminal can request in a month. The client counts them in `bbg_security_use`.
The default budget of the client is 4,500 for each month (`--budget`). It stops when a request would pass the budget, or when Bloomberg reports a limit.
The budget is a safety limit of this project. It is not the limit of your terminal. Type `DAPI<GO>` on the terminal to see the real limit.
A security that was requested before in the same month costs nothing again. New fields, new history, and new market data for known securities are free.
On 14 October 2026 the pulls had used 4,275 securities with a budget of 4,300.
The search service (the bond census) needs no unique security.

When the real limit is reached, Bloomberg answers every reference-data request with a response error: category `LIMIT`, code `-4002`, source `rsfrdsvc2`, and the text "Workflow review needed". The text has no limit word, so the client reads the category and raises `LimitReached`.
The pulls then stop with exit code 2. The count in `bbg_security_use` is not the whole use of the terminal: the project `blauto`, the Excel add-in, and other tools count too, so the real limit can come before the budget of the client.
The project `blauto` (`C:\Users\E40889\Documents\blauto`) uses the same API (blpapi, localhost:8194, the services refdata and instruments) and gets the same answer. Its function `ref_data` stops with an `InvalidArgumentException` instead of a readable message.
Type `DAPI<GO>` to see the use and the date of the reset. Do not retry before that date: every refused request is still a request.

## Tables

| Table | Content | Key |
|---|---|---|
| `bbg_rate_series`, `bbg_rate_daily` | 100 daily series from 1999: ECB policy rates, ESTR, Euribor, 17 ESTR OIS tenors, EUR swaps, government yields, credit indices, 19 FX rates, equity indices. | series, date |
| `bbg_rate_average` | Average of each series for each month (M), quarter (Q), half year (H), year (Y), year to date (YTD), and last 12 months (LTM). `complete` = 1 when the period is over. | series, type, period end |
| `bbg_expected_dfr` | Expected average deposit rate for each year, seen from each month end since 2020. For the last date also each half year and quarter. | as of, type, period end |
| `bbg_entity` | One row for each P3DH entity: Bloomberg name, country, parent and the relationship to it, tax rates, ratings, fundamentals of the last fiscal year (EUR million), net income of the last 12 months (`net_income_ltm`) and the part of it from continuing operations (`net_income_cont_ltm`, field `TRAIL_12M_CONT_INC`), number and amount of bonds, tickers, match method, market basis. | P3DH key |
| `bbg_ticker_map` | Tickers of each bank: `equity`, `proxy_equity`, `parent_equity`, `debt`, `cds`. `priced` = 1 when the stock has a price. | key, kind, ticker |
| `bbg_debt_maturity` | Debt that matures in each year (EUR million): bonds, and bonds with loans. | key, year |
| `bbg_equity_snapshot` | 27 fields for each listed ticker on the pull date: price, shares, book value, tangible book value, EPS, ratios, subgroup. | ticker, field, date |
| `bbg_equity_daily` | Daily price, market cap in EUR, shares, P/B since 2005 for 175 listed financials. | ticker, date |
| `bbg_fundamental` | Annual (A) and quarterly (Q) fundamentals since 2006, in EUR (net income, equity, assets, loans, deposits, opex, revenue, RWAs, ratios). | ticker, period end, type, field |
| `bbg_consensus` | Consensus (BEST) for the next 4 fiscal years: net income, EPS, DPS, revenue, operating profit, book value per share, ROE. | ticker, pull date, period, field |
| `bbg_holder` | The 20 largest holders of each listed ticker: name, type (Government, Sovereign Wealth Fund, Bank, Investment Advisor, ...), country, percent of shares, change, filing date. | ticker, date, rank |
| `bbg_ownership` | Share of each holder type (named holders, and all holders), the institutional share, and the free float. | ticker, date, kind, type |
| `bbg_bond_listing` | The live bonds that the census found for each bank, with a status: pending (empty), ok (in the universe), small (outstanding, not above EUR 150m), redeemed, ambiguous, unresolved. | key, security |
| `bbg_bond` | Static data of a bond (coupon, maturity, size, rank, Basel III designation, call, rating, series). | security |
| `bbg_bond_market` | Market data of a bond on the pull date: bid, ask, mid, yields (maturity, call, worst), I-spread, Z-spread, G-spread, benchmark spread, asset-swap spread, OAS, duration, quote date. | security, date |
| `bbg_bond_history` | Daily history of the quoted outstanding bonds: price, bid, ask, yield to maturity, yield to call, I-spread, Z-spread, asset-swap spread. | security, date |
| `bbg_pull_log` | Each pull: time, kind, detail, number of rows, status. | pull id |

Views: `v_bond_universe` (the bonds with an outstanding amount above EUR 150m or the equivalent), `v_bond_outstanding` (all outstanding bonds with the latest market data and the amount in EUR), `v_bank_ownership` (ownership and state status of each bank),
`v_bank_tickers` (the tickers of each P3DH bank), `v_dfr_average`, `v_dfr_p3dh` (for each P3DH reference date: the spot deposit rate and the averages of the quarter, half, year to date, and last 12 months),
`v_bank_market` (each P3DH entity with its Bloomberg data).

Units: amounts in `bbg_entity`, `bbg_fundamental`, and `bbg_debt_maturity` are EUR million. `bbg_equity_daily.mkt_cap_eur` is EUR. Shares are in million.
Rates, yields, and ownership shares are percent. Spreads are basis points. Prices of bonds are percent of par. Per-share values are in the currency of the stock.
The amount of a bond (`amt_outstanding`) is in the currency of the bond. `v_bond_outstanding.amt_outstanding_eur` converts it with the latest FX rate in `bbg_rate_daily`.
In `bbg_entity`, `net_income`, `revenue`, `operating_expenses`, and `common_equity` are values of the last fiscal year. `latest_period_end` is the latest interim period, not the fiscal year.

## The link to P3DH: the LEI, the rebuilt LEI, and the name

P3DH identifies a bank by its LEI. Bloomberg accepts `/lei/<LEI>` as an identifier. It gives data of the issuer, also for banks without listed shares.
Every row of `bbg_entity` has the P3DH key as its key. The columns `bbg_lei` and `match_method` say how the bank was found.

| Method | Rule | Banks |
|---|---|---|
| `lei` | The P3DH key is a LEI. | 674 |
| `lei_rebuilt` | The key is a country code and the first 18 characters of a LEI. The last 2 characters of a LEI are check digits (ISO 7064), so the full LEI can be rebuilt. | 2: Groupe BPCE (9695005MSX1OYEMGDF46 is BPCE SA), Groupe Credit Agricole (969500TJ5KRTCJQWXH05 is Credit Agricole SA) |
| `name` | The key is a national bank code. The name finds a live bond or the equity record of the bank. That gives the LEI. | 1: Volksbank Wien (AT0000000000043000VB) |

A national code can look like a country code and a LEI start. Then the rebuilt LEI does not exist in Bloomberg, and the match falls back to the name. The name search drops a short code at the end of the name.
All 677 keys are found.

## Tickers

`bbg_ticker_map` lists the tickers of each bank.
- `equity`: the equity ticker of the bank. A placeholder such as `3358410Z FP` (BPCE SA) means that the company is private. `priced` is then 0.
- `proxy_equity`: the listed ticker of an issuer that is not the same legal entity as the P3DH group. Groupe Credit Agricole has `ACA FP` (Credit Agricole SA).
- `parent_equity`: the equity ticker of the ultimate parent. The note gives the industry subgroup.
- `debt`: the ticker of the bonds, from the group structure of Bloomberg and from the bond listing. 485 of 677 banks have one. Groupe BPCE has `BPCEGP`.
- `cds`: the ticker of the credit default swap. 65 banks have one.

409 banks have no ticker with a price. They are private, co-operative, or subsidiaries of a parent that is not listed. Natixis (`KN FP`) no longer has a price.

## Market basis

Each bank gets a market basis. It tells the M&A model where the market cap comes from.

| Basis | Rule | Banks (14 October 2026) |
|---|---|---|
| `self` | The bank has its own listed shares with a price. | 129 |
| `parent` | The ultimate parent is listed and its industry subgroup contains "Bank". | 95 |
| `proxy` | A group that was matched to a listed issuer that is not the same legal entity (Groupe Credit Agricole). | 1 |
| `none` | All other banks. | 452 |

The M&A model uses a market cap only for basis `self`. A parent share price is not the value of a subsidiary.
A conglomerate (for example Legend Holdings for BIL) or a car maker (BMW, Ford) is not a bank. Such a parent does not give a basis.
The consensus has a fiscal year for each period: the last annual report plus 1 to 4 years.
The readers of the snapshot table use the latest value of each field. A newer partial snapshot does not hide the price.

## Ownership and state participation

Bloomberg gives the 20 largest holders of a listed stock with their type. The type `Government` is the state.
The pull covers 185 listed tickers. The securities were requested for the equity data, so the pull costs no new unique security.
`v_bank_ownership` has, for each bank:
- `state_pct_named`: the sum of the holders of type Government among the 20 largest holders. `state_pct_all`: the share of type Government among all holders (a larger number, because it counts small holders).
- `swf_pct_named`: the share of Sovereign Wealth Funds. `largest_holder`, `largest_type`, `largest_pct`, `free_float_pct`, `institutional_pct`.
- `via_parent` = 1 when the bank has no own listed shares. The numbers are those of the listed parent.
- `state_status`: `owned by a government` (the relationship is `Govt Owned Entity`, or the ultimate parent is a state), `state majority` (50% or more), `state participation` (a Government holder in the top 20), or `none reported`.

Result on 14 October 2026 (677 banks): 33 owned by a government, 43 with state participation (21 of them with own listed shares, and 4 listed banks that a government owns), 601 none reported.
The view lists the state holders by name and share. NBG shows the Hellenic Republic as a holder of type Government.

Limits:
- Bloomberg has no list of shareholders for a bank that is not listed. For these banks the database has the ultimate parent and the relationship (`bbg_entity.parent_name`, `parent_relationship`).
  BIL is an example: Bloomberg shows only Legend Holdings. The 10% of the State of Luxembourg is not in Bloomberg.
- A state can hold through a holding vehicle (HFSF for Greece, NLFI for the Netherlands, SFPI for Belgium). Bloomberg names the vehicle or the state. Only the type tells that it is a state.
- A holder filing can be older than the pull date. `bbg_holder.filing_date` has it.

## Deposit rate

Bloomberg dates an ECB decision on the day of the meeting. The ECB applies the rate on the first Wednesday after the meeting.
The database holds the series with the day of the decision (`ECB_DFR_ANN`) and the derived series with the day the rate applies (`ECB_DFR`).
The averages and the expected rates use `ECB_DFR`.

The expected deposit rate of a period comes from the ESTR OIS curve:
1. Discount factors come from the par rates (up to 1 year a single payment, act/360; after 1 year an annual fixed leg; log-linear interpolation).
2. The forward ESTR of the period plus the spread of the deposit rate to ESTR on the pull date gives the expected average.
3. The days up to the pull date use the realised rate.

## Bonds

The search service of Bloomberg lists bonds as text, for example `ETEGA 5<7/8> 06/28/2035 REGS<corp>`. It costs no unique security.
Static data and market data cost one unique security for each bond.

How the census works (`bonds --all --census-only`):
1. The Bloomberg name of the bank gives the issuer tickers. Codes of loan facilities (`BL...`, `BF...`) are not tickers. Two P3DH entities with one Bloomberg issuer are listed once.
2. A search for the ticker returns a part of the bonds. A sweep over the years in which the bank has debt that matures (`bbg_debt_maturity`) and over `FRN` and `0` adds the rest.
   A search finds a perpetual (AT1 and old Tier 1) only when the query holds a coupon. `<ticker> PERP` returns nothing. So a sweep over `<ticker> 0 PERP` to `<ticker> 14 PERP` adds the perpetuals (`PERPETUAL_COUPONS`).
   Each query returns the perpetuals with a coupon from n to n + 0.99, so a sweep in steps of 1 is complete.
3. A bond stays if the issuer name matches the bank, the maturity in its name is not in the past, and it is not a CDS contract or a loan.
   The issuer name must match with 75% of the words, counted against all words of both names. Deutsche Bank Luxembourg is not Deutsche Bank AG.
4. A request converts a fraction coupon to a decimal (`5<7/8>` becomes `5.875`). Bloomberg does not accept the fraction.

The field `SERIES` (column `series` of `bbg_bond`) names the programme of a bond, for example `EMTN`, `GMTN`, or `DMTN`. The spelling differs (`EMTN`, `Emtn`, `emtn`), so compare in upper case.
A bond that is not issued under a programme has an empty series. Private structured notes of a bank (zero-coupon and index-linked notes) also have an empty series or a number.
A perpetual AT1 has an empty series: filter the EMTN series for senior and Tier 2 bonds, and add the perpetuals.

The name of a bond shows the maturity but not an early redemption. A called bond has an amount outstanding of 0. 389 of the 1,745 bonds in the last pull were no longer outstanding (status `redeemed`).
`v_bond_outstanding` shows only bonds with an amount above 0 and a maturity in the future (or a perpetual).

Market data (`bbg_bond_market`): bid, ask, mid, yield to maturity, yield to call, yield to worst, I-spread, Z-spread, G-spread (`G_SPREAD_MID_CALC`, to the interpolated government curve),
benchmark spread (`YAS_YLD_SPREAD`, to the benchmark bond `bench_bond` with yield `bench_yield`), asset-swap spread, OAS, duration, convexity, and the quote date.
The I-spread is `I_SPRD_MID`, or `YAS_ISPREAD` when the first is empty. Yield to worst is the Bloomberg value, or the lower of yield to maturity and yield to call.
A bond without a quote has empty market columns. A bond near its maturity or a zero-coupon note can show a negative spread or a large yield. These are the Bloomberg values (fewer than 1% of the quoted bonds).
History (`bbg_bond_history`): Bloomberg keeps the price, the yields, and the I-spread for the whole period. It keeps the Z-spread and the asset-swap spread for about 60 days only.

The universe is the bonds with an outstanding amount above EUR 150m or the equivalent in another currency (`UNIVERSE_MIN_EUR` in `modules/bbg/schema.py`, view `v_bond_universe`). A bond outstanding below the limit gets the status `small`.
Market data and history are pulled for the universe only. The size of a bond is known only after the bond is requested, and a request costs one unique security. So the pull orders the bonds that are not in the database with signals that cost nothing:
- An issuer whose average bond (debt of the issuer / number of issues) is below EUR 50m is skipped: 1% of its bonds are in the universe, against 37% to 61% for the others. An issuer with total debt below the limit is skipped too.
- A Reg S bond with a coupon is in the universe in 74% of the cases. A zero-coupon note, or a bond without Reg S, in 11% to 14%.
- Order: banks in focus, then Reg S bonds with a coupon of issuers that average EUR 100m or more, then other Reg S bonds with a coupon, then the rest of the large issuers, then the rest.
On 14 October 2026 this left 38,451 of the 49,825 pending bonds to request.

Coverage on 14 October 2026:
- Census: 421 issuers with 69,315 live bonds in the names. 82 banks have no live bond.
- Universe (outstanding above EUR 150m): 710 bonds of 111 banks. 697 of them have a quote. The bonds below the limit stay in `bbg_bond` (1,428 bonds).
- Resolved before the universe rule: 2,141 outstanding bonds of 201 banks. 1,415 of them have a quote.
  Capital instruments among them: 195 Tier 2 and 13 Additional Tier 1.
- Complete banks: 227 of 346 banks with listed bonds. The pull stopped at the budget before the 117 banks that have the most bonds.
  The largest left are Landesbank Baden-Wurttemberg (4,618 bonds), Deutsche Bank (3,940), DZ Bank (3,607), Societe Generale (3,512), UniCredit Bank GmbH (3,429), LB Hessen-Thuringen (3,109), and BNP Paribas (1,992).
  49,825 bonds are pending. Run `bonds --all` in a later month to continue. It starts with the smallest issuers that are left.
- Focus banks (outstanding bonds, of which with a quote): NBG 11 (11), Eurobank 35 (31), Alpha Bank 13 (13), Piraeus 15 (15), Bank of Cyprus 1 (1), BIL 628 (110), HCOB 82 (81).

Limits:
- A name with "(Multiple Matches)" stands for several bonds. Bloomberg cannot resolve it by name. The status is `ambiguous`. There are 12,241 such names, mostly zero-coupon structured notes (BIL: 351).
  The search service gives no identifier for them.
- A bond that Bloomberg cannot find has the status `unresolved` (196 bonds, mostly zero-coupon notes of BIL and NOBA).
- A search returns at most 1,000 results. A sweep covers the gap, but a bank with thousands of notes is not complete.
- The perpetual sweep was added on 14 October 2026. The 7 focus banks have their perpetuals. The other banks get them at their next relist (the monthly run, `--relist`), so the count of AT1 bonds of the other banks is low until then.
- The count of issues in `bbg_entity` (`DDIS`) is the count of the ultimate parent and includes loans. BNP Paribas Fortis, BGL, and BNL show the 11,489 issues of BNP Paribas.
- Bank of Cyprus Holdings shows 1 outstanding bond. The operating bank issues under another legal entity.
- The amounts of the bonds in other currencies are converted at the latest FX rate. The Austrian schilling uses its fixed rate.

## Issuance workbook

`scripts/build_issuance_excel.py` writes `docs/Issuance NBG and BIL.xlsx` (not in git: it holds Bloomberg data). It reads `bbg_bond`, `bbg_bond_market`, `bbg_bond_listing`, and the FX series. The code is in `modules/bbg/issuance.py` (data) and `modules/bbg/issuance_xlsx.py` (workbook).
Use `--banks SHORT=LEI ...` for other issuers.

- Sheet `Profile`: for each issuer and for all issuers combined, the amount outstanding in EUR by debt type and by maturity year (ten single years, one open bucket, and perpetual), the number of notes, and a table of public and private amounts.
  Cell B4 chooses the contractual maturity or the next call date. The cells are SUMIFS and COUNTIFS formulas over the sheet `Issues`, so a change of a class in `Issues` changes the profile.
- Sheet `Issues`: one row for each bond, active or not, with the fields of the database, the amount in EUR, and the latest quote.
- Sheet `Listed without data`: live names of the census that have no row in `bbg_bond` (ambiguous, not found, or listed after the last pull), with the coupon and the maturity read from the name.
- Debt type: AT1, Tier 2, senior non-preferred, senior preferred, covered bond, senior unsecured programme notes, and structured and private notes. The rules are in `debt_type` and in the Read me sheet. Bloomberg has no field for a structured note: the class is a rule on the rank, the coupon type, the maturity type, and the programme.
- Public or private: a note with the series EMTN, GMTN, or DMTN is public. A note outside a programme is public from EUR 150m (`UNIVERSE_MIN_EUR`). All others are private.
- The notes that are listed without data are not in the amounts. Load them with `pull_bloomberg.py bonds --leis <LEI>`. This needs the terminal and unique securities of the monthly budget.
- The tests (`scripts/test_bbg.py`, section 3e) use invented bonds. They check the rules, and every Profile cell against pandas with the library `formulas` (install it to run that part).

## MREL templates against the bonds

`scripts/mrel_vs_bonds.py --lei <LEI>` compares KM2 and TLAC1 of P3DH with the bonds of the database: AT1, Tier 2 (with the amortised part that TLAC1 counts as a liability), senior non-preferred, and the non-subordinated eligible liabilities.
It takes the bonds that were outstanding on the TLAC1 date with a residual maturity of at least 1 year. Result for BIL (TLAC1 of 31 December 2025, EUR million):

| Item | P3DH (EUR m) | Bloomberg bonds |
|---|---|---|
| AT1 (TLAC1 row 2) | 300.0 | ties exactly: one perpetual (series empty, Basel III designation Additional Tier 1) |
| Tier 2 plus the amortised part (rows 6 + EU-12c) | 436.6 | ties within 1% |
| Senior non-preferred (rows 12 + EU-12b) | 398.2 | ties within 4% |
| Non-subordinated eligible liabilities (row 14) | 2,550.3 | does not tie: the senior preferred bonds of the EMTN series give less than one third of the P3DH value |

- AT1, Tier 2, and senior non-preferred tie. TLAC1 itself adds up: row 17a (462.0) = rows 12 + EU-12b + EU-12c, and row 14 (2,550.3) = rows 13 + EU-13a.
- The AT1 was missing from the first census, because a search finds a perpetual only with a coupon in the query (see the census above).
- The non-subordinated layer does not tie. All senior preferred bonds of BIL with a residual maturity of at least 1 year are in the EMTN series, so the series filter does not change the total.
  The rest of the layer is not in the EMTN series. Bloomberg labels most other BIL notes `Sr Unsecured` with an empty series (zero-coupon and index-linked notes). Bloomberg gives no flag for structured notes or for the contractual conditions of MREL.
  BIL publishes TLAC3a (creditor ranking by residual maturity) in its own Pillar 3 report, not in P3DH. The rank of this layer holds debt instruments and eligible deposits.
  Beyond 5 years of residual maturity, the layer ties to the EMTN bonds of the database. The gap is in the buckets of 1 to 2 years and 2 to 5 years, and the part of 1 to 2 years is too large for the notes of the database.
  So the gap is probably not bonds (for example term deposits, registered notes, or loans). Ask BIL treasury for the list of eligible liabilities.
- 351 BIL names are `ambiguous` and 35 `unresolved`. The tool cannot see them.
- BIL files no TLAC3 (creditor ranking), which would split the liabilities by rank and maturity.
- NBG ties on AT1 and on Tier 2 (within 3%). Its non-subordinated value is within 9% of its senior preferred bonds. For Eurobank and Bank of Cyprus the bonds sit in another legal entity (the holding company), so the totals do not tie.

## Tests

`scripts/test_bbg.py` tests the curve maths, the effective dates of the policy rates, the averages, the bond names and the issuer match, the market data rules, the history, the rebuilt LEI and the name match,
the market basis, the ticker map, the ownership and the state status, the bond universe, the refresh plan, and the reader of the M&A workbook.
It also checks the coverage of the database (all keys found, every entity has a basis, consensus has a fiscal year, BIL and HCOB have the data that the M&A model needs, plausible bond data).
The tests need no Bloomberg terminal.
