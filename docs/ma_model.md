# M&A model

The M&A model combines NBG with up to three target banks. It exists in two forms that use the same formulas:

- The Excel file `docs/M&A calc v2.xlsx` (sheets Calc and Merger). The file is not in git. It holds Bloomberg data.
- The Streamlit page `M&A scenario` (`dashboard/pages/7_MA_scenario.py`).

The page does not copy the formulas. It reads them from the workbook and runs them with a small evaluator (`dashboard/ma_sheet.py`).
So each number on the page is a cell of the Excel file.

## Files

| File | Purpose |
|---|---|
| `dashboard/ma_workbook.py` | Writes the sheets and the formulas. Holds the review log, the table of typed numbers, the layout of the page, and the defaults. |
| `dashboard/ma_sheet.py` | Evaluator for Excel formulas (SUM, AVERAGE, MAX, MIN, IF, IFERROR, CHOOSE, COUNT, MEDIAN, SLOPE, INTERCEPT, RSQ, ABS, AND, OR, NOT, ROUND, TEXT). |
| `dashboard/ma_data.py` | Reads the P3DH clean layer (KM1, OV1, CC1, CC2, KM2, LR1, IRRBB1, AE1, CR1) for one bank and one quarter. |
| `dashboard/ma_market.py` | Reads the Bloomberg tables of the database (`bbg_*`) for the four banks, the nearest peers, and the deposit rates. Links to P3DH by the LEI. |
| `scripts/build_ma_workbook.py` | Builds the Excel file. You can choose three other targets. |
| `scripts/pull_bloomberg.py` | Pulls Bloomberg data into the database. See `docs/bloomberg_db.md`. |
| `scripts/test_ma_workbook.py` | Tests of the evaluator, the workbook, the identities, the data policy, and the page. |
| `scripts/test_bbg.py` | Tests of the Bloomberg modules (curve maths, rates, bond names, market basis, coverage). |

## Sheets of the Excel file

- **Calc**: the calculation for one year. Cell N15 chooses the year (1 = 2026E to 4 = 2029E, default 2027E). Rows 1 to 58 keep the cells of your original sheet. Rows from 59 are new.
- **Merger**: the four-year model (2026E to 2029E) for each of the three deals. It follows Figure 89, the picture in your original sheet.
- **P3DH**: the data of the EBA Pillar 3 Data Hub, with the period and the quality of each value.
- **Market**: Bloomberg data from the database, one column for each bank (NBG and the three targets): price, shares, market cap, profit, consensus, opex, tax rate. It also holds the ESTR OIS curve and the average deposit rate for each year, half year, and quarter. Do not publish this sheet.
- **Peers**: the listed European banks of P3DH with P/TBV, P/CET1, and returns. For each target without a market cap it picks the k banks with the closest return and takes the median multiple. Do not publish this sheet.
- **Review**: each finding about the original sheet, the effect of the corrections, and a table of every typed number of the original.
- **Guide**: how to use the file.
- **Original (user)**: your sheet, unchanged, with its picture.

Colours: blue on yellow is an input. Green font is a link to P3DH or Market. Black is a formula. A green fill in column C marks a new row.

## Data sources

| Item | Source |
|---|---|
| Size, RWAs, CET1, AT1, Tier 2 | KM1 and CC2 or LR1 (P3DH). AT1 = Tier 1 less CET1. Tier 2 = total capital less Tier 1. |
| MREL-eligible liabilities | KM2 own funds and eligible liabilities less total capital. KM2 and TLAC1 count items after deductions, so the amount is MREL-eligible. |
| Senior non-preferred and senior preferred | KM2: own funds and subordinated liabilities (row 1a) gives the subordinated part. The rest is non-subordinated (senior preferred). |
| Deferred tax assets | CC2 (balance sheet line "Deferred tax assets", and "of which: do not rely on future profitability" = DTCs). CC1 rows 10, 21 and 75 for the deduction and the amount below the threshold. |
| Tangible equity | CC1 row 6 (common equity before adjustments) less row 8 (intangible assets). |
| P2R, buffers, leverage, liquidity | KM1 (P3DH). |
| MREL requirement | KM2 (P3DH). |
| IRRBB, encumbrance, non-performing loans | IRRBB1, AE1, CR1 (P3DH). |
| Price, shares, market cap | Bloomberg, by LEI. Only for a bank with its own listed shares (market basis `self`). |
| Profit | Consensus of the year (Bloomberg BEST). Without consensus: income from continuing operations of the last 12 months (Bloomberg `TRAIL_12M_CONT_INC`). P3DH has no income statement. |
| Revenue, EPS, DPS | Consensus (Bloomberg BEST) for NBG and for targets that have it. |
| Opex and tax rate | Bloomberg: operating expenses of the last fiscal year, statutory tax rate (the effective rate if the statutory rate is missing). |
| Valuation | Market cap (Bloomberg) for a listed bank. For a bank without listed shares: the median multiple of the nearest listed peers times its equity in P3DH (see below). |
| Expected deposit rate | Bloomberg: the realised ECB deposit rate and the ESTR OIS curve (see below). |
| Cash share, stake, premium | Your levers. They are the only deal inputs that have no data source. |
| Deposit data | Not available in P3DH. The model has no deposits row. |

