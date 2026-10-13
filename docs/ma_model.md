# M&A scenario model

The page `dashboard/pages/7_MA_scenario.py` combines two banks. The default acquirer is National Bank of Greece (NBG).
You can choose any other bank in P3DH as the acquirer or the target.
The model shows the position of the combined bank on the day the deal closes.

## Data rule

Every input comes from the P3DH clean layer. The model uses no number from the draft workbook in the folder `M&A`.
The model has no market price and no profit data, because P3DH has neither. You enter the price and the costs.

The loader is `dashboard/ma_data.py`. The calculation is `dashboard/ma_model.py`.
Neither file needs Streamlit. The test is `scripts/test_ma_model.py`.

## Inputs from P3DH

| Group | Template | Rows used |
|---|---|---|
| Capital, buffers, leverage, liquidity | KM1 (K_61.00) | CET1, Tier 1, total capital, TREA, P2R, buffers, leverage exposure, HQLA, net outflows, ASF, RSF |
| Risk exposure by type | OV1 (K_60.00) | credit, CCR, CVA, securitisation, market, operational |
| Common equity, intangible assets | CC1 (K_66.01) | rows 0110, 0130, 0090 |
| Total assets, equity (fallback) | CC2 (K_66.02), LR1 (K_70.00), table `entity_assets` | total assets, total equity |
| MREL | KM2 (K_90.01) | resources, subordinated resources, TREA, TEM, requirements |
| Interest rate risk | IRRBB1 (K_68.00) | change of economic value of equity and net interest income, 6 scenarios |
| Encumbrance | AE1 (K_20.01) | encumbered and unencumbered assets |
| Asset quality | CR1 (K_21.01) | performing and non-performing loans |

Abbreviations: TREA is the total risk exposure amount. TEM is the total exposure measure.
HQLA is high-quality liquid assets. ASF and RSF are available and required stable funding.
P2R is the Pillar 2 requirement. MDA is the maximum distributable amount.

Rules for the loader:

- KM1 and OV1 values come from the quarter you choose. The target uses its newest quarter up to that date, within 12 months.
- The loader reads all cells of one template from one filing only. It never mixes cells of two filings.
- A cell with quality `quarantined` is not used.
- The model marks each input as verified or not verified. The inputs table in the page shows the result.
- KM2 ratio cells can be fractions or percentage points. The model tests the unit with own funds divided by TREA.

## Deal inputs

You choose the price basis: tangible book value, CET1 capital, or a fixed amount.
You also choose the stake (50% to 100%), the cash share, new instruments, costs, and effects of the combination.

Tangible book value of the target is `E - I`. `E` is the common equity before adjustments (CC1 row 0110). `I` is the intangible assets (CC1 row 0130).

## Formulas

Notation: `k` is the stake. `P` is the price for the stake. `C` is the cash part of `P`. `S` is the part paid in new shares, so `P = C + S`.

**Price.** `P = k x multiple x TBV` for the basis tangible book. `P = k x multiple x CET1` for the basis CET1 capital.

**Fair value and costs.** After-tax fair value write-down `F = write-down % x TBV x (1 - tax)`.
After-tax integration cost `N = integration % x TBV x (1 - tax)`. Transaction cost `X = transaction % x P`.

**Goodwill.** The purchase accounting writes off the existing intangible assets of the target (`I`) and books new goodwill.
Goodwill = `max(P - k x (TBV - F), 0)`, with `TBV = E - I`. A negative result is a gain from a bargain purchase.
A price of exactly 1.0 times tangible book therefore gives no goodwill and no gain.
CC1 does not split `I` into goodwill and other intangible assets, so the model treats all of `I` the same way.

**Pro-forma CET1.**

`CET1 = CET1(A) + CET1(T) - C + NCI(eligible) - NCI(removed) - k x F - N - X + new CET1`

The equity route gives the same result: parent equity + new shares - the other deductions of the target - new goodwill.
The result does not depend on the split between goodwill and other items.
A deal paid in shares with no cost adds the two CET1 amounts. Each euro of cash paid reduces CET1 by one euro.

