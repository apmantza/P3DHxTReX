# P3DH template status

This is the working note on the clean layer. The goal is a clean layer for every template. `scripts/clean_templates.py` writes this file at each run. Edit the lists `CLEAN_NOTES` and `family_note` in that script, not this file.

Status values:

- clean: unit, zero, and scale tests run. Use `clean_period_fact` or `clean_fact`.
- partly clean: some cells are tested.
- not clean: no test. Use the raw `fact` table for one bank in one filing only.
- text only: no amounts.
- not downloaded: no data in the database.

Count by status: not clean 98, text only 6, clean 6, partly clean 3, not downloaded 1.

## Result of the last run

| Template | Entity-filings | ok | rescaled or converted | removed |
|----------|----------------|----|-----------------------|---------|
| K_68.00 | 492 | 409 | 49 | 34 |
| K_20.01 | 290 | 261 | 5 | 24 |
| K_20.02 | 268 | 243 | 4 | 21 |
| K_20.03 | 265 | 241 | 5 | 19 |

## All templates

| Template | Title | Status | Note |
|----------|-------|--------|------|
| K_00.01 | Accompanying narrative FINDIS | text only | Narrative text. HTML escapes occur in some facts. |
| K_00.02 | Accompanying narrative CODIS | text only | Narrative text. HTML escapes occur in some facts. |
| K_00.03 | Accompanying narrative ESGDIS | text only | Narrative text. HTML escapes occur in some facts. |
| K_00.04 | Accompanying narrative IRRBBDIS | text only | Narrative text. HTML escapes occur in some facts. |
| K_00.05 | Accompanying narrative MREL/TLACDIS | text only | Narrative text. HTML escapes occur in some facts. |
| K_00.06 | Accompanying narrative G-SIIs | text only | Narrative text. HTML escapes occur in some facts. |
| K_01.00 | Template EU CAE1 – Exposures to crypto-assets | not clean | Not tested. |
| K_02.00 | EU CCR1 – Analysis of CCR exposure by approach | not clean | Sums pass in 98.6% of tests. Non-monetary cells (alpha in K_02.00, PD and LGD in K_04.00) carry FX or unit factors. Whole-filing unit errors are not tested. |
| K_03.00 | EU CCR3 – Standardised approach – CCR exposures by regulatory exposure class and risk weig | not clean | Sums pass in 98.6% of tests. Non-monetary cells (alpha in K_02.00, PD and LGD in K_04.00) carry FX or unit factors. Whole-filing unit errors are not tested. |
| K_04.00 | EU CCR4 – IRB approach – CCR exposures by exposure class and PD scale | not clean | Sums pass in 98.6% of tests. Non-monetary cells (alpha in K_02.00, PD and LGD in K_04.00) carry FX or unit factors. Whole-filing unit errors are not tested. |
| K_05.00 | EU CCR5 – Composition of collateral for CCR exposures | not clean | Sums pass in 98.6% of tests. Non-monetary cells (alpha in K_02.00, PD and LGD in K_04.00) carry FX or unit factors. Whole-filing unit errors are not tested. |
| K_06.00 | EU CCR6 – Credit derivatives exposures | not clean | Sums pass in 98.6% of tests. Non-monetary cells (alpha in K_02.00, PD and LGD in K_04.00) carry FX or unit factors. Whole-filing unit errors are not tested. |
| K_07.00 | EU CCR7 – RWEA flow statements of CCR exposures under the IMM | not clean | Sums pass in 98.6% of tests. Non-monetary cells (alpha in K_02.00, PD and LGD in K_04.00) carry FX or unit factors. Whole-filing unit errors are not tested. |
| K_08.00 | EU CCR8 – Exposures to CCPs | not clean | Sums pass in 98.6% of tests. Non-monetary cells (alpha in K_02.00, PD and LGD in K_04.00) carry FX or unit factors. Whole-filing unit errors are not tested. |
| K_09.01 | EU-SEC1 - Securitisation exposures in the non-trading book | not clean | Securitisation, market risk, and CVA templates. Sums pass in 98.6% of tests. Whole-filing unit errors are not tested. |
| K_09.02 | EU-SEC2 - Securitisation exposures in the trading book | not clean | Securitisation, market risk, and CVA templates. Sums pass in 98.6% of tests. Whole-filing unit errors are not tested. |
| K_09.03 | EU-SEC3 - Securitisation exposures in the non-trading book and associated regulatory capit | not clean | Securitisation, market risk, and CVA templates. Sums pass in 98.6% of tests. Whole-filing unit errors are not tested. |
| K_09.04 | EU-SEC4 - Securitisation exposures in the non-trading book and associated regulatory capit | not clean | Securitisation, market risk, and CVA templates. Sums pass in 98.6% of tests. Whole-filing unit errors are not tested. |
| K_09.05 | EU-SEC5 - Exposures securitised by the institution - Exposures in default and specific cre | not clean | Securitisation, market risk, and CVA templates. Sums pass in 98.6% of tests. Whole-filing unit errors are not tested. |
| K_10.00 | EU MR1 - Market risk under the standardised approach | not clean | Securitisation, market risk, and CVA templates. Sums pass in 98.6% of tests. Whole-filing unit errors are not tested. |
| K_11.00 | EU MR2-A - Market risk under the internal Model Approach (IMA) | not clean | Securitisation, market risk, and CVA templates. Sums pass in 98.6% of tests. Whole-filing unit errors are not tested. |
| K_12.00 | EU MR2-B - RWA flow statements of market risk exposures under the IMA | not clean | Securitisation, market risk, and CVA templates. Sums pass in 98.6% of tests. Whole-filing unit errors are not tested. |
| K_13.00 | EU MR3 - IMA values for trading portfolios | not clean | Securitisation, market risk, and CVA templates. Sums pass in 98.6% of tests. Whole-filing unit errors are not tested. |
| K_18.01 | EU CVA 1 – Credit valuation adjustment risk under the Reduced Basic Approach | not clean | Securitisation, market risk, and CVA templates. Sums pass in 98.6% of tests. Whole-filing unit errors are not tested. |
| K_18.02 | EU CVA 2 – Credit valuation adjustment risk under the Full Basic Approach | not clean | Securitisation, market risk, and CVA templates. Sums pass in 98.6% of tests. Whole-filing unit errors are not tested. |
| K_18.03 | EU CVA3 – Credit valuation adjustment risk under the Standardised Approach | not clean | Securitisation, market risk, and CVA templates. Sums pass in 98.6% of tests. Whole-filing unit errors are not tested. |
| K_18.04 | EU CVA4 – RWEA flow statements of credit valuation adjustment risk under the Standardised  | not clean | Securitisation, market risk, and CVA templates. Sums pass in 98.6% of tests. Whole-filing unit errors are not tested. |
| K_19.01 | EU OR1 -Operational risk losses | not clean | Operational risk. Event counts are scaled by FX or unit factors in 516 of 4,929 cells. Sums pass in 98.6%. |
| K_19.02 | EU OR2 - Business Indicator, components and subcomponents | not clean | Operational risk. Event counts are scaled by FX or unit factors in 516 of 4,929 cells. Sums pass in 98.6%. |
| K_19.03 | EU OR3 - Operational risk own funds requirements and risk exposure amounts | not clean | Operational risk. Event counts are scaled by FX or unit factors in 516 of 4,929 cells. Sums pass in 98.6%. |
| K_20.01 | EU AE1 - Encumbered and unencumbered assets | clean | AE1. Test: encumbered plus unencumbered assets against total assets. Values are medians of 4 quarters. Table clean_fact. |
| K_20.02 | EU AE2 - Collateral received and own debt securities issued | clean | AE2. Test: row 250 against the encumbered assets of AE1. Table clean_fact. |
| K_20.03 | EU AE3 - Sources   of  encumbrance | clean | AE3. Test: encumbered assets against the encumbered assets of AE1. Table clean_fact. |
| K_21.01 | EU CR1: Performing and non-performing exposures and related provisions | not clean | Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. |
| K_21.02 | EU CR1-A: Maturity of exposures | not clean | Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. |
| K_22.01 | EU CR2: Changes in the stock of non-performing loans and advances | not clean | Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. |
| K_22.02 | EU CR2a: Changes in the stock of non-performing loans and advances and related net accumul | not clean | Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. |
| K_23.00 | EU CR3 –  CRM techniques overview:  Disclosure of the use of credit risk mitigation techni | not clean | Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. |
| K_24.00 | EU CR4 – standardised approach – Credit risk exposure and CRM effects | not clean | Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. |
| K_25.00 | EU CR5 – standardised approach | not clean | Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. |
| K_26.00 | EU CR6 – IRB approach – Credit risk exposures by exposure class and PD range | not clean | Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. One exposure class has a blank key. |
| K_26.01 | EU CR6-A – Scope of the use of IRB and SA approaches | not clean | Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. |
| K_27.01 | EU CR7 – IRB approach – Effect on the RWEAs of credit derivatives used as CRM techniques | not clean | Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. |
| K_27.02 | EU CR7-A – IRB approach – Disclosure of the extent of the use of CRM techniques | not clean | Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. |
| K_28.00 | EU CR8 –  RWEA flow statements of credit risk exposures under the IRB approach | not clean | Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. |
| K_29.00 | EU CR9 –IRB approach – Back-testing of PD per exposure class (fixed PD scale) | not clean | Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. |
| K_29.01 | EU CR9.1 – IRB approach – Back-testing of PD per exposure class (only for PD estimates acc | not clean | Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. |
| K_29.02 | EU CR10 –  Specialised lending and equity exposures under the simple risk weighted approac | not clean | Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. The layout changes between dates. |
| K_30.01 | EU REM1 - Remuneration awarded for the financial year | not clean | Remuneration. Pay per head is below EUR 10,000 in 14% of entity-dates (unit errors). |
| K_30.02 | EU REM2 - Special payments  to staff whose professional activities have a material impact  | not clean | Remuneration. Pay per head is below EUR 10,000 in 14% of entity-dates (unit errors). |
| K_30.03 | EU REM3 - Deferred remuneration | not clean | Remuneration. Pay per head is below EUR 10,000 in 14% of entity-dates (unit errors). |
| K_30.04 | EU REM4 - Remuneration of 1 million EUR or more per year | not clean | Remuneration. Pay per head is below EUR 10,000 in 14% of entity-dates (unit errors). |
| K_30.05 | EU REM5 - Information on remuneration of staff whose professional activities have a materi | not clean | Remuneration. Pay per head is below EUR 10,000 in 14% of entity-dates (unit errors). |
| K_41.00 | Template 1 - Banking book- Indicators of potential climate Change transition risk: Credit  | not clean | Climate and GAR. About 4.5% of entity-dates have a wrong scale. K_43.00 keys contain the metric value. |
| K_42.00 | Template 2 - Banking book - Indicators of potential climate change transition risk: Loans  | not clean | Climate and GAR. About 4.5% of entity-dates have a wrong scale. K_43.00 keys contain the metric value. |
| K_43.00 | Template 3 - Banking book - Indicators of potential climate change transition risk: Alignm | not clean | Climate and GAR. About 4.5% of entity-dates have a wrong scale. K_43.00 keys contain the metric value. |
| K_44.00 | Template 4 - Banking book - Indicators of potential climate change transition risk: Exposu | not clean | Climate and GAR. About 4.5% of entity-dates have a wrong scale. K_43.00 keys contain the metric value. |
| K_45.00 | Template 5 - Banking book - Indicators of potential climate change physical risk: Exposure | not clean | Climate and GAR. About 4.5% of entity-dates have a wrong scale. K_43.00 keys contain the metric value. |
| K_46.00 | Template 6 - Summary of GAR KPIs | not clean | Climate and GAR. About 4.5% of entity-dates have a wrong scale. K_43.00 keys contain the metric value. |
| K_47.00 | Template 7 - Mitigating actions: Assets for the calculation of GAR | not clean | Climate and GAR. About 4.5% of entity-dates have a wrong scale. K_43.00 keys contain the metric value. |
| K_48.00 | Template 8 - GAR (%) | not clean | Climate and GAR. About 4.5% of entity-dates have a wrong scale. K_43.00 keys contain the metric value. |
| K_49.01 | Template 9.1 - Mitigating actions: Assets for the calculation of BTAR | not clean | Climate and GAR. About 4.5% of entity-dates have a wrong scale. K_43.00 keys contain the metric value. |
| K_49.02 | Template 9.2 - BTAR % | not clean | Climate and GAR. About 4.5% of entity-dates have a wrong scale. K_43.00 keys contain the metric value. |
| K_49.03 | Template 9.3 - Summary table - BTAR % | not clean | Climate and GAR. About 4.5% of entity-dates have a wrong scale. K_43.00 keys contain the metric value. |
| K_50.00 | Template 10 - Other climate change mitigating actions that are not covered in the EU Taxon | not clean | Climate and GAR. About 4.5% of entity-dates have a wrong scale. K_43.00 keys contain the metric value. |
| K_60.00 | EU OV1 – Overview of total risk exposure amounts | clean | OV1, column T only. Tests: scale against KM1, zero total. Table clean_period_fact. |
| K_61.00 | EU KM1 - Key metrics template | clean | KM1. Tests: units, zeros, ratio units, period dates. Table clean_period_fact. |
| K_62.01 | EU INS1 - Insurance participations | not clean | Not assessed in detail. Unit errors are not tested. |
| K_62.02 | EU INS2 - Financial conglomerates information on own funds and capital adequacy ratio | not clean | Not assessed in detail. Unit errors are not tested. |
| K_63.01 | EU CMS1 – Comparison of modelled and standardised risk weighted exposure amounts at risk l | not clean | Not assessed in detail. Unit errors are not tested. |
| K_63.02 | EU CMS2 – Comparison of modelled and standardised risk weighted exposure amounts for credi | not clean | Not assessed in detail. Unit errors are not tested. |
| K_64.01 | EU LI1 - Differences between the accounting scope and the scope of prudential consolidatio | partly clean | Row "Total assets" is tested for scale (table entity_assets). The other rows have no test. |
| K_64.02 | EU LI3 - Outline of the differences in the scopes of consolidation (entity by entity) | not clean | Not assessed in detail. Unit errors are not tested. |
| K_64.03 | EU LI2 - Main sources of differences between regulatory exposure amounts and carrying valu | not clean | Not assessed in detail. Unit errors are not tested. |
| K_65.00 | EU PV1: Prudent valuation adjustments (PVA) | not clean | Not assessed in detail. Unit errors are not tested. |
| K_66.01 | EU CC1 - Composition of regulatory own funds | not clean | Own funds (CC1). Sums fail in 2.7% to 4.7% of cells. CC1 shares the unit error of KM1 in one filing. |
| K_66.02 | EU CC2 - reconciliation of regulatory own funds to balance sheet in the audited financial  | partly clean | Row "Total assets" is tested for scale (table entity_assets). The other rows have no test. |
| K_67.01 | EU CCyB1 - Geographical distribution of credit exposures relevant for the calculation of t | not clean | CCyB1. Open table with a blank key. About 5% of entity-filings have ratios in percentage points. |
| K_67.02 | EU CCyB2 - Amount of institution-specific countercyclical capital buffer | not clean | CCyB2. Ratios in percentage points in about 5% of entity-filings. |
| K_68.00 | EU IRRBB1 - Interest rate risks of non-trading book activities | clean | IRRBB1. Test: size against Tier 1. Six unit conventions are found and converted. Table clean_fact. The last-period columns have no date. |
| K_70.00 | EU LR1 - LRSum: Summary reconciliation of accounting assets and leverage ratio exposures | partly clean | Row "Total assets" is tested for scale (table entity_assets). The other rows have no test. |
| K_71.00 | EU LR2 - LRCom: Leverage ratio common disclosure | not clean | LR2. Leverage ratio in percentage points for 11 banks (for example Piraeus). T-1 is the previous disclosure date. |
| K_72.00 | EU LR3 - LRSpl: Split-up of on balance sheet exposures (excluding derivatives, SFTs and ex | not clean | Not assessed in detail. Unit errors are not tested. |
| K_73.00 | EU LIQ1 - Quantitative information of LCR | not clean | LIQ1 and LIQ2. LCR and NSFR in percentage points for about 2%. Outflows fail the sum test in 8.4%. |
| K_74.00 | EU LIQ2: Net Stable Funding Ratio | not clean | LIQ1 and LIQ2. LCR and NSFR in percentage points for about 2%. Outflows fail the sum test in 8.4%. |
| K_80.00 | EU CQ1: Credit quality of forborne exposures | not clean | Credit quality (CQ). CQ3 equals CR1 in all tested cases. Unit errors are not tested. |
| K_81.00 | EU CQ2: Quality of forbearance | not clean | Credit quality (CQ). CQ3 equals CR1 in all tested cases. Unit errors are not tested. |
| K_82.00 | EU CQ3: Credit quality of performing and non-performing exposures by past due days | not clean | Credit quality (CQ). CQ3 equals CR1 in all tested cases. Unit errors are not tested. |
| K_83.01 | EU CQ4: Quality of non-performing exposures by geography | not downloaded | The server times out. The downloader skips this template. |
| K_84.01 | EU CQ5: Credit quality of loans and advances by industry | not clean | Credit quality (CQ). CQ3 equals CR1 in all tested cases. Unit errors are not tested. |
| K_85.00 | EU CQ6: Collateral valuation - loans and advances | not clean | Credit quality (CQ). CQ3 equals CR1 in all tested cases. Unit errors are not tested. |
| K_86.00 | EU CQ7: Collateral obtained by taking possession and execution processes | not clean | Credit quality (CQ). CQ3 equals CR1 in all tested cases. Unit errors are not tested. |
| K_87.00 | EU CQ8: Collateral obtained by taking possession and execution processes – vintage breakdo | not clean | Credit quality (CQ). CQ3 equals CR1 in all tested cases. Unit errors are not tested. |
| K_90.01 | EU KM2 - Key metrics - MREL and, where applicable, G-SII requirement for own funds and eli | not clean | MREL and TLAC. Ratios in percentage points (NBG, 3 of 3 filings). Not tested. |
| K_91.00 | EU TLAC1 - Composition - MREL and, where applicable, G-SII requirement for own funds and e | not clean | MREL and TLAC. Ratios in percentage points (NBG, 3 of 3 filings). Not tested. |
| K_93.00 | EU ILAC - Internal loss absorbing capacity: internal MREL and, where applicable, requireme | not clean | MREL and TLAC. Ratios in percentage points (NBG, 3 of 3 filings). Not tested. |
| K_95.00 | Creditor ranking - Entity that is not a resolution entity | not clean | Creditor ranking. Open tables with blank keys. Rank labels change between dates. |
| K_96.00 | EU TLAC2b: Creditor ranking - Entity that is not a resolution entity | not clean | Creditor ranking. Open tables with blank keys. Rank labels change between dates. |
| K_97.00 | EU TLAC3 - creditor ranking - resolution entity | not clean | Creditor ranking. Open tables with blank keys. Rank labels change between dates. |
| K_98.00 | EU TLAC3b: creditor ranking - resolution entity | not clean | Creditor ranking. Open tables with blank keys. Rank labels change between dates. |
| K_100.00 | Section 1 - General Information | not clean | G-SIB indicators. Three of 13 banks file in million or thousand. |
| K_101.00 | Section 2- total exposures | not clean | G-SIB indicators. Three of 13 banks file in million or thousand. |
| K_102.00 | Section 3 - Intra-Financial System Assets | not clean | G-SIB indicators. Three of 13 banks file in million or thousand. |
| K_103.00 | Section 4 - Intra-Financial System Liabilities | not clean | G-SIB indicators. Three of 13 banks file in million or thousand. |
| K_104.00 | Section 5 - Securities Outstanding | not clean | G-SIB indicators. Three of 13 banks file in million or thousand. |
| K_105.00 | Section 6 - Payments made in the reporting year excluding intragroup payments | not clean | G-SIB indicators. Three of 13 banks file in million or thousand. |
| K_106.00 | Section 7 - Assets Under Custody | not clean | G-SIB indicators. Three of 13 banks file in million or thousand. |
| K_107.00 | Section 8 - Underwritten Transactions in Debt and Equity Markets | not clean | G-SIB indicators. Three of 13 banks file in million or thousand. |
| K_108.00 | Section 9 - Trading Volume | not clean | G-SIB indicators. Three of 13 banks file in million or thousand. |
| K_109.00 | Section 10 - Notional Amount of Over-the-Counter OTC Derivatives | not clean | G-SIB indicators. Three of 13 banks file in million or thousand. |
| K_110.00 | Section 11 - Trading and Available-for-Sale Securities | not clean | G-SIB indicators. Three of 13 banks file in million or thousand. |
| K_111.00 | Section 12 - Level 3 Assets | not clean | G-SIB indicators. Three of 13 banks file in million or thousand. |
| K_112.00 | Section 13 - Cross-Jurisdictional Claims | not clean | G-SIB indicators. Three of 13 banks file in million or thousand. |
| K_113.00 | Section 14 - Cross-Jurisdictional Liabilities | not clean | G-SIB indicators. Three of 13 banks file in million or thousand. |

## Next in line

1. Credit risk and credit quality (K_21.01 to K_29.02, K_80.00 to K_87.00): anchor on total assets and CR1.
2. Liquidity and leverage (K_71.00 to K_74.00): anchor on KM1.
3. MREL, TLAC, and creditor ranking (K_90.01 to K_98.00): ratio units.
4. Climate, remuneration, and G-SIB (K_30.01, K_41.00 to K_50.00, K_100.00 to K_113.00).