BIL and HCOB use only P3DH and Bloomberg. Row 152 of Calc checks that every bank has a profit, an opex, a tax rate, and a valuation.
A test checks that no typed number is in these rows.

## Expected deposit rate

The profit of a deal depends on the rate that the cash earns. The model uses the average expected ECB deposit rate of each calendar year.

1. The model bootstraps discount factors from the ESTR OIS swap rates (1 week to 10 years).
2. The forward ESTR of a period is the average over that period. The model adds the spread of the deposit rate to ESTR on the pull date (6.1 bp).
3. A period that is over has its realised average. A period that has not ended has the realised rate to the pull date, then the forward rate.
4. The ECB applies a new rate on the first Wednesday after the meeting. The database holds both series: the day of the decision and the day the rate applies.
   The model uses the second one (2.00% to 16 June 2026, 2.25% to 15 September, 2.50% since).

Calc uses the year in N15. Merger uses the average of each year.
Sheet Market also lists the average for each half year and each quarter (2025 to 2028). The database has them for every month, quarter, half, year, YTD and LTM since 1999 (view `v_dfr_average`).
The view `v_dfr_p3dh` gives, for each P3DH reference date, the spot rate and the averages of the quarter, half, year to date, and the last 12 months.

## Calc: formulas

Notation: `D` is NBG. `E`, `F`, `G` are the targets. `H`, `I`, `J` are the combinations. `K` is NBG at the CET1 target. `k` is the stake.

**Price.** Price for the stake = `k x valuation x (1 + premium)` (row 38). Cash paid = cash share x price (row 74).
New shares = share paid in shares x price / NBG share price (row 48).

**CET1** (row 20). `CET1(NBG) + CET1(target) - cash paid + minority interest counted - minority interest removed - k x fair value write-down - transaction cost + new CET1`.
Equity paid in shares does not change this sum. Each euro of cash reduces CET1 by one euro.

**Goodwill** (rows 80 to 82). The purchase accounting writes off the intangible assets of the target and books new goodwill:
`price - k x (tangible equity - fair value write-down)`. A negative result is a gain from a bargain purchase.
A price of exactly 1.0 times tangible equity gives no goodwill and no gain.

**Minority interest** (rows 84 and 85). Removed: `(1 - k) x tangible equity`. Counted: `(1 - k) x min(CET1 of the target, CET1 requirement x RWAs)`.

**Profit** (rows 9 to 12). The profit of the year in N15: consensus, else net income of the last 12 months. `Profit(NBG) + k x profit(target) - after-tax deposit income on cash paid - after-tax integration cost`.
Integration cost = integration % x opex of the target / years x (1 - tax rate).

**ROCET1** (row 13). Profit, less the after-tax deposit income on CET1 above the target, divided by the target CET1 ratio times RWAs.
The combinations use RWAs attributable to NBG holders (row 88: NBG + k x target).

**Cash paid, equity, and market cap.** Cash paid leaves the group. It reduces CET1 and tangible equity one for one. Only new shares add equity.
Market cap is the value of the business plus the excess CET1 above the target. The market values excess CET1 at N6 (default 1.0, book value).
Cash paid out of excess CET1 therefore reduces market cap by the cash. The two methods (rows 31 to 33) use this rule:
- P/E method: `P/E x (profit without the integration cost and without income on excess CET1) + N6 x excess CET1`. The default P/E (N3) is the P/E of NBG on the same basis, so a deal that changes nothing gives no upside.
- P/TBV method: the P/TBV at the CET1 target of both banks (market cap without excess CET1 over tangible equity at the CET1 target), weighted by tangible equity at the CET1 target,
  applied to the tangible equity at the CET1 target of the combination (row 45), plus `N6 x excess CET1`.
