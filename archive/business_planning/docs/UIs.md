# BBIRR UI Flow — Executive Perspective

## 1. Entry Point: Base Year Ready

You arrive after Base Year Validation is complete. The system has a fully populated Year 0 with estimated items flagged and accepted.

Primary goals:
- See the bank's current position quickly
- Decide what to change in the plan
- Run base and stress scenarios
- Review bridges and key drivers

## 2. Main Dashboard (Landing View)

Top strip (always visible):
- CET1 (fully loaded) + headroom vs MDA
- RWA and floor add-on
- ROE and ROTE
- NIM and NII
- NPL/NPE ratio and CoR
- LCR / NSFR
- Indicative rating notch + direction
- RAF limits status (green/amber/red)

Primary charts (first screen):
- Capital trajectory (CET1 ratio vs requirements)
- P&L trajectory (NII, provisions, net income)
- Segment NII view (stacked area by segment, drillable)
- NII-at-Risk across IRRBB shocks
- Peer percentile position (CET1, NPL, ROE, NIM)

Quick actions:
- "Edit Plan"
- "Run Stress"
- "Add Scenario"
- "View Bridges"

Drill-down patterns:
- Clicking any KPI opens a side drawer with the bridge for that metric
- Clicking any chart opens a detail view with quarter-by-quarter data and scenario comparisons
- Clicking any RAF limit opens a breach driver analysis

## 3. Plan Builder (Primary Input Workspace)

Left panel: inputs (grouped)
- Portfolio growth and mix by segment
- Pricing and margin targets
- Funding strategy and mix
- Rate environment (base curve + forward path)
- Deposit pass-through (beta, lag, floor) by product
- FTP curves by segment and tenor (base + liquidity premium)
- Capital actions (issuance, buyback, dividend policy)
- Recovery options editor (capital and liquidity actions, timing, constraints)
- NII target optimizer (goal-seek)
- Hedging instruments (IRS)

Right panel: live preview
- Mini P&L, balance sheet, capital snapshot
- RAF limits flags updated on recalculation

Bottom panels:
- Assumption Audit Panel (macro implied vs input)
- Bridges panel: CET1, NII, ROE, RWA (quarterly + cumulative)
- Sensitivity table (collapsed by default)

Interaction rules:
- Inputs are debounced (500ms) for fast re-run
- IRRBB and rating refresh on explicit "Refresh" button
- Undo/redo preserves last 20 changes

NII Target Optimizer flow:
- Input: target NII growth (YoY %) or absolute NII level
- Constraints: CET1/LCR/NSFR floors, RAF limits, max change per lever, balance-sheet growth cap, pricing guardrails by segment (bps bands)
- Levers: pricing, mix, funding, hedging, pass-through assumptions
- Output: recommended lever changes + feasibility status + trade-off summary
- Ranked alternatives (top 3) with constraint slack and driver attribution
- Sensitivity bands for NII target (p10/p50/p90) based on elasticity uncertainty

## 4. Bridges (Drill-Down Views)

CET1 Bridge:
- Net income, dividends/buybacks, CET1 issuance
- Prudential deductions (by category)
- RWA floor add-on impact

NII Bridge:
- Volume, mix, base rate move
- Deposit pass-through change
- Funding spread change
- Hedge impact
- Credit migration (Stage 2/3) impact
 - Segment drill-down: corporate, mortgage, consumer, SME, public sector

ROE Bridge:
- NII, fees, trading, opex
- Provisions, tax, capital actions

RWA Bridge:
- Credit SA/IRB, CCR/CVA, market, operational
- Volume vs risk-weight vs PD/LGD shifts
- Output floor add-on

## 5. Scenario Management

Scenario library view:
- Base case (default)
- EBA baseline / adverse / severe
- Custom scenarios (user created)

Add/edit scenario flow:
1) Select scenario type (EBA preset or Custom)
2) Set macro paths (GDP, unemployment, HPI, spreads, rate curve)
3) Override transmission elasticities (optional)
4) Funding curve stress overlay (spreads, pass-through beta shifts)
5) Save scenario and run

Reverse stress flow:
- Select target metric and floor (e.g., CET1 >= 10.5%)
- Choose shock dimension(s) (GDP only or GDP + rate)
- Solve and review breach point

## 6. Stress Testing View

Top controls:
- Scenario selector and comparison mode
- Recovery options overlay toggle
- Consistency warnings panel

Main outputs:
- CET1 and RWA trajectories
- NII and ROE trajectories
- Liquidity survival horizon
- Rating notch change

Side panels:
- Driver breakdown for CET1 and NII
- RAF breach status per scenario

## 7. Historical Analysis

Counterfactual tab:
- Hedge input form
- NII/EVE charts vs actual
- Cumulative benefit summary

Historical bridges tab:
- NII, CET1, RWA bridges over historical periods
- Replay rate paths and pass-through impacts

## 8. Reporting

Report builder:
- Select scenarios
- Include bridges and RAF limits
- Include ICAAP/ILAAP draft pack

Outputs:
- PDF (reportlab/WeasyPrint)
- Excel workbook