**Book equity and CET1.** Tangible book value is higher than CET1. CET1 also deducts additional value adjustments, deferred tax assets,
the expected-loss shortfall, pension assets, and other regulatory adjustments. The page shows the bridge from CC1 row 6 to KM1 CET1 for both banks.
The model flags a bank where CC1 row 6 plus the total adjustments (row 28) differs from KM1 CET1 by more than 2%.
This happens for about 4% of the banks (411 tested at their latest quarter).

Minority interest applies when `k` is below 100%. `NCI(removed) = (1 - k) x TBV`.
`NCI(eligible) = (1 - k) x min(CET1(T), CET1 requirement of T x TREA(T))`. This follows the rule of Article 84 CRR in a simple form.

**Other capital.** AT1 and Tier 2 are the sum of both banks, times the recognition factor for the target, plus new instruments.
`TREA = TREA(A) x (1 + change A) + TREA(T) x (1 + change T)`.

**Requirements.** The countercyclical and systemic risk buffers are weighted by TREA.
The G-SII or O-SII buffer follows your rule (higher of the two, one bank, or own value).
P2R follows your rule (weighted by TREA, one bank, or own value).
The CET1 requirement is `4.5% + P2R (CET1 part) + combined buffer`. Tier 1 uses 6% and total capital uses 8%.

**Distance to MDA.** The model computes the headroom of each of the 3 layers in euro. The smallest headroom is the distance to MDA.
It shows the result in basis points of TREA and names the binding layer.

**Leverage.** Leverage exposure = both exposures, minus removed exposure, plus the change of cash.
Leverage ratio = Tier 1 divided by leverage exposure.

**Cash.** The change of cash = new instruments - cash paid - transaction cost - integration cost (before tax).
A negative change reduces HQLA and leverage exposure by the same amount.

**LCR.** `(HQLA(A) + HQLA(T) + change of cash) / (net outflows(A) + net outflows(T))`.
The model pools the liquidity of both banks.

**NSFR.** `ASF = ASF(A) + ASF(T) + new instruments + S - k x E`. `RSF = RSF(A) + RSF(T)`.
The term `S - k x E` replaces the equity of the target with the new equity of the group. The model gives goodwill a required stable funding factor of 0%.

**MREL.** Resources = both KM2 amounts + change of own funds + new MREL instruments.
The requirement is the TREA-weighted mix of both requirements. The combined buffer is added.
A bank with no KM2 enters with total capital as resources. A target with no requirement uses the requirement of the acquirer.

**IRRBB.** The model adds the changes of economic value of both banks in each scenario.
It divides the sum by the pro-forma Tier 1 capital. The supervisory limit is 15%.

**Encumbrance and non-performing loans.** The model adds the amounts of both banks and divides.

**Capacity.** The page shows the largest cash payment and the largest price multiple that keep the CET1 ratio at or above your floor.
CET1 falls one for one with cash, so two model runs give both limits.

**Size class.** The model adds total assets, the change of cash, and new goodwill, and removes the intangible assets of the target. It applies the same limits as the classification
(10 bn, 100 bn, and 250 bn euro).

## Limits

- The model is static. It has no earnings, no synergies over time, and no dividend.
- The model does not value the core deposit intangible. This item does not change CET1 in this method.
- Deferred tax assets and deferred tax liabilities of the deal are not modelled.
- The supervisor sets the real P2R, buffers, and MREL requirement of the combined group. The model uses a mix.
- Liquidity can be trapped in a subsidiary. The model pools it.
- KM1 amounts of two banks can come from two different quarters. The page shows a note in this case.
- AE1 and CC1 are annual for many banks. The page names each input that comes from an older filing.
- Foreign targets: P3DH converts amounts to euro at the exchange rate of the filing date.

## Test

`scripts/test_ma_model.py` tests the formulas with made-up banks (share deal, cash deal, bargain purchase, minority interest,
funding, capacity limits). It then runs NBG with 6 real targets on the database.

```
.venv/Scripts/python scripts/test_ma_model.py
```