- Set N6 to 0 to see the method of the original sheet. Then excess CET1 has no value, and a cash deal looks almost free.

**Valuation of a bank without a market cap** (rows 32, 60, 129, and 160 to 167). The market cap of a listed bank is its Bloomberg market cap in EUR.
A bank without listed shares (BIL, HCOB) is valued with its nearest listed peers (sheet Peers). The peers are the listed European banks of P3DH, without subsidiaries, cooperatives, and specialists.
- A subsidiary is a bank that Bloomberg gives a parent in a group (field `COMPANY_TO_PARENT_RELATIONSHIP`: Subsidiary, Synthetic Parent, Related Entities). A parent that is a state, or a foundation that holds depositary receipts (ABN AMRO), does not count.
- A cooperative has the Bloomberg subgroup Cooperative Banks, or a cooperative legal form or name (for example SCpA, Popolare, Caisse Regionale, Credit Agricole, Coop).
- A specialist has a Bloomberg subgroup of leasing, commercial finance, brokerage, investment management, mortgage, or special purpose banks. Banca Sistema (factoring) is a named exception, because Bloomberg calls it a commercial bank.
- The function is `peer_exclusion` in `dashboard/ma_market.py`. Sheet Peers lists the banks that it leaves out, with the reason.
- The value of BIL depends on the peers. Each screen moved it by 10% or more. Check the result against the Gordon model below, and look at both bases (rows 165 and 166).
- On tangible equity: the median P/TBV of the k banks whose return on tangible equity is closest to the return of the target, times the tangible equity of the target (CC1).
- On CET1: the median P/CET1 (market cap in EUR / CET1 of P3DH) of the k banks whose return on CET1 is closest, times the CET1 of the target (KM1).
- N17 sets k (default 20). N18 sets the basis: 1 tangible equity, 2 CET1, 3 the average of both (default).
- The return of the target is its profit of the year divided by the equity. The peers use the profit of the last 12 months (EPS x shares).
- **Cost of equity of the target** (levers N23 to N25, rows 224 to 231). The peers do not show a size premium, but a smaller and unlisted bank such as BIL has a higher cost of equity than its peers. This is a judgment, so it is an input.
  Gordon model: P/TBV = (return - g) / (cost of equity - g). The cost of equity that a peer implies is g + (return - g) / multiple, with g in N23 (default 2%). Sheet Peers shows the median of the near peers (rows 7, columns X and following).
  The peer value on each basis is scaled by (cost of equity of the peers - g) / (cost of equity of the target - g). N24 is the cost of equity of the first target (BIL, default 10%). N25 is the same for the third target (HCOB, default 0).
  0 means no adjustment: the value is the plain median multiple. A target at or below g gets no adjustment. Bank of Cyprus is listed and has no adjustment. Row 231 shows the effect, and row 230 the value without it.
A CET1 basis is needed because CET1 is below tangible equity by the other CET1 deductions. For BIL they are EUR 0.45bn (CET1 1.65bn, tangible equity 2.09bn). For HCOB they are EUR 1.6bn.
Peers are valued on tangible book, which does not show these deductions. The CET1 basis can give a lower or a higher value than the tangible equity basis, depending on the peers. Rows 165 and 166 of Calc show both.
A linear fit of P/TBV on RoTE is shown on sheet Peers for information. It is not used: a few banks with a high return and a high multiple raise the line.
For BIL it gives a clearly higher value than the nearest peers. A Gordon model (P/TBV = (return - growth) / (cost of equity - growth)) with a growth of 2% is a third check.
Do not fix the cost of equity at 10%. A fixed 10% is above the cost of equity that the peers imply, and the Gordon value of the peers then lies below their market P/TBV.
Use the cost of equity that the peers imply: the median of (growth + (RoTE - growth) / P/TBV) of the peers. The Bloomberg analyst target prices give a second estimate: the same formula with the target P/TBV and the consensus RoTE.
Analysts expect the return to rise (consensus EPS of the current year is above the EPS of the last 12 months), so the Gordon value on the consensus RoTE fits the market better than the value on the trailing RoTE.
BIL has no analyst coverage: its Gordon value uses the trailing RoTE. Only peers with a consensus and a target price (mostly the large banks) are in the analyst estimate.
A bank with a parent that is a bank group gets no value from the parent share price. A parent that is a conglomerate or a car maker says nothing about the bank.
The result is a rule of thumb. It does not include control premium, quality of assets, or country risk. Use the premium (row 37) to change the price.

