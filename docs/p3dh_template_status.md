# P3DH template status

This is the working note on the clean layer. The goal is a clean layer for every template. `scripts/clean_templates.py` and `scripts/clean_engine.py` write this file at each run. Edit the lists `CLEAN_NOTES` and `family_note` in `clean_templates.py`, not this file.

Status values:

- clean: unit, zero, and scale tests run with a rule for the template. Use `clean_period_fact` or `clean_fact`.
- clean (auto): the generic engine found a reliable scale anchor. Use `clean_fact`.
- partly clean: some cells are tested.
- not clean: no test. Use the raw `fact` table for one bank in one filing only.
- text only: no numeric facts.
- no amounts: numbers are ratios or counts. No unit factor applies.
- not downloaded: no data in the database.

Count by status: clean (auto) 79, not clean 15, no amounts 8, clean 6, text only 5, not downloaded 1.

## Result of the last run

| Template | Entity-filings | ok | rescaled or converted | with removed cells |
|----------|----------------|----|-----------------------|--------------------|
| K_02.00 | 505 | 453 | 17 | 35 |
| K_03.00 | 472 | 417 | 14 | 41 |
| K_07.00 | 123 | 123 | 0 | 0 |
| K_08.00 | 368 | 335 | 8 | 25 |
| K_09.01 | 270 | 227 | 14 | 29 |
| K_09.02 | 58 | 54 | 2 | 2 |
| K_09.03 | 198 | 158 | 5 | 35 |
| K_09.04 | 202 | 169 | 10 | 23 |
| K_09.05 | 203 | 183 | 5 | 15 |
| K_10.00 | 390 | 347 | 13 | 30 |
| K_11.00 | 119 | 113 | 2 | 4 |
| K_12.00 | 212 | 201 | 2 | 9 |
| K_13.00 | 119 | 112 | 2 | 5 |
| K_18.01 | 194 | 162 | 8 | 24 |
| K_18.02 | 47 | 41 | 0 | 6 |
| K_18.03 | 27 | 24 | 0 | 3 |
| K_18.04 | 180 | 176 | 3 | 1 |
| K_19.01 | 163 | 135 | 6 | 22 |
| K_19.02 | 270 | 237 | 4 | 29 |
| K_19.03 | 297 | 274 | 3 | 20 |
| K_20.01 | 290 | 261 | 5 | 24 |
| K_20.02 | 268 | 243 | 4 | 21 |
| K_20.03 | 265 | 241 | 5 | 19 |
| K_21.01 | 871 | 808 | 12 | 51 |
| K_21.02 | 571 | 525 | 20 | 26 |
| K_22.01 | 498 | 456 | 17 | 25 |
| K_22.02 | 122 | 106 | 5 | 11 |
| K_23.00 | 580 | 543 | 10 | 27 |
| K_24.00 | 628 | 585 | 20 | 23 |
| K_25.00 | 527 | 496 | 11 | 20 |
| K_26.00 | 242 | 221 | 12 | 9 |
| K_26.01 | 105 | 99 | 5 | 1 |
| K_27.01 | 227 | 221 | 1 | 5 |
| K_27.02 | 344 | 331 | 10 | 3 |
| K_28.00 | 539 | 526 | 7 | 6 |
| K_29.02 | 291 | 262 | 6 | 23 |
| K_30.01 | 581 | 469 | 55 | 57 |
| K_30.03 | 362 | 259 | 26 | 77 |
| K_30.05 | 357 | 291 | 32 | 34 |
| K_41.00 | 375 | 332 | 27 | 16 |
| K_42.00 | 361 | 318 | 32 | 11 |
| K_45.00 | 359 | 331 | 21 | 7 |
| K_47.00 | 62 | 51 | 3 | 8 |
| K_49.01 | 21 | 18 | 1 | 2 |
| K_50.00 | 52 | 39 | 10 | 3 |
| K_62.01 | 78 | 64 | 8 | 6 |
| K_62.02 | 44 | 38 | 1 | 5 |
| K_63.01 | 608 | 585 | 7 | 16 |
| K_63.02 | 552 | 532 | 7 | 13 |
| K_64.01 | 239 | 219 | 3 | 17 |
| K_64.03 | 235 | 212 | 4 | 19 |
| K_65.00 | 141 | 120 | 7 | 14 |
| K_66.01 | 908 | 844 | 21 | 43 |
| K_66.02 | 817 | 751 | 15 | 51 |
| K_67.02 | 621 | 567 | 26 | 28 |
| K_68.00 | 492 | 409 | 29 | 54 |
| K_70.00 | 635 | 601 | 10 | 24 |
| K_71.00 | 629 | 582 | 23 | 24 |
| K_72.00 | 630 | 592 | 14 | 24 |
| K_73.00 | 905 | 859 | 22 | 24 |
| K_74.00 | 606 | 573 | 13 | 20 |
| K_80.00 | 808 | 714 | 18 | 76 |
| K_81.00 | 65 | 52 | 8 | 5 |
| K_82.00 | 631 | 591 | 6 | 34 |
| K_84.01 | 580 | 524 | 25 | 31 |
| K_85.00 | 105 | 93 | 4 | 8 |
| K_90.01 | 459 | 416 | 22 | 21 |
| K_91.00 | 228 | 208 | 10 | 10 |
| K_93.00 | 174 | 157 | 11 | 6 |
| K_95.00 | 52 | 49 | 1 | 2 |
| K_96.00 | 45 | 39 | 3 | 3 |
| K_97.00 | 82 | 75 | 2 | 5 |
| K_98.00 | 128 | 120 | 0 | 8 |
| K_101.00 | 16 | 13 | 3 | 0 |
| K_102.00 | 13 | 10 | 3 | 0 |
| K_103.00 | 13 | 10 | 3 | 0 |
| K_104.00 | 13 | 10 | 3 | 0 |
| K_107.00 | 11 | 8 | 3 | 0 |
| K_108.00 | 12 | 9 | 3 | 0 |
| K_109.00 | 13 | 10 | 3 | 0 |
| K_110.00 | 13 | 10 | 3 | 0 |
| K_112.00 | 12 | 9 | 3 | 0 |
| K_113.00 | 12 | 9 | 3 | 0 |

## All templates

| Template | Title | Status | Note |
|----------|-------|--------|------|
| K_00.01 | Accompanying narrative FINDIS | text only | Narrative text. HTML escapes occur in some facts. |
| K_00.02 | Accompanying narrative CODIS | no amounts | No amount cells (ratios, counts, or text). Nothing to rescale. Narrative text. HTML escapes occur in some facts. |
| K_00.03 | Accompanying narrative ESGDIS | text only | Narrative text. HTML escapes occur in some facts. |
| K_00.04 | Accompanying narrative IRRBBDIS | text only | Narrative text. HTML escapes occur in some facts. |
| K_00.05 | Accompanying narrative MREL/TLACDIS | text only | Narrative text. HTML escapes occur in some facts. |
| K_00.06 | Accompanying narrative G-SIIs | text only | Narrative text. HTML escapes occur in some facts. |
| K_01.00 | Template EU CAE1 – Exposures to crypto-assets | not clean | No reliable scale anchor (best anchor S:K_09.01: 64% of filings in the main mode, spread 0.19; needs at least 70% and at most 0.35). Not tested. |
| K_02.00 | EU CCR1 – Analysis of CCR exposure by approach | clean (auto) | Engine test against anchor S:K_07.00: 96% of filings in the main mode (spread 0.24). Sums pass in 98.6% of tests. Non-monetary cells (alpha in K_02.00, PD and LGD in K_04.00) carry FX or unit factors. Whole-filing unit errors are not tested. |
| K_03.00 | EU CCR3 – Standardised approach – CCR exposures by regulatory exposure class and risk weig | clean (auto) | Engine test against anchor S:K_07.00: 91% of filings in the main mode (spread 0.26). Sums pass in 98.6% of tests. Non-monetary cells (alpha in K_02.00, PD and LGD in K_04.00) carry FX or unit factors. Whole-filing unit errors are not tested. |
| K_04.00 | EU CCR4 – IRB approach – CCR exposures by exposure class and PD scale | not clean | No reliable scale anchor (best anchor S:K_85.00: 40% of filings in the main mode, spread 0.23; needs at least 70% and at most 0.35). Sums pass in 98.6% of tests. Non-monetary cells (alpha in K_02.00, PD and LGD in K_04.00) carry FX or unit factors. Whole-filing unit errors are not tested. |
| K_05.00 | EU CCR5 – Composition of collateral for CCR exposures | not clean | No reliable scale anchor (best anchor S:K_13.00: 91% of filings in the main mode, spread 0.39; needs at least 70% and at most 0.35). Sums pass in 98.6% of tests. Non-monetary cells (alpha in K_02.00, PD and LGD in K_04.00) carry FX or unit factors. Whole-filing unit errors are not tested. |
| K_06.00 | EU CCR6 – Credit derivatives exposures | not clean | No reliable scale anchor (best anchor S:K_22.02: 43% of filings in the main mode, spread 0.30; needs at least 70% and at most 0.35). Sums pass in 98.6% of tests. Non-monetary cells (alpha in K_02.00, PD and LGD in K_04.00) carry FX or unit factors. Whole-filing unit errors are not tested. |
| K_07.00 | EU CCR7 – RWEA flow statements of CCR exposures under the IMM | clean (auto) | Engine test against anchor OV1_CCR: 100% of filings in the main mode (spread 0.11). Sums pass in 98.6% of tests. Non-monetary cells (alpha in K_02.00, PD and LGD in K_04.00) carry FX or unit factors. Whole-filing unit errors are not tested. |
| K_08.00 | EU CCR8 – Exposures to CCPs | clean (auto) | Engine test against anchor S:K_03.00: 82% of filings in the main mode (spread 0.30). Sums pass in 98.6% of tests. Non-monetary cells (alpha in K_02.00, PD and LGD in K_04.00) carry FX or unit factors. Whole-filing unit errors are not tested. |
| K_09.01 | EU-SEC1 - Securitisation exposures in the non-trading book | clean (auto) | Engine test against anchor OV1_SEC: 91% of filings in the main mode (spread 0.34). Securitisation, market risk, and CVA templates. Sums pass in 98.6% of tests. Whole-filing unit errors are not tested. |
| K_09.02 | EU-SEC2 - Securitisation exposures in the trading book | clean (auto) | Engine test against anchor TA: 84% of filings in the main mode (spread 0.24). Securitisation, market risk, and CVA templates. Sums pass in 98.6% of tests. Whole-filing unit errors are not tested. |
| K_09.03 | EU-SEC3 - Securitisation exposures in the non-trading book and associated regulatory capit | clean (auto) | Engine test against anchor S:K_09.01: 86% of filings in the main mode (spread 0.10). Securitisation, market risk, and CVA templates. Sums pass in 98.6% of tests. Whole-filing unit errors are not tested. |
| K_09.04 | EU-SEC4 - Securitisation exposures in the non-trading book and associated regulatory capit | clean (auto) | Engine test against anchor S:K_09.02: 84% of filings in the main mode (spread 0.17). Securitisation, market risk, and CVA templates. Sums pass in 98.6% of tests. Whole-filing unit errors are not tested. |
| K_09.05 | EU-SEC5 - Exposures securitised by the institution - Exposures in default and specific cre | clean (auto) | Engine test against anchor S:K_09.01: 85% of filings in the main mode (spread 0.24). Securitisation, market risk, and CVA templates. Sums pass in 98.6% of tests. Whole-filing unit errors are not tested. |
| K_10.00 | EU MR1 - Market risk under the standardised approach | clean (auto) | Engine test against anchor OV1_MKT: 92% of filings in the main mode (spread 0.04). Securitisation, market risk, and CVA templates. Sums pass in 98.6% of tests. Whole-filing unit errors are not tested. |
| K_11.00 | EU MR2-A - Market risk under the internal Model Approach (IMA) | clean (auto) | Engine test against anchor OV1_MKT: 100% of filings in the main mode (spread 0.20). Securitisation, market risk, and CVA templates. Sums pass in 98.6% of tests. Whole-filing unit errors are not tested. |
| K_12.00 | EU MR2-B - RWA flow statements of market risk exposures under the IMA | clean (auto) | Engine test against anchor S:K_11.00: 98% of filings in the main mode (spread 0.10). Securitisation, market risk, and CVA templates. Sums pass in 98.6% of tests. Whole-filing unit errors are not tested. |
| K_13.00 | EU MR3 - IMA values for trading portfolios | clean (auto) | Engine test against anchor S:K_12.00: 98% of filings in the main mode (spread 0.12). Securitisation, market risk, and CVA templates. Sums pass in 98.6% of tests. Whole-filing unit errors are not tested. |
| K_18.01 | EU CVA 1 – Credit valuation adjustment risk under the Reduced Basic Approach | clean (auto) | Engine test against anchor OV1_CVA: 84% of filings in the main mode (spread 0.11). Securitisation, market risk, and CVA templates. Sums pass in 98.6% of tests. Whole-filing unit errors are not tested. |
| K_18.02 | EU CVA 2 – Credit valuation adjustment risk under the Full Basic Approach | clean (auto) | Engine test against anchor OV1_CVA: 85% of filings in the main mode (spread 0.28). Securitisation, market risk, and CVA templates. Sums pass in 98.6% of tests. Whole-filing unit errors are not tested. |
| K_18.03 | EU CVA3 – Credit valuation adjustment risk under the Standardised Approach | clean (auto) | Engine test against anchor S:K_12.00: 73% of filings in the main mode (spread 0.18). Securitisation, market risk, and CVA templates. Sums pass in 98.6% of tests. Whole-filing unit errors are not tested. |
| K_18.04 | EU CVA4 – RWEA flow statements of credit valuation adjustment risk under the Standardised  | clean (auto) | Engine test against anchor OV1_CVA: 99% of filings in the main mode (spread 0.10). Securitisation, market risk, and CVA templates. Sums pass in 98.6% of tests. Whole-filing unit errors are not tested. |
| K_19.01 | EU OR1 -Operational risk losses | clean (auto) | Engine test against anchor S:K_93.00: 73% of filings in the main mode (spread 0.30). Operational risk. Event counts are scaled by FX or unit factors in 516 of 4,929 cells. Sums pass in 98.6%. |
| K_19.02 | EU OR2 - Business Indicator, components and subcomponents | clean (auto) | Engine test against anchor OV1_OPRISK: 93% of filings in the main mode (spread 0.12). Operational risk. Event counts are scaled by FX or unit factors in 516 of 4,929 cells. Sums pass in 98.6%. |
| K_19.03 | EU OR3 - Operational risk own funds requirements and risk exposure amounts | clean (auto) | Engine test against anchor OV1_OPRISK: 99% of filings in the main mode (spread 0.00). Operational risk. Event counts are scaled by FX or unit factors in 516 of 4,929 cells. Sums pass in 98.6%. |
| K_20.01 | EU AE1 - Encumbered and unencumbered assets | clean | AE1. Test: encumbered plus unencumbered assets against total assets. Values are medians of 4 quarters. Table clean_fact. |
| K_20.02 | EU AE2 - Collateral received and own debt securities issued | clean | AE2. Test: row 250 against the encumbered assets of AE1. Table clean_fact. |
| K_20.03 | EU AE3 - Sources   of  encumbrance | clean | AE3. Test: encumbered assets against the encumbered assets of AE1. Table clean_fact. |
| K_21.01 | EU CR1: Performing and non-performing exposures and related provisions | clean (auto) | Engine test against anchor T1: 94% of filings in the main mode (spread 0.20). Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. |
| K_21.02 | EU CR1-A: Maturity of exposures | clean (auto) | Engine test against anchor TA: 96% of filings in the main mode (spread 0.13). Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. |
| K_22.01 | EU CR2: Changes in the stock of non-performing loans and advances | clean (auto) | Engine test against anchor TREA: 89% of filings in the main mode (spread 0.19). Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. |
| K_22.02 | EU CR2a: Changes in the stock of non-performing loans and advances and related net accumul | clean (auto) | Engine test against anchor S:K_22.01: 95% of filings in the main mode (spread 0.01). Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. |
| K_23.00 | EU CR3 –  CRM techniques overview:  Disclosure of the use of credit risk mitigation techni | clean (auto) | Engine test against anchor S:K_21.02: 97% of filings in the main mode (spread 0.09). Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. |
| K_24.00 | EU CR4 – standardised approach – Credit risk exposure and CRM effects | clean (auto) | Engine test against anchor S:K_98.00: 94% of filings in the main mode (spread 0.30). Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. |
| K_25.00 | EU CR5 – standardised approach | clean (auto) | Engine test against anchor S:K_24.00: 97% of filings in the main mode (spread 0.18). Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. |
| K_26.00 | EU CR6 – IRB approach – Credit risk exposures by exposure class and PD range | clean (auto) | Engine test against anchor S:K_21.01: 92% of filings in the main mode (spread 0.23). Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. One exposure class has a blank key. |
| K_26.01 | EU CR6-A – Scope of the use of IRB and SA approaches | clean (auto) | Engine test against anchor S:K_23.00: 96% of filings in the main mode (spread 0.12). Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. |
| K_27.01 | EU CR7 – IRB approach – Effect on the RWEAs of credit derivatives used as CRM techniques | clean (auto) | Engine test against anchor S:K_21.01: 96% of filings in the main mode (spread 0.15). Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. |
| K_27.02 | EU CR7-A – IRB approach – Disclosure of the extent of the use of CRM techniques | clean (auto) | Engine test against anchor S:K_26.01: 99% of filings in the main mode (spread 0.20). Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. |
| K_28.00 | EU CR8 –  RWEA flow statements of credit risk exposures under the IRB approach | clean (auto) | Engine test against anchor T1: 98% of filings in the main mode (spread 0.14). Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. |
| K_29.00 | EU CR9 –IRB approach – Back-testing of PD per exposure class (fixed PD scale) | no amounts | No amount cells (ratios, counts, or text). Nothing to rescale. Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. |
| K_29.01 | EU CR9.1 – IRB approach – Back-testing of PD per exposure class (only for PD estimates acc | no amounts | No amount cells (ratios, counts, or text). Nothing to rescale. Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. |
| K_29.02 | EU CR10 –  Specialised lending and equity exposures under the simple risk weighted approac | clean (auto) | Engine test against anchor S:K_47.00: 85% of filings in the main mode (spread 0.31). Credit risk. Sums pass in 97% to 99.8% of tests. Whole-filing unit errors are not tested. The layout changes between dates. |
| K_30.01 | EU REM1 - Remuneration awarded for the financial year | clean (auto) | Engine test against anchor T1: 79% of filings in the main mode (spread 0.35). Remuneration. Pay per head is below EUR 10,000 in 14% of entity-dates (unit errors). |
| K_30.02 | EU REM2 - Special payments  to staff whose professional activities have a material impact  | not clean | No reliable scale anchor (best anchor S:K_07.00: 71% of filings in the main mode, spread 0.35; needs at least 70% and at most 0.35). Remuneration. Pay per head is below EUR 10,000 in 14% of entity-dates (unit errors). |
| K_30.03 | EU REM3 - Deferred remuneration | clean (auto) | Engine test against anchor S:K_11.00: 80% of filings in the main mode (spread 0.28). Remuneration. Pay per head is below EUR 10,000 in 14% of entity-dates (unit errors). |
| K_30.04 | EU REM4 - Remuneration of 1 million EUR or more per year | no amounts | No amount cells (ratios, counts, or text). Nothing to rescale. Remuneration. Pay per head is below EUR 10,000 in 14% of entity-dates (unit errors). |
| K_30.05 | EU REM5 - Information on remuneration of staff whose professional activities have a materi | clean (auto) | Engine test against anchor S:K_30.01: 90% of filings in the main mode (spread 0.17). Remuneration. Pay per head is below EUR 10,000 in 14% of entity-dates (unit errors). |
| K_41.00 | Template 1 - Banking book- Indicators of potential climate Change transition risk: Credit  | clean (auto) | Engine test against anchor S:K_27.01: 93% of filings in the main mode (spread 0.24). Climate and GAR. About 4.5% of entity-dates have a wrong scale. K_43.00 keys contain the metric value. |
| K_42.00 | Template 2 - Banking book - Indicators of potential climate change transition risk: Loans  | clean (auto) | Engine test against anchor S:K_27.02: 94% of filings in the main mode (spread 0.26). Climate and GAR. About 4.5% of entity-dates have a wrong scale. K_43.00 keys contain the metric value. |
| K_43.00 | Template 3 - Banking book - Indicators of potential climate change transition risk: Alignm | not clean | No reliable scale anchor (best anchor S:K_97.00: 82% of filings in the main mode, spread 0.41; needs at least 70% and at most 0.35). Climate and GAR. About 4.5% of entity-dates have a wrong scale. K_43.00 keys contain the metric value. |
| K_44.00 | Template 4 - Banking book - Indicators of potential climate change transition risk: Exposu | not clean | No reliable scale anchor (best anchor S:K_18.04: 68% of filings in the main mode, spread 0.16; needs at least 70% and at most 0.35). Climate and GAR. About 4.5% of entity-dates have a wrong scale. K_43.00 keys contain the metric value. |
| K_45.00 | Template 5 - Banking book - Indicators of potential climate change physical risk: Exposure | clean (auto) | Engine test against anchor S:K_62.02: 73% of filings in the main mode (spread 0.28). Climate and GAR. About 4.5% of entity-dates have a wrong scale. K_43.00 keys contain the metric value. |
| K_46.00 | Template 6 - Summary of GAR KPIs | no amounts | No amount cells (ratios, counts, or text). Nothing to rescale. Climate and GAR. About 4.5% of entity-dates have a wrong scale. K_43.00 keys contain the metric value. |
| K_47.00 | Template 7 - Mitigating actions: Assets for the calculation of GAR | clean (auto) | Engine test against anchor S:K_23.00: 96% of filings in the main mode (spread 0.16). Climate and GAR. About 4.5% of entity-dates have a wrong scale. K_43.00 keys contain the metric value. |
| K_48.00 | Template 8 - GAR (%) | no amounts | No amount cells (ratios, counts, or text). Nothing to rescale. Climate and GAR. About 4.5% of entity-dates have a wrong scale. K_43.00 keys contain the metric value. |
| K_49.01 | Template 9.1 - Mitigating actions: Assets for the calculation of BTAR | clean (auto) | Engine test against anchor S:K_21.02: 93% of filings in the main mode (spread 0.10). Climate and GAR. About 4.5% of entity-dates have a wrong scale. K_43.00 keys contain the metric value. |
| K_49.02 | Template 9.2 - BTAR % | no amounts | No amount cells (ratios, counts, or text). Nothing to rescale. Climate and GAR. About 4.5% of entity-dates have a wrong scale. K_43.00 keys contain the metric value. |
| K_49.03 | Template 9.3 - Summary table - BTAR % | no amounts | No amount cells (ratios, counts, or text). Nothing to rescale. Climate and GAR. About 4.5% of entity-dates have a wrong scale. K_43.00 keys contain the metric value. |
| K_50.00 | Template 10 - Other climate change mitigating actions that are not covered in the EU Taxon | clean (auto) | Engine test against anchor S:K_27.02: 83% of filings in the main mode (spread 0.20). Climate and GAR. About 4.5% of entity-dates have a wrong scale. K_43.00 keys contain the metric value. |
| K_60.00 | EU OV1 – Overview of total risk exposure amounts | clean | OV1, column T only. Tests: scale against KM1, zero total. Table clean_period_fact. |
| K_61.00 | EU KM1 - Key metrics template | clean | KM1. Tests: units, zeros, ratio units, period dates. Table clean_period_fact. |
| K_62.01 | EU INS1 - Insurance participations | clean (auto) | Engine test against anchor S:K_19.03: 82% of filings in the main mode (spread 0.32). Not assessed in detail. Unit errors are not tested. |
| K_62.02 | EU INS2 - Financial conglomerates information on own funds and capital adequacy ratio | clean (auto) | Engine test against anchor TREA: 77% of filings in the main mode (spread 0.18). Not assessed in detail. Unit errors are not tested. |
| K_63.01 | EU CMS1 – Comparison of modelled and standardised risk weighted exposure amounts at risk l | clean (auto) | Engine test against anchor TREA: 96% of filings in the main mode (spread 0.06). Not assessed in detail. Unit errors are not tested. |
| K_63.02 | EU CMS2 – Comparison of modelled and standardised risk weighted exposure amounts for credi | clean (auto) | Engine test against anchor S:K_21.02: 98% of filings in the main mode (spread 0.12). Not assessed in detail. Unit errors are not tested. |
| K_64.01 | EU LI1 - Differences between the accounting scope and the scope of prudential consolidatio | clean (auto) | Engine test against anchor S:K_21.02: 98% of filings in the main mode (spread 0.17). Row "Total assets" is tested for scale (table entity_assets). The other rows have no test. |
| K_64.02 | EU LI3 - Outline of the differences in the scopes of consolidation (entity by entity) | not clean | Not assessed in detail. Unit errors are not tested. |
| K_64.03 | EU LI2 - Main sources of differences between regulatory exposure amounts and carrying valu | clean (auto) | Engine test against anchor TA: 97% of filings in the main mode (spread 0.02). Not assessed in detail. Unit errors are not tested. |
| K_65.00 | EU PV1: Prudent valuation adjustments (PVA) | clean (auto) | Engine test against anchor S:K_12.00: 90% of filings in the main mode (spread 0.32). Not assessed in detail. Unit errors are not tested. |
| K_66.01 | EU CC1 - Composition of regulatory own funds | clean (auto) | Engine test against anchor T1: 99% of filings in the main mode (spread 0.02). Own funds (CC1). Sums fail in 2.7% to 4.7% of cells. CC1 shares the unit error of KM1 in one filing. |
| K_66.02 | EU CC2 - reconciliation of regulatory own funds to balance sheet in the audited financial  | clean (auto) | Engine test against anchor S:K_64.01: 94% of filings in the main mode (spread 0.08). Row "Total assets" is tested for scale (table entity_assets). The other rows have no test. |
| K_67.01 | EU CCyB1 - Geographical distribution of credit exposures relevant for the calculation of t | not clean | No reliable scale anchor (best anchor S:K_09.02: 79% of filings in the main mode, spread 0.41; needs at least 70% and at most 0.35). CCyB1. Open table with a blank key. About 5% of entity-filings have ratios in percentage points. |
| K_67.02 | EU CCyB2 - Amount of institution-specific countercyclical capital buffer | clean (auto) | Engine test against anchor TREA: 95% of filings in the main mode (spread 0.00). CCyB2. Ratios in percentage points in about 5% of entity-filings. |
| K_68.00 | EU IRRBB1 - Interest rate risks of non-trading book activities | clean | IRRBB1. Test: size against Tier 1. Six unit conventions are found and converted. Table clean_fact. The last-period columns have no date. |
| K_70.00 | EU LR1 - LRSum: Summary reconciliation of accounting assets and leverage ratio exposures | clean (auto) | Engine test against anchor LEV: 96% of filings in the main mode (spread 0.01). Row "Total assets" is tested for scale (table entity_assets). The other rows have no test. |
| K_71.00 | EU LR2 - LRCom: Leverage ratio common disclosure | clean (auto) | Engine test against anchor S:K_70.00: 98% of filings in the main mode (spread 0.02). LR2. Leverage ratio in percentage points for 11 banks (for example Piraeus). T-1 is the previous disclosure date. |
| K_72.00 | EU LR3 - LRSpl: Split-up of on balance sheet exposures (excluding derivatives, SFTs and ex | clean (auto) | Engine test against anchor S:K_64.03: 96% of filings in the main mode (spread 0.04). Not assessed in detail. Unit errors are not tested. |
| K_73.00 | EU LIQ1 - Quantitative information of LCR | clean (auto) | Engine test against anchor OV1_OPRISK: 96% of filings in the main mode (spread 0.17). LIQ1 and LIQ2. LCR and NSFR in percentage points for about 2%. Outflows fail the sum test in 8.4%. |
| K_74.00 | EU LIQ2: Net Stable Funding Ratio | clean (auto) | Engine test against anchor S:K_23.00: 97% of filings in the main mode (spread 0.13). LIQ1 and LIQ2. LCR and NSFR in percentage points for about 2%. Outflows fail the sum test in 8.4%. |
| K_80.00 | EU CQ1: Credit quality of forborne exposures | clean (auto) | Engine test against anchor S:K_22.01: 92% of filings in the main mode (spread 0.24). Credit quality (CQ). CQ3 equals CR1 in all tested cases. Unit errors are not tested. |
| K_81.00 | EU CQ2: Quality of forbearance | clean (auto) | Engine test against anchor S:K_80.00: 78% of filings in the main mode (spread 0.20). Credit quality (CQ). CQ3 equals CR1 in all tested cases. Unit errors are not tested. |
| K_82.00 | EU CQ3: Credit quality of performing and non-performing exposures by past due days | clean (auto) | Engine test against anchor S:K_21.01: 97% of filings in the main mode (spread 0.12). Credit quality (CQ). CQ3 equals CR1 in all tested cases. Unit errors are not tested. |
| K_83.01 | EU CQ4: Quality of non-performing exposures by geography | not downloaded | The server times out. The downloader skips this template. |
| K_84.01 | EU CQ5: Credit quality of loans and advances by industry | clean (auto) | Engine test against anchor S:K_27.01: 92% of filings in the main mode (spread 0.23). Credit quality (CQ). CQ3 equals CR1 in all tested cases. Unit errors are not tested. |
| K_85.00 | EU CQ6: Collateral valuation - loans and advances | clean (auto) | Engine test against anchor S:K_47.00: 88% of filings in the main mode (spread 0.25). Credit quality (CQ). CQ3 equals CR1 in all tested cases. Unit errors are not tested. |
| K_86.00 | EU CQ7: Collateral obtained by taking possession and execution processes | not clean | No reliable scale anchor (best anchor S:K_18.02: 53% of filings in the main mode, spread 0.19; needs at least 70% and at most 0.35). Credit quality (CQ). CQ3 equals CR1 in all tested cases. Unit errors are not tested. |
| K_87.00 | EU CQ8: Collateral obtained by taking possession and execution processes – vintage breakdo | not clean | No reliable scale anchor (best anchor S:K_95.00: 40% of filings in the main mode, spread 0.26; needs at least 70% and at most 0.35). Credit quality (CQ). CQ3 equals CR1 in all tested cases. Unit errors are not tested. |
| K_90.01 | EU KM2 - Key metrics - MREL and, where applicable, G-SII requirement for own funds and eli | clean (auto) | Engine test against anchor LEV: 97% of filings in the main mode (spread 0.03). MREL and TLAC. Ratios in percentage points (NBG, 3 of 3 filings). Not tested. |
| K_91.00 | EU TLAC1 - Composition - MREL and, where applicable, G-SII requirement for own funds and e | clean (auto) | Engine test against anchor S:K_67.02: 95% of filings in the main mode (spread 0.14). MREL and TLAC. Ratios in percentage points (NBG, 3 of 3 filings). Not tested. |
| K_93.00 | EU ILAC - Internal loss absorbing capacity: internal MREL and, where applicable, requireme | clean (auto) | Engine test against anchor S:K_71.00: 92% of filings in the main mode (spread 0.10). MREL and TLAC. Ratios in percentage points (NBG, 3 of 3 filings). Not tested. |
| K_95.00 | Creditor ranking - Entity that is not a resolution entity | clean (auto) | Engine test against anchor T1: 82% of filings in the main mode (spread 0.17). Creditor ranking. Open tables with blank keys. Rank labels change between dates. |
| K_96.00 | EU TLAC2b: Creditor ranking - Entity that is not a resolution entity | clean (auto) | Engine test against anchor T1: 82% of filings in the main mode (spread 0.09). Creditor ranking. Open tables with blank keys. Rank labels change between dates. |
| K_97.00 | EU TLAC3 - creditor ranking - resolution entity | clean (auto) | Engine test against anchor S:K_95.00: 91% of filings in the main mode (spread 0.15). Creditor ranking. Open tables with blank keys. Rank labels change between dates. |
| K_98.00 | EU TLAC3b: creditor ranking - resolution entity | clean (auto) | Engine test against anchor CET1: 99% of filings in the main mode (spread 0.06). Creditor ranking. Open tables with blank keys. Rank labels change between dates. |
| K_100.00 | Section 1 - General Information | not clean | G-SIB indicators. Three of 13 banks file in million or thousand. |
| K_101.00 | Section 2- total exposures | clean (auto) | Engine test against anchor LEV: 81% of filings in the main mode (spread 0.01). G-SIB indicators. Three of 13 banks file in million or thousand. |
| K_102.00 | Section 3 - Intra-Financial System Assets | clean (auto) | Engine test against anchor S:K_29.02: 70% of filings in the main mode (spread 0.15). G-SIB indicators. Three of 13 banks file in million or thousand. |
| K_103.00 | Section 4 - Intra-Financial System Liabilities | clean (auto) | Engine test against anchor OV1_CVA: 77% of filings in the main mode (spread 0.19). G-SIB indicators. Three of 13 banks file in million or thousand. |
| K_104.00 | Section 5 - Securities Outstanding | clean (auto) | Engine test against anchor TREA: 77% of filings in the main mode (spread 0.06). G-SIB indicators. Three of 13 banks file in million or thousand. |
| K_105.00 | Section 6 - Payments made in the reporting year excluding intragroup payments | not clean | No reliable scale anchor (best anchor S:K_19.01: 67% of filings in the main mode, spread 0.12; needs at least 70% and at most 0.35). G-SIB indicators. Three of 13 banks file in million or thousand. |
| K_106.00 | Section 7 - Assets Under Custody | not clean | No reliable scale anchor (best anchor S:K_30.01: 67% of filings in the main mode, spread 0.14; needs at least 70% and at most 0.35). G-SIB indicators. Three of 13 banks file in million or thousand. |
| K_107.00 | Section 8 - Underwritten Transactions in Debt and Equity Markets | clean (auto) | Engine test against anchor OV1_CCR: 73% of filings in the main mode (spread 0.09). G-SIB indicators. Three of 13 banks file in million or thousand. |
| K_108.00 | Section 9 - Trading Volume | clean (auto) | Engine test against anchor OV1_SEC: 75% of filings in the main mode (spread 0.19). G-SIB indicators. Three of 13 banks file in million or thousand. |
| K_109.00 | Section 10 - Notional Amount of Over-the-Counter OTC Derivatives | clean (auto) | Engine test against anchor S:K_09.05: 70% of filings in the main mode (spread 0.25). G-SIB indicators. Three of 13 banks file in million or thousand. |
| K_110.00 | Section 11 - Trading and Available-for-Sale Securities | clean (auto) | Engine test against anchor OV1_CCR: 77% of filings in the main mode (spread 0.11). G-SIB indicators. Three of 13 banks file in million or thousand. |
| K_111.00 | Section 12 - Level 3 Assets | not clean | No reliable scale anchor (best anchor S:K_82.00: 58% of filings in the main mode, spread 0.09; needs at least 70% and at most 0.35). G-SIB indicators. Three of 13 banks file in million or thousand. |
| K_112.00 | Section 13 - Cross-Jurisdictional Claims | clean (auto) | Engine test against anchor S:K_09.01: 75% of filings in the main mode (spread 0.14). G-SIB indicators. Three of 13 banks file in million or thousand. |
| K_113.00 | Section 14 - Cross-Jurisdictional Liabilities | clean (auto) | Engine test against anchor OV1_SEC: 75% of filings in the main mode (spread 0.13). G-SIB indicators. Three of 13 banks file in million or thousand. |