**Stake in BIL.** The stake is 90% because the State of Luxembourg holds 10% and does not sell. Price = stake x valuation x (1 + premium).
A premium of -10% on top of a stake of 90% would count the 10% twice, so the default premium is 0%.

**NBG at the CET1 target** (column K). NBG pays out its excess CET1. Market cap falls by the same amount. Profit falls by the after-tax deposit income.
The price effect is 0%. The method of the original sheet shows a gain of 13% that has no cause.

**Shares and EPS** (rows 48 to 53). The EPS at the CET1 target removes the excess CET1 from profit (after-tax deposit income) and from the share count (at the NBG price).

**Deferred tax assets** (rows 41 to 43). Total DTAs and DTCs come from CC2. The DTCs do not rely on future profitability. They are not deducted from CET1.
The remaining DTAs (about 0.40bn for NBG) are below the deduction threshold (CC1 row 75, 250% risk weight) and are in CET1 already.
The lever in rows 28 and 29 adds them to CET1 a second time. It is off by default (N16 = 0).

**Regulatory view** (rows 90 to 128).
- P2R and the countercyclical and systemic risk buffers are weighted by RWAs. The G-SII or O-SII buffer is the higher of the two.
- CET1 requirement = 4.5% + P2R (CET1 part) + combined buffer. Tier 1 uses 6%. Total capital uses 8%.
- Distance to MDA = the smallest headroom of the three layers, in basis points of RWAs. Row 107 names the binding layer.
- Leverage exposure = both exposures + change of cash. Leverage ratio = Tier 1 / exposure.
- LCR = (HQLA of both banks + change of cash) / net outflows of both banks.
- NSFR: ASF of both banks + new instruments + shares issued - k x common equity of the target; RSF is the sum of both.
- MREL requirement = RWA-weighted mix of the KM2 requirements, plus the combined buffer.
- AT1, Tier 2, and senior surplus (rows 122 to 124) use the requirement stack of CRR Article 104a (P2R: 56.25% CET1, 18.75% AT1, 25% Tier 2).

**Issuance needs and requirements weighted by RWAs** (rows 169 to 201, tab Issuance needs).
- The requirement of the combination is the average of the requirements of the two banks, weighted by their RWAs (the RWAs of NBG and of the target after the RWA change, as in row 8). This applies to the CET1, Tier 1, and total capital requirement (P2R and combined buffer),
  to the MREL requirement with the combined buffer, and to the subordination requirement. Rows 91 to 102 weight the P2R and buffers too, but they take the higher of the two systemic buffers (row 97). The weighted average of rows 173 to 177 is the simple version.
- A need is the amount to issue. It follows a waterfall: CET1 first, then Tier 1 (AT1), then Tier 2, then eligible liabilities. An instrument that is issued for one layer also counts for the next layers.
  At the requirements the need is the shortfall against requirement x RWAs (rows 187 to 192). At the targets it is the shortfall against the CET1 target D1 and the MREL target D2 (rows 193 to 195).
- CET1 of the combination (row 20) already carries the goodwill. A cash payment reduces CET1 one for one. A share payment leaves it unchanged, because the new goodwill is deducted against the new equity. Rows 199 to 201 show the goodwill, its effect in basis points of RWAs, and the CET1 change compared with NBG alone.
- The AT1, Tier 2, and eligible liabilities of the target stay outstanding and count in the group stack (rows 22 to 24 and 154 and 155). N19 sets the share that counts (default 100%).
  Rows 196 to 198 show the need at the MREL target if none of them counted, and the mitigation. A caution: the instruments of a subsidiary count at group level in part (CRR Articles 83 to 88),
  and as external MREL only if the subsidiary is a resolution entity. Otherwise they are internal MREL. Test this with N19.

**Buckets for AT1 and Tier 2** (rows 203 to 222). CRR Article 104a lets a bank meet the P2R with at most 18.75% AT1 and 25% Tier 2 (56.25% must be CET1). The largest AT1 bucket is the Pillar 1 AT1 (1.5%) plus 18.75% of the P2R.
The largest Tier 2 bucket is 2% plus 25% of the P2R. The P2R is the P2R weighted by RWAs (row 92). Rows 212 and 213 give the room that is left in each bucket, and rows 214 and 215 the instruments above the buckets (they count for the MREL, not for the capital requirement).
Rows 216 to 222 give the mix to issue, cheapest first: AT1 and Tier 2 within the buckets, the rest of a capital need as CET1, senior non-preferred for the subordination need, and senior preferred for the rest of the MREL need.

**Subordination requirement** (rows 177, 182, and 191, levers N20 to N22). P3DH shows it: KM2 rows EU-8 and EU-10 give the part of the MREL requirement to be met with own funds or subordinated liabilities, as % of TREA and of TEM.
- 156 of 200 banks fill EU-8. 111 file a value above 0. All 22 banks of EUR 250bn and more, and 16 of 19 banks of EUR 100bn to 250bn that file KM2, report one.
  Median of the filed values: 19.1% (above EUR 250bn) and 15.9% (EUR 100bn to 250bn) of TREA. 13.50% is the most frequent value of the banks of EUR 100bn to 250bn (AIB, Bank of Ireland, Belfius, BNP Paribas, Erste, Rabobank). It is probably the rule for banks above EUR 100bn.
  I could not check the legal text here. Check it with the resolution authority. Filed values on the exposure measure (EU-10) are 5.0% to 8.2%.
- NBG files 0% in EU-8. BIL, Eurobank, Piraeus, and Bank of Cyprus leave it empty.
- The model uses the filed values (weighted by RWAs) when a bank files one. When none is filed and the combination has assets of N21 or more (default EUR 100bn), it uses N20 (default 13.5% of TREA) plus the combined buffer.
  The requirement in EUR is not below N22 (default 5%) of the leverage exposure. NBG and BIL together have assets of EUR 113bn, so the assumption applies. Set N20 to 0 to remove it.

**MREL detail** (rows 153 to 159). Senior non-preferred and senior preferred, the subordinated resources (own funds + senior non-preferred) as % of RWAs,
the subordination requirement of KM2 (zero for these banks), and the headroom.

**IRRBB** (rows 130 to 143). The change of economic value of both banks is added in each scenario and divided by Tier 1. The supervisory limit is 15%.

## Merger: formulas (four years)

The layout follows Figure 89. Capital is in EUR bn. Profit is in EUR m. The deal terms come from Calc.

- Cost synergies = target costs x cost synergy % x phase-in. Revenue synergies = target revenues x revenue synergy % x phase-in.
- Restructuring = restructuring % x run-rate cost synergies, after tax, in 2026E.
- Deal financing = cash paid x expected deposit rate of the year x (1 - tax rate).
- Total net profit = NBG profit + k x target profit + deal effects.
- NBG shares = net profit / EPS (consensus). New shares come from Calc. New share total is the sum.
- CET1 new = NBG CET1 (organic) + target CET1 less price paid + value of shares issued + minority interest, fair value, and costs + cumulative retained profit of the target and the deal.
  NBG CET1 in 2026E is the reported CET1 of the data quarter. Later years add retained profit (1 - payout ratio).
- RWAs = NBG RWAs + target RWAs (each grows at its own rate) + RWA optimisation + purchase accounting adjustment.
- Clean P/E = NBG price / pro forma EPS. P/TNAV = NBG price x new share total / pro forma tangible equity. RoTE = total net profit / pro forma tangible equity.
- Earnings impact = pro forma EPS / EPS before the deal - 1. TNAV per share impact compares tangible equity per share with and without the deal.
- Return on investment = (target profit + after-tax synergies + deal financing) / price. It excludes restructuring.
- A year with consensus uses it (net income, revenue, revenue less operating profit as cost). A year without consensus grows from the year before (profit: growth input, costs and revenue: cost growth input).
  A target without consensus in year 1 (BIL, HCOB) starts from the net income of the last 12 months and the opex of the last fiscal year. Revenue = costs / cost-income ratio (input).
  Bank of Cyprus has consensus for 3 years. Year 4 grows from year 3.

## The review of the original sheet

Sheet Review lists each finding and a table of every typed number. The main findings:

1. New shares were divided by NBG market cap instead of the NBG price. They were overstated by 11%.
2. The share split of BIL and HCOB was blank, so no shares were issued.
3. The case NBG at 13% CET1 paid out excess CET1 but kept market cap and profit. This created a price gain of 13% from nothing.
4. Cash paid did not reduce market cap. A cash deal looked almost free.
5. Profit counted at the stake, but price, cash, CET1 and RWAs counted at 100%.
6. Tangible equity of BIL and BoC was accounting equity less AT1, without deducting intangible assets.
7. The tax rate was 25% for every bank. The model uses the statutory rate of each bank (Bloomberg, sheet Market).
8. The deposit rate of 3% is near the OIS-based averages of the later years. It is too high for the current year, in which the realised rates are lower.
9. The DTA lever added 0.4bn that is already in CET1 (P3DH, CC1 and CC2).
10. BIL and HCOB had profit, opex, tax rate, and valuation as typed numbers without a source. All come from P3DH or Bloomberg now.

Effect on the upside for NBG holders (market cap method): +15.8% (BIL), +11.0% (BoC), +15.1% (HCOB) in the original sheet.
With the corrections, the data of P3DH and Bloomberg, and the year 2027E, the upside is much lower: see the Review sheet, which shows each step.
Valuation of BIL and HCOB: your sheet used 0.926x tangible equity for BIL (EUR 2.2bn) and EUR 2.5bn for HCOB. The sheet Calc (rows 160 to 167) shows the value of the nearest peers on tangible equity, on CET1, and on average.

## Limits

- The model shows one year (Calc) and four years (Merger). It does not model dividends in detail, DTC amortisation, or deposit flows.
- Consensus for the last year has few brokers. The net profit and EPS consensus of that year do not always match, so the share count that follows from them can jump.
- The issuance needs use the pro forma stack of the combination. The instruments of the target count in full unless N19 is lower (see above).
- The assumed subordination requirement is a rule of thumb from the filings of other banks, not a decision of a resolution authority.
- The senior surplus counts all CET1 towards MREL. CET1 used for the combined buffer does not count. The surplus is too high by the combined buffer.
- HCOB files no KM2 or TLAC1 in P3DH, so its MREL line has capital only.
- The valuation of a bank without listed shares is the median multiple of listed peers. BIL and HCOB are not traded. A real price depends on a negotiation.
  The two bases differ clearly for both banks. A different k (10 to 30) moves the value of BIL by less than 10%.
- For HCOB the net income of the last fiscal year and of the last 12 months differ clearly (sheet Market). The model uses the last 12 months. Check which one fits the case.
- Opex, revenue, and net income of a bank without consensus are values of the last fiscal year or the last 12 months. They are not forecasts. The growth inputs extend them.
- The profit of a bank without consensus leaves out discontinued operations. The net income of Bloomberg for BIL includes the gain on the sale of a subsidiary, so the model uses the income from continuing operations. This lowers the return on tangible equity of BIL, and so its peer-based valuation.
  Bloomberg has no half-year result of 2026 for BIL: its profit is the last fiscal year.
- The statutory tax rate is the rate on the law. The effective rates of BIL and HCOB differ much from it (sheet Market). The model uses the statutory rate.
- The Bloomberg data is a pull of one day. The page warns when it is older than 7 days.
- The size of the DTC lever (N16) and the waived dividend (D29) are scenario inputs.
- Liquidity can be trapped in a subsidiary. The model pools it.

## How to refresh

```
.venv/Scripts/python scripts/refresh_p3dh.py                 # P3DH data and clean layer
C:\Users\E40889\Documents\blauto\.venv\Scripts\python scripts/pull_bloomberg.py rates      # Bloomberg (terminal must run). See docs/bloomberg_db.md
dashboard/.venv/Scripts/python scripts/build_ma_workbook.py   # docs/M&A calc v2.xlsx
dashboard/.venv/Scripts/python scripts/test_ma_workbook.py    # tests (the check with the library formulas needs: pip install formulas)
dashboard/.venv/Scripts/python scripts/test_bbg.py            # tests of the Bloomberg modules
```
The page reads the database. New data shows on the page after a reload.
