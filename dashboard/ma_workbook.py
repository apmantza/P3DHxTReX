"""The M&A workbook: one set of formulas for the Excel file and for the Streamlit page.

build_workbook() writes the formulas into an openpyxl workbook. The page evaluates the same formulas with
ma_sheet.Model. Sheet Calc keeps the layout of docs/M&A calc.xlsx (rows 1 to 58 have the same cells).
New blocks start at row 59. Inputs come from P3DH (sheet P3DH) and from the Bloomberg tables of the P3DH database (sheets Market and Peers).
Profit, opex, tax rate, and valuation of every bank come from P3DH or Bloomberg. Only the deal terms (cash, stake, premium) are inputs.
This module does not use Streamlit.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

import ma_data
import ma_market
import ma_sheet

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "docs" / "M&A calc.xlsx"
NBG_KEY = "5UMCZOEYKCVFAW8ZLO05"

BANK_COLS = ["D", "E", "F", "G"]
TGT = ["E", "F", "G"]
COMBO = {"E": "H", "F": "I", "G": "J"}
TOF = {v: k for k, v in COMBO.items()}
ALL = ["D", "E", "F", "G", "H", "I", "J", "K"]
COMBOS = ["H", "I", "J"]

# Deal terms of the user workbook. They are levers, not data. Keys are LEIs. Other banks get a cash share of 50%, a stake of 100%, and no premium.
DEAL_DEFAULTS: dict[str, dict[str, Any]] = {
    "9CZ7TVMR36CYD5TZBS50": dict(short="BIL", premium=0.0, cash=0.9, stake=0.9),  # the State of Luxembourg holds 10% and does not sell
    "635400L14KNHZXPUZM19": dict(short="BOC", premium=0.15, cash=0.5, stake=1.0),
    "TUKDD90GPC79G1KOE162": dict(short="HCOB", premium=0.0, cash=1.0, stake=0.9),
}

# Sheet Market: one column for each bank (B = NBG, C to E = the three targets). Amounts in EUR million as Bloomberg gives them.
MCOLS = ["B", "C", "D", "E"]
MROW = dict(lei=4, name=5, basis=6, ticker=7, parent=8, ccy=9, price=10, shares=11, mcap=12, bvps=13, tbvps=14, ptbv=15, eps_ttm=16, ni_fy=17, ni_ltm=18,
            ni_base=19, revenue=20, opex=21, equity=22, tax_stat=23, tax_eff=24, tax=25, rating_sp=26, rating_moodys=27, debt_out=28, bonds_n=29, record_end=30)
CONS_ORDER = ["NI", "EPS", "DPS", "SALES", "OPP"]
CONS_LABEL = {"NI": "Net income (EUR m)", "EPS": "EPS (currency of the stock)", "DPS": "DPS (currency of the stock)", "SALES": "Revenue (EUR m)",
              "OPP": "Operating profit (EUR m)"}
CONS_TOP = 34  # first consensus row: 4 rows (2026E to 2029E) for each metric
USED_TOP = 56  # rows 56 to 59: net income used for each year. Row 60: full consensus (1 = yes)
FULL_ROW = 60
MKT_DFR_ROW = 87  # expected average deposit rate of each calendar year, columns B to E (2026E to 2029E)
PEER_TOP = 10  # first peer row on sheet Peers
PEER_BLOCK = ["H", "L", "P"]  # first helper column of each target on sheet Peers (4 columns each)


def peer_cols(t: int) -> dict[str, str]:
    """Columns of target t (0 to 2) on sheet Peers: distance and included multiple, on tangible equity (tbv) and on CET1 (cet1)."""
    base = openpyxl.utils.column_index_from_string(PEER_BLOCK[t])
    L = get_column_letter
    return {"d_tbv": L(base), "m_tbv": L(base + 1), "d_cet1": L(base + 2), "m_cet1": L(base + 3)}


def cons_row(metric: str, k: int) -> int:
    return CONS_TOP + 4 * CONS_ORDER.index(metric) + k


# Items of sheet P3DH: key, label, kind (bn, frac, text).
P3DH_ITEMS: list[tuple[str, str, str]] = [
    ("total_assets", "Total assets", "bn"),
    ("trea", "Total risk exposure amount (KM1 row 4)", "bn"),
    ("cet1", "CET1 capital (KM1 row 1)", "bn"),
    ("t1", "Tier 1 capital (KM1 row 2)", "bn"),
    ("tc", "Total capital (KM1 row 3)", "bn"),
    ("p2r", "Pillar 2 requirement, total (KM1 row 7d)", "frac"),
    ("p2r_cet1", "Pillar 2 requirement, CET1 part (KM1 row 7e)", "frac"),
    ("p2r_t1", "Pillar 2 requirement, Tier 1 part (KM1 row 7f)", "frac"),
    ("ccb", "Capital conservation buffer (KM1 row 8)", "frac"),
    ("ccyb", "Countercyclical buffer (KM1 row 9)", "frac"),
    ("syrb", "Systemic risk buffer (KM1 row 9a)", "frac"),
    ("gsii", "G-SII buffer (KM1 row 10)", "frac"),
    ("osii", "O-SII buffer (KM1 row 10a)", "frac"),
    ("cbr", "Combined buffer requirement (KM1 row 11)", "frac"),
    ("lev_exp", "Leverage ratio exposure measure (KM1 row 13)", "bn"),
    ("lev_req", "Overall leverage ratio requirement (KM1 row 14e)", "frac"),
    ("hqla", "HQLA (KM1 row 15)", "bn"),
    ("net_outflow", "Net cash outflows (KM1 row 16)", "bn"),
    ("asf", "Available stable funding (KM1 row 18)", "bn"),
    ("rsf", "Required stable funding (KM1 row 19)", "bn"),
    ("cc1_cet1_before_adj", "Common equity before adjustments (CC1 row 6)", "bn"),
    ("cc1_intangibles", "Intangible assets, positive (CC1 row 8)", "bn"),
    ("cc1_total_adj", "Total CET1 adjustments, positive (CC1 row 28)", "bn"),
    ("km2_ofel", "Own funds and eligible liabilities (KM2 row 1)", "bn"),
    ("km2_ofel_sub", "of which own funds and subordinated (KM2 row 1a)", "bn"),
    ("km2_trea", "TREA of the resolution group (KM2 row 2)", "bn"),
    ("km2_req_trea", "MREL requirement, % of TREA (KM2 row EU-7)", "frac"),
    ("km2_req_tem", "MREL requirement, % of TEM (KM2 row EU-9)", "frac"),
    ("ae_encumbered", "Encumbered assets (AE1)", "bn"),
    ("ae_unencumbered", "Unencumbered assets (AE1)", "bn"),
    ("cr1_loans_npl", "Non-performing loans and advances (CR1)", "bn"),
    ("cr1_loans_performing", "Performing loans and advances (CR1)", "bn"),
    ("country", "Country", "text"),
    ("dta_total", "Deferred tax assets, total (CC2)", "bn"),
    ("dta_nonreliant", "of which DTCs: do not rely on future profitability (CC2)", "bn"),
    ("cc1_dta_below", "DTAs below the deduction threshold, 250% RW (CC1 row 75)", "bn"),
    ("cc1_dta_deducted", "DTAs deducted from CET1, positive (CC1 rows 10 and 21)", "bn"),
    ("km2_req_trea_sub", "MREL subordination requirement, % of TREA (KM2 row EU-8)", "frac"),
    ("rwa_credit", "RWEA credit risk (OV1)", "bn"),
    ("rwa_ccr", "RWEA counterparty credit risk (OV1)", "bn"),
    ("rwa_cva", "RWEA CVA (OV1)", "bn"),
    ("rwa_securitisation", "RWEA securitisation (OV1)", "bn"),
    ("rwa_market", "RWEA market risk (OV1)", "bn"),
    ("rwa_operational", "RWEA operational risk (OV1)", "bn"),
] + [(f"irrbb_{c}", f"IRRBB1: change of EVE, {n}", "bn") for c, n in ma_data.IRRBB_ROWS.items()]

BLUE, GREEN = Font(color="0000FF"), Font(color="006100")
BOLD = Font(bold=True)
HEAD = PatternFill("solid", fgColor="1F3864")
HEAD_FONT = Font(bold=True, color="FFFFFF")
SECTION = PatternFill("solid", fgColor="D9E1F2")
INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")
NEW_FILL = PatternFill("solid", fgColor="E2EFDA")
FORMATS = {"pct": "0.0%", "pct2": "0.00%", "bn": "0.00", "x": '0.00"x"', "bp": "0", "int": "0", "eps": "0.00", "text": "@", "flag": "0"}


# --------------------------------------------------------------------------------------------- data

def load_market(query, banks: list[ma_data.BankData]) -> dict:
    """Bloomberg data from the database for NBG and the three targets (banks[0] is NBG)."""
    return ma_market.load(query, [ma_market.lei_of(query, b.key) for b in banks])


def item_value(bank: ma_data.BankData, key: str, kind: str):
    if kind == "text":
        return bank.country, bank.as_of, "ok"
    if key.startswith("irrbb_"):
        it = bank.irrbb_eve.get(key.split("_", 1)[1])
    elif key == "cc1_dta_deducted":
        a, b = bank.item("cc1_dta_deducted"), bank.item("cc1_dta_temporary")
        if a.value is None and b.value is None:
            return None, None, "missing"
        return (abs(a.value or 0) + abs(b.value or 0)) / 1e9, a.period or b.period, a.quality
    elif key == "total_assets":
        it = bank.item("total_assets")
        if it.value is None:
            it = bank.item("cc2_total_assets")
        if it.value is None:
            it = bank.item("lr1_total_assets")
    else:
        it = bank.item(key)
    if it is None or it.value is None:
        return None, None, "missing"
    v = it.value
    if key in ("cc1_intangibles", "cc1_total_adj"):
        v = abs(v)
    return (v / 1e9 if kind == "bn" else v), it.period, it.quality


def p3dh_rows() -> dict[str, int]:
    return {key: 5 + i for i, (key, _, _) in enumerate(P3DH_ITEMS)}


def default_deal(bank: ma_data.BankData, lei: str) -> dict[str, Any]:
    """Deal terms of a target. They are levers. Data (profit, opex, tax, valuation) is not here: it comes from sheets P3DH, Market, and Peers."""
    d = DEAL_DEFAULTS.get(lei, {})
    return dict(short=d.get("short") or bank.name.split()[0][:12], premium=d.get("premium", 0.0), cash=d.get("cash", 0.5), stake=d.get("stake", 1.0),
                txn=0.0, fv=0.0, rwa=0.0, new_cet1=0.0, new_at1=0.0, new_t2=0.0, new_snp=0.0, new_sp=0.0)


def default_globals() -> dict[str, Any]:
    return dict(cet1_target=0.13, mrel_target=0.29, year=2, pe=14.0, integ_pct=0.20, integ_years=5, excess_value=1.0, dividend_waiver=0.8, rwa_nbg=0.0, peers_k=20, peers_basis=3, target_instruments=1.0, sub_req=0.135, sub_assets=100, sub_tem=0.05)


# ---------------------------------------------------------------------------------------- workbook

class Builder:
    def __init__(self, wb: openpyxl.Workbook):
        self.wb = wb
        self.rows = p3dh_rows()

    def p(self, key: str, col: str, absolute: bool = False) -> str:
        c = f"${col}" if absolute else col
        return f"P3DH!{c}{self.rows[key]}"


def ctx(c: str) -> dict[str, str]:
    if c in TGT:
        return {"c": c, "t": c, "x": COMBO[c]}
    if c in TOF:
        return {"c": c, "t": TOF[c], "x": c}
    return {"c": c, "t": c, "x": c}


def style_cell(cell, kind: str | None, font=None, fill=None) -> None:
    if kind:
        cell.number_format = FORMATS.get(kind, kind)
    if font:
        cell.font = font
    if fill:
        cell.fill = fill


def write_p3dh(ws, banks: list[ma_data.BankData], rows: dict[str, int]) -> None:
    ws["A1"] = "Data from the EBA Pillar 3 Data Hub (clean layer). Amounts in EUR bn. Ratios as fractions."
    ws["A1"].font = BOLD
    heads = ["Item", "Description", "Kind"] + [f"Value: {b.name[:22]}" for b in banks] + [f"Period {i + 1}" for i in range(4)] + [f"Quality {i + 1}" for i in range(4)]
    ws["A2"], ws["B2"], ws["C2"] = "Bank", "Name", ""
    ws["A3"], ws["B3"] = "As of", "Reference quarter of each bank"
    ws["A4"] = "Item"
    for i, b in enumerate(banks):
        col = get_column_letter(4 + i)
        ws[f"{col}2"] = b.name
        ws[f"{col}3"] = b.as_of
        ws[f"{col}4"] = "value"
        ws[f"{get_column_letter(8 + i)}4"] = "period"
        ws[f"{get_column_letter(12 + i)}4"] = "quality"
        ws[f"{get_column_letter(8 + i)}2"] = b.name
        ws[f"{get_column_letter(12 + i)}2"] = b.name
    for cell in ws[4]:
        cell.font, cell.fill = HEAD_FONT, HEAD
    for key, label, kind in P3DH_ITEMS:
        r = rows[key]
        ws[f"A{r}"], ws[f"B{r}"], ws[f"C{r}"] = key, label, kind
        for i, b in enumerate(banks):
            v, period, quality = item_value(b, key, kind)
            vc = ws.cell(row=r, column=4 + i, value=v)
            if kind in ("bn", "frac"):
                vc.number_format = "0.0000" if kind == "frac" else "0.000"
            ws.cell(row=r, column=8 + i, value=period)
            ws.cell(row=r, column=12 + i, value=quality)
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 24, 52
    for col in "DEFG":
        ws.column_dimensions[col].width = 22
    ws.freeze_panes = "D5"


OIS_LABELS = ma_market.OIS_LABELS


def write_market(ws, market: dict) -> None:
    slots, rates, pulled = market["slots"], market["rates"], market["pulled"]
    pct = "0.000%"
    ws["A1"] = "Bloomberg data from the tables bbg_* of the P3DH database. Amounts in EUR million. Do not publish this sheet."
    ws["A1"].font = BOLD
    ws["A2"], ws["B2"] = "Pulled at", "; ".join(f"{k} {v[:10]}" for k, v in sorted(pulled.items()))
    ws["A3"] = "Item"
    for j, (col, sl) in enumerate(zip(MCOLS, slots)):
        ws[f"{col}3"] = "NBG" if j == 0 else f"Target {j}"
    for cell in ws[3]:
        cell.font, cell.fill = HEAD_FONT, HEAD
    items = [
        ("lei", "LEI (the link to P3DH)", lambda s_: s_["lei"], None), ("name", "Bloomberg name", lambda s_: s_.get("name"), None),
        ("basis", "Market basis: self = own listed shares, parent or none = no market cap", lambda s_: s_["basis"], None),
        ("ticker", "Ticker of the listed shares", lambda s_: s_.get("ticker"), None),
        ("parent", "Ultimate parent (information)", lambda s_: s_.get("parent_name"), None),
        ("ccy", "Currency of the stock", lambda s_: s_.get("ccy"), None), ("price", "Share price", lambda s_: s_.get("price"), "0.00"),
        ("shares", "Shares outstanding (million)", lambda s_: s_.get("shares"), "0.0"), ("mcap", "Market cap (EUR m)", lambda s_: s_.get("mcap"), "#,##0"),
        ("bvps", "Book value per share", lambda s_: s_.get("bvps"), "0.00"), ("tbvps", "Tangible book value per share", lambda s_: s_.get("tbvps"), "0.00"),
        ("ptbv", "P/TBV (price / tangible book value per share)", None, '0.00"x"'), ("eps_ttm", "EPS, last 12 months", lambda s_: s_.get("eps_ttm"), "0.00"),
        ("ni_fy", "Net income, last fiscal year (EUR m)", lambda s_: s_.get("ni_fy"), "#,##0"),
        ("ni_ltm", "Net income, last 12 months (EUR m)", lambda s_: s_.get("ni_ltm"), "#,##0"),
        ("ni_base", "Net income without consensus: last 12 months, else last fiscal year (EUR m)", None, "#,##0"),
        ("revenue", "Revenue, last fiscal year (EUR m)", lambda s_: s_.get("revenue"), "#,##0"),
        ("opex", "Operating expenses, last fiscal year (EUR m)", lambda s_: s_.get("opex"), "#,##0"),
        ("equity", "Common equity, last fiscal year (EUR m)", lambda s_: s_.get("equity"), "#,##0"),
        ("tax_stat", "Statutory tax rate", lambda s_: s_.get("tax_stat"), "0.0%"), ("tax_eff", "Effective tax rate (information)", lambda s_: s_.get("tax_eff"), "0.0%"),
        ("tax", "Tax rate used (statutory, else effective)", None, "0.0%"),
        ("rating_sp", "Rating S&P (information)", lambda s_: s_.get("rating_sp"), None), ("rating_moodys", "Rating Moody's (information)", lambda s_: s_.get("rating_moodys"), None),
        ("debt_out", "Bonds and loans outstanding (EUR m, information)", lambda s_: s_.get("debt_out"), "#,##0"),
        ("bonds_n", "Number of bond and loan issues (information)", lambda s_: s_.get("bonds_n"), "0"),
        ("record_end", "Latest period in the Bloomberg record (information)", lambda s_: s_.get("record_end"), None),
    ]
    for key, label, getter, fmt_ in items:
        r = MROW[key]
        ws[f"A{r}"] = label
        for col, sl in zip(MCOLS, slots):
            if getter:
                cell = ws[f"{col}{r}"]
                cell.value = getter(sl)
            elif key == "ptbv":
                cell = ws[f"{col}{r}"]
                cell.value = f"=IF(AND({col}{MROW['price']}>0,{col}{MROW['tbvps']}>0),{col}{MROW['price']}/{col}{MROW['tbvps']},0)"
            elif key == "ni_base":
                cell = ws[f"{col}{r}"]
                cell.value = f"=IF({col}{MROW['ni_ltm']}<>0,{col}{MROW['ni_ltm']},{col}{MROW['ni_fy']})"
            else:
                cell = ws[f"{col}{r}"]
                cell.value = f"=IF({col}{MROW['tax_stat']}>0,{col}{MROW['tax_stat']},{col}{MROW['tax_eff']})"
            if fmt_:
                cell.number_format = fmt_

    ws["A32"] = "Consensus (Bloomberg BEST), by fiscal year that ends in the calendar year"
    ws["A32"].font = BOLD
    for m_ in CONS_ORDER:
        for k, y in enumerate(YEARS):
            r = cons_row(m_, k)
            ws[f"A{r}"] = f"{CONS_LABEL[m_]}, {y}"
            for col, sl in zip(MCOLS, slots):
                ws[f"{col}{r}"] = sl["cons"].get(2026 + k, {}).get(m_)
                ws[f"{col}{r}"].number_format = "0.00" if m_ in ("EPS", "DPS") else "#,##0"
    ws["A55"] = "Net income used by the model (EUR m): consensus of the year, else the value of the year before. Year 1 without consensus: last 12 months."
    ws["A55"].font = BOLD
    for k, y in enumerate(YEARS):
        r = USED_TOP + k
        ws[f"A{r}"] = f"Net income used, {y}"
        for col in MCOLS:
            ni = f"{col}{cons_row('NI', k)}"
            ws[f"{col}{r}"] = f"=IF({ni}<>0,{ni},{col}{MROW['ni_base']})" if k == 0 else f"=IF({ni}<>0,{ni},{col}{r - 1})"
            ws[f"{col}{r}"].number_format = "#,##0"
    ws[f"A{FULL_ROW}"] = "Consensus for revenue, operating profit, and net income in 2026E (1 = yes)"
    for col in MCOLS:
        ws[f"{col}{FULL_ROW}"] = f"=IF(AND({col}{cons_row('NI', 0)}<>0,{col}{cons_row('SALES', 0)}<>0,{col}{cons_row('OPP', 0)}<>0),1,0)"

    ws["A62"] = "Rates"
    ws["A62"].font = BOLD
    ws["A63"], ws["B63"] = "ECB deposit facility rate, today", rates["today"].get("ECB_DFR")
    ws["A64"], ws["B64"] = "EUR short-term rate (ESTR), last fixing", rates["today"].get("ESTR")
    ws["A65"], ws["B65"] = "Spread of the deposit rate to ESTR", "=B63-B64"
    ws["A66"] = "ESTR OIS swap rates"
    ws["A66"].font = BOLD
    for k, label in enumerate(OIS_LABELS):
        ws[f"A{67 + k}"] = f"ESTR OIS, {label}"
        ws[f"B{67 + k}"] = rates["ois"].get(label)
    for r in range(63, 84):
        ws[f"B{r}"].number_format = pct
    ws["A85"] = "Expected average deposit rate of each calendar year"
    ws["A85"].font = BOLD
    ws["A86"] = "Calendar year"
    for k, y in enumerate(YEARS):
        ws.cell(row=86, column=2 + k, value=y).font = BOLD
        c = ws.cell(row=MKT_DFR_ROW, column=2 + k, value=rates["by_year"].get(2026 + k))
        c.number_format = "0.00%"
    ws[f"A{MKT_DFR_ROW}"] = "Average deposit rate"
    ws["A88"] = "A year that is over has its realised average. The current year has the realised path to the pull date, then the OIS forward rate plus the spread. Later years: OIS forward rate plus the spread."
    ws["A90"] = "Average deposit rate by period"
    ws["A90"].font = BOLD
    for j, h in enumerate(["Period", "Average", "Basis", "From", "To"]):
        c = ws.cell(row=91, column=1 + j, value=h)
        c.font, c.fill = HEAD_FONT, HEAD
    r = 92
    for per in rates["periods"]:
        ws[f"A{r}"], ws[f"B{r}"], ws[f"C{r}"], ws[f"D{r}"], ws[f"E{r}"] = per["label"], per["avg"], per["status"], per["start"], per["end"]
        ws[f"B{r}"].number_format = "0.00%"
        r += 1
    r += 1
    ws[f"A{r}"] = "Changes of the deposit rate since 1 January 2024"
    ws[f"A{r}"].font = BOLD
    for d, v in rates["history"]:
        r += 1
        ws[f"A{r}"], ws[f"B{r}"] = d, v
        ws[f"B{r}"].number_format = "0.00%"
    ws.column_dimensions["A"].width = 78
    for col in MCOLS:
        ws.column_dimensions[col].width = 26


def write_peers(ws, market: dict) -> None:
    rows = market["peers"]["rows"]
    first, last = PEER_TOP, PEER_TOP + len(rows) - 1
    rng = lambda col: f"{col}{first}:{col}{last}"  # noqa: E731
    ws["A1"] = "Peers for a bank without a market cap. Median multiple of the k listed banks with the closest return. Do not publish this sheet."
    ws["A1"].font = BOLD
    ws["A2"] = ("Listed European banks of P3DH. P/TBV = price / tangible book value per share. RoTE = EPS of the last 12 months / tangible book value per share. "
                "P/CET1 = market cap in EUR / CET1 of P3DH. RoCET1 = EPS x shares / CET1. A bank outside P/TBV 0.15x to 6x, P/CET1 0.2x to 6x, or a return of -10% to 60% is left out.")
    ws["A3"], ws["B3"] = "Nearest peers used (k), input N17 of Calc", "=Calc!$N$17"
    ws["A4"], ws["A5"], ws["A6"], ws["A7"], ws["A8"] = ("Target", "Return of the target: RoTE (distance to P/TBV peers) and RoCET1 (distance to P/CET1 peers)", "Distance of the k-th nearest peer",
                                                          "Median multiple of the k nearest peers: P/TBV and P/CET1", "Peers counted")
    for t, c in enumerate(TGT):
        pc = peer_cols(t)
        ws[f"{pc['d_tbv']}4"] = f"=Calc!{c}6"
        ws[f"{pc['d_tbv']}4"].font = BOLD
        ws[f"{pc['d_tbv']}5"], ws[f"{pc['d_cet1']}5"] = f"=Calc!{c}161", f"=Calc!{c}162"
        ws[f"{pc['d_tbv']}6"], ws[f"{pc['d_cet1']}6"] = f"=SMALL({rng(pc['d_tbv'])},$B$3)", f"=SMALL({rng(pc['d_cet1'])},$B$3)"
        ws[f"{pc['m_tbv']}7"], ws[f"{pc['m_cet1']}7"] = f"=MEDIAN({rng(pc['m_tbv'])})", f"=MEDIAN({rng(pc['m_cet1'])})"
        ws[f"{pc['m_tbv']}8"], ws[f"{pc['m_cet1']}8"] = f"=COUNT({rng(pc['m_tbv'])})", f"=COUNT({rng(pc['m_cet1'])})"
        for col in (pc["d_tbv"], pc["d_cet1"]):
            ws[f"{col}5"].number_format = ws[f"{col}6"].number_format = "0.0%"
        for col in (pc["m_tbv"], pc["m_cet1"]):
            ws[f"{col}7"].number_format = '0.00"x"'
            ws[f"{col}7"].font = BOLD
        for col, h in zip(pc.values(), ("Distance RoTE", "P/TBV if near", "Distance RoCET1", "P/CET1 if near")):
            c_ = ws[f"{col}{PEER_TOP - 1}"]
            c_.value, c_.font, c_.fill = h, HEAD_FONT, HEAD
    ws["U3"], ws["U4"], ws["U5"], ws["U6"], ws["U7"] = "Linear fit of P/TBV on RoTE (information only)", "Slope", "Intercept", "R squared", "Number of peers"
    ws["U3"].font = BOLD
    ws["V4"], ws["V5"], ws["V6"], ws["V7"] = f"=SLOPE({rng('D')},{rng('E')})", f"=INTERCEPT({rng('D')},{rng('E')})", f"=RSQ({rng('D')},{rng('E')})", f"=COUNT({rng('D')})"
    for r in (4, 5, 6):
        ws[f"V{r}"].number_format = "0.000"
    for j, h in enumerate(["Bank", "Country", "Ticker", "P/TBV", "RoTE", "P/CET1", "RoCET1"]):
        c = ws.cell(row=PEER_TOP - 1, column=1 + j, value=h)
        c.font, c.fill = HEAD_FONT, HEAD
    for i, p_ in enumerate(rows):
        r = PEER_TOP + i
        ws[f"A{r}"], ws[f"B{r}"], ws[f"C{r}"] = p_["name"], p_["country"], p_["ticker"]
        ws[f"D{r}"], ws[f"E{r}"], ws[f"F{r}"], ws[f"G{r}"] = p_["ptbv"], p_["rote"], p_["pcet1"], p_["rocet1"]
        ws[f"D{r}"].number_format, ws[f"E{r}"].number_format = '0.00"x"', "0.0%"
        ws[f"F{r}"].number_format, ws[f"G{r}"].number_format = '0.00"x"', "0.0%"
        for t in range(3):
            pc = peer_cols(t)
            ws[f"{pc['d_tbv']}{r}"] = f"=ABS($E{r}-{pc['d_tbv']}$5)"
            ws[f"{pc['m_tbv']}{r}"] = f'=IF({pc["d_tbv"]}{r}<={pc["d_tbv"]}$6,$D{r},"")'
            ws[f"{pc['d_cet1']}{r}"] = f"=ABS($G{r}-{pc['d_cet1']}$5)"
            ws[f"{pc['m_cet1']}{r}"] = f'=IF({pc["d_cet1"]}{r}<={pc["d_cet1"]}$6,$F{r},"")'
            for col in (pc["d_tbv"], pc["d_cet1"]):
                ws[f"{col}{r}"].number_format = "0.0%"
            for col in (pc["m_tbv"], pc["m_cet1"]):
                ws[f"{col}{r}"].number_format = '0.00"x"'
    ws.column_dimensions["A"].width = 44
    for j in range(2, 23):
        ws.column_dimensions[get_column_letter(j)].width = 14
    ws.column_dimensions["U"].width = 40


def write_calc(ws, b: Builder, banks: list[ma_data.BankData], deals: list[dict], g: dict) -> None:
    """Sheet Calc. banks[0] is NBG. deals[i] is the deal input of banks[i + 1]."""
    P = b.p

    def put(cell: str, value, kind: str | None = None, role: str | None = None) -> None:
        ws[cell] = value
        c = ws[cell]
        if kind:
            c.number_format = FORMATS.get(kind, kind)
        if role == "input":
            c.font, c.fill = BLUE, INPUT_FILL
        elif role == "link":
            c.font = GREEN

    def fill(row: int, cols: list[str], tmpl: str, kind: str | None = None, role: str | None = None) -> None:
        for c in cols:
            put(f"{c}{row}", tmpl.format(**ctx(c)), kind, role)

    def label(row: int, text: str, new: bool = False) -> None:
        ws[f"C{row}"] = text
        if new:
            ws[f"C{row}"].fill = NEW_FILL

    # ---- inputs
    label(1, "CET1 TARGET"); put("D1", g["cet1_target"], "pct", "input")
    label(2, "MREL TARGET"); put("D2", g["mrel_target"], "pct", "input")
    label(3, "DFR (expected average of the analysis year, N15)")
    put("D3", "=CHOOSE($N$15," + ",".join(f"Market!{c}{MKT_DFR_ROW}" for c in MKT_YC) + ")", "pct2", "link")
    label(4, "Pillar 2R (NBG)"); put("D4", f"={P('p2r', 'D')}", "pct2", "link")
    put("H1", "Purchase split"); ws["H1"].font = BOLD
    put("F2", "Cash"); put("F3", "Shares"); put("F4", "Profit consol (stake)")
    for c, d in zip(COMBOS, deals):
        put(f"{c}2", d["cash"], "pct", "input")
        put(f"{c}3", f"=1-{c}2", "pct")
        put(f"{c}4", d["stake"], "pct", "input")
    # additional assumptions
    put("M1", "Additional assumptions (new)"); ws["M1"].font = BOLD
    extra = [
        (2, "Tax rate NBG", f"=Market!B{MROW['tax']}", "pct", "Statutory tax rate of NBG (Bloomberg)"),
        (3, "P/E for the market cap method (x)", g["pe"], '0.0"x"', "Original used 14 inside the formula"),
        (4, "Integration cost, % of target opex", g["integ_pct"], "pct", "Original: 20%"),
        (5, "Integration cost, spread over (years)", g["integ_years"], "0", "Original: 5 years"),
        (6, "Value of excess CET1 in market cap (x)", g["excess_value"], "0.0", "1 = at book value. 0 = original method (no value)"),
        (7, "Pillar 1 total capital requirement", 0.08, "pct", "CRR Article 92"),
        (8, "Pillar 1 AT1 minimum", 0.015, "pct", "CRR Article 92 and 104a"),
        (9, "Pillar 1 Tier 2 minimum", 0.02, "pct", "CRR Article 92 and 104a"),
        (10, "P2R met with CET1", 0.5625, "pct2", "CRR Article 104a"),
        (11, "P2R met with AT1", 0.1875, "pct2", "CRR Article 104a (Tier 1 = 75%)"),
        (12, "P2R met with Tier 2", 0.25, "pct2", "CRR Article 104a"),
        (13, "Pillar 1 CET1 minimum", 0.045, "pct", "CRR Article 92"),
        (14, "Pillar 1 Tier 1 minimum", 0.06, "pct", "CRR Article 92"),
        (15, "Year of the analysis (1 = 2026E ... 4 = 2029E)", g["year"], "0", "Sets the profit (consensus) and the deposit rate"),
        (16, "Add DTAs relying on future profitability to CET1 (1 = yes)", 0, "0", "Original lever in rows 28 and 29. Default 0: P3DH shows they are in CET1 already"),
        (17, "Nearest listed peers used to value a bank without a market cap (k)", g["peers_k"], "0", "Median multiple of the k banks with the closest return (sheet Peers)"),
        (18, "Valuation basis of such a bank (1 = tangible equity, 2 = CET1, 3 = average)", g["peers_basis"], "0", "CET1 is below tangible equity by the other CET1 deductions"),
        (19, "Share of the target's AT1, Tier 2, and eligible liabilities that count in the group", g["target_instruments"], "pct",
         "100% = all count. A subsidiary's instruments count at group level in part (CRR Articles 83 to 88), and as external MREL only if it is a resolution entity. 0% shows the need without them"),
        (20, "Assumed subordination requirement of a combination without a filed one (% of TREA)", g["sub_req"], "pct",
         "Banks above EUR 100bn of assets that file one report 13.5% to 31% (P3DH KM2 row EU-8). 13.5% is the most frequent value of the banks of EUR 100bn to 250bn"),
        (21, "Assets from which the assumption applies (EUR bn)", g["sub_assets"], "0", "NBG and BIL together have EUR 113bn. NBG alone has EUR 83bn and files 0%"),
        (22, "Floor of the subordination requirement (% of the leverage exposure)", g["sub_tem"], "pct", "Filed requirements are 5.0% to 8.2% of the exposure (KM2 row EU-10)"),
    ]
    for r, text, v, kind, note in extra:
        put(f"M{r}", text)
        put(f"N{r}", v, kind, "link" if isinstance(v, str) else "input")
        put(f"O{r}", note)
    put("N3", "=(D32-$N$6*D46)/(D9-MAX(D46,0)*$D$3*(1-$N$2))", '0.0"x"', "link")
    put("O3", "Default: the P/E of NBG without excess CET1. The original typed 14. Overwrite to test another multiple")

    # ---- header and size
    label(5, "Data as of"); fill(5, BANK_COLS, "=P3DH!{c}3", "text", "link")
    label(6, "M&A ANALYSIS"); ws["C6"].font = BOLD
    put("D6", "NBG")
    for c, d in zip(TGT, deals):
        put(f"{c}6", d["short"], None, "input")
    fill(6, COMBOS, '=$D$6&"+"&{t}6')
    put("K6", '="NBG at "&TEXT($D$1*100,"0")&"% CET1"')
    for c in ALL:
        ws[f"{c}6"].font = BOLD
    label(7, "Size (€bn)")
    fill(7, BANK_COLS, "=" + "P3DH!{c}" + str(b.rows["total_assets"]), "bn", "link")
    fill(7, COMBOS, "=$D$7+{t}7-" + P("cc1_intangibles", "{t}") + "+{c}81+{c}86", "bn")
    put("K7", "=$D$7-($D$20-K20)", "bn")
    label(8, "RWAs (€bn)")
    fill(8, BANK_COLS, "=P3DH!{c}" + str(b.rows["trea"]), "bn", "link")
    fill(8, COMBOS, "=$D$8*(1+$D$65)+{t}8*(1+{t}65)", "bn")
    put("K8", "=D8", "bn")
    label(9, "Profits (€bn)")
    for c, m in zip(BANK_COLS, MCOLS):  # profit of the analysis year: consensus, else the last 12 months
        put(f"{c}9", "=CHOOSE($N$15," + ",".join(f"Market!{m}{USED_TOP + k}" for k in range(4)) + ")/1000", "bn", "link")
    fill(9, COMBOS, "=$D$9+{t}9*{c}4", "bn")
    put("K9", "=D9", "bn")
    label(10, "Cash income lost at DFR (after tax)")
    fill(10, COMBOS, "=-{c}2*{t}38*$D$3*(1-$N$2)", "bn")
    put("K10", "=-($D$20-K20)*$D$3*(1-$N$2)", "bn")
    label(11, "Integration cost: % of opex over years (after tax)")
    fill(11, COMBOS, "=-($N$4/$N$5)*{t}62*(1-{t}61)", "bn")
    label(12, "Profits after M&A costs (€bn)")
    fill(12, BANK_COLS, "={c}9", "bn")
    fill(12, COMBOS + ["K"], "=SUM({c}9:{c}11)", "bn")
    ws["C13"] = '="ROCET1 (at "&TEXT($D$1*100,"0")&"%)"'
    put("D13", "=(D12-MAX(D46,0)*$D$3*(1-$N$2))/(D8*$D$1)", "pct")
    fill(13, TGT, "=({c}12-MAX({c}46,0)*$D$3*(1-{c}61))/({c}8*$D$1)", "pct")
    fill(13, COMBOS, "=({c}12-MAX({c}46,0)*$D$3*(1-$N$2))/({c}88*$D$1)", "pct")
    put("K13", "=(K12-MAX(K46,0)*$D$3*(1-$N$2))/(K8*$D$1)", "pct")
    label(14, "Change to current NBG"); fill(14, COMBOS + ["K"], "={c}13/$D$13-1", "pct")
    label(15, "Synergies required for same as current returns (€bn)"); fill(15, COMBOS, "=$D$13*$D$1*{c}88-{c}12", "bn")
    ws["C16"] = "=C13&\"+goodwill\""
    fill(16, COMBOS, "={c}12/(($D$1*{c}88)+{t}39)", "pct")
    ws["C17"] = '="Efficiency metric : ROCET1 (at "&TEXT($D$1*100,"0")&"%) / (P/E)"'
    fill(17, BANK_COLS, "={c}13/{c}36", "pct2")

    # ---- equity and market cap
    label(19, "Equity and Market cap"); ws["C19"].font = BOLD
    fill(19, ALL, "={c}6")
    label(20, "CET1")
    fill(20, BANK_COLS, "=P3DH!{c}" + str(b.rows["cet1"]), "bn", "link")
    fill(20, COMBOS, "=$D$20+{t}20-{c}74+{c}85-{c}84-{c}4*{c}79-{c}83+{c}67", "bn")
    put("K20", "=$D$1*K8", "bn")
    label(21, "CET1 ratio"); fill(21, ALL, "={c}20/{c}8", "pct")
    label(22, "AT1")
    fill(22, BANK_COLS, "=P3DH!{c}" + str(b.rows["t1"]) + "-P3DH!{c}" + str(b.rows["cet1"]), "bn", "link")
    fill(22, COMBOS, "=$D22+$N$19*{t}22+{c}68", "bn")
    label(23, "Tier2")
    fill(23, BANK_COLS, "=P3DH!{c}" + str(b.rows["tc"]) + "-P3DH!{c}" + str(b.rows["t1"]), "bn", "link")
    fill(23, COMBOS, "=$D23+$N$19*{t}23+{c}69", "bn")
    label(24, "Senior (MREL eligible liabilities)")
    fill(24, BANK_COLS, "=IF(P3DH!{c}" + str(b.rows["km2_ofel"]) + ">0,P3DH!{c}" + str(b.rows["km2_ofel"]) + "-P3DH!{c}" + str(b.rows["tc"]) + ",0)", "bn", "link")
    fill(24, COMBOS, "=$D24+$N$19*{t}24+{c}70+{c}71", "bn")
    label(25, "MREL total"); fill(25, BANK_COLS + COMBOS, "={c}20+{c}22+{c}23+{c}24", "bn")
    label(26, "MREL ratio"); fill(26, BANK_COLS + COMBOS, "={c}25/{c}8", "pct")
    ws["C27"] = '="MREL needed for "&TEXT($D$2*100,"0")&"% ratio (+ shortfall, - surplus)"'
    fill(27, ["D"] + COMBOS, "=($D$2-{c}26)*{c}8", "bn")
    label(28, "CET1 ratio + DTAs relying on future profitability (lever N16)"); fill(28, COMBOS, "=({c}20+$N$16*($D$41-$D$42))/{c}8", "pct")
    label(29, "CET1 ratio + that lever + waived dividend"); put("D29", g["dividend_waiver"], "bn", "input")
    fill(29, COMBOS, "=({c}20+$N$16*($D$41-$D$42)+$D$29)/{c}8", "pct")
    label(30, "Tangible Equity (€bn)")
    fill(30, BANK_COLS, "=P3DH!{c}" + str(b.rows["cc1_cet1_before_adj"]) + "-P3DH!{c}" + str(b.rows["cc1_intangibles"]), "bn", "link")
    fill(30, COMBOS, "={c}20+($D$30-$D$20)+({t}30-{t}20)", "bn")
    put("K30", "=$D$30-$D$20+K20", "bn")
    ws["C31"] = '="Market cap: "&TEXT($N$3,"0.0")&"x P/E on profit without income on excess CET1, plus excess CET1 (€bn)"'
    fill(31, COMBOS, "=({c}12-{c}11-MAX({c}46,0)*$D$3*(1-$N$2))*$N$3+$N$6*{c}46", "bn")
    label(32, "Market cap (WA P/TBV) (€bn)")
    put("D32", "=D48*D49", "bn")
    for c, m in zip(TGT, MCOLS[1:]):  # market cap when the bank is listed, else the value of the nearest peers
        mc_ = f"Market!{m}{MROW['mcap']}"
        put(f"{c}32", f"=IF({mc_}>0,{mc_}/1000,{c}60*{c}30)", "bn", "link")
    fill(32, COMBOS, "=($D$35*$D$45+{t}35*{t}45)/($D$45+{t}45)*{c}45+$N$6*{c}46", "bn")
    label(33, "Average estimated market cap (€bn)")
    fill(33, COMBOS, "=AVERAGE({c}31:{c}32)", "bn")
    put("K33", "=$D$32-$N$6*($D$20-K20)", "bn")
    label(34, "P/TBV"); fill(34, BANK_COLS, "={c}32/{c}30", "x"); fill(34, COMBOS + ["K"], "={c}33/{c}30", "x")
    ws["C35"] = '="P/TBV at "&TEXT($D$1*100,"0")&"% (excess CET1 valued at "&TEXT($N$6,"0.0")&"x)"'
    fill(35, BANK_COLS, "=({c}32-$N$6*{c}46)/{c}45", "x")
    fill(35, COMBOS + ["K"], "=({c}33-$N$6*{c}46)/{c}45", "x")
    label(36, "P/E")
    put("D36", "=D32/D9", "x"); fill(36, TGT, "={c}32*(1+{c}37)/{c}9", "x"); fill(36, COMBOS + ["K"], "={c}33/{c}12", "x")
    label(37, "Premium paid")
    for c, d in zip(TGT, deals):
        put(f"{c}37", d["premium"], "pct", "input")
    label(38, "Acquisition price for the stake (€bn)"); fill(38, TGT, "={x}4*{c}32*(1+{c}37)", "bn")
    label(39, "Goodwill + tangible non-CET1 (price less CET1 acquired)"); fill(39, TGT, "={c}38-{x}4*{c}20", "bn")
    label(40, "P/E at the price"); fill(40, TGT, "={c}38/({x}4*{c}12)", "x")
    label(41, "Total DTAs (CC2)"); put("D41", "=P3DH!D" + str(b.rows["dta_total"]), "bn", "link"); fill(41, COMBOS, "=$D$41/{c}20", "pct")
    label(42, "of which DTCs: do not rely on future profitability (CC2)"); put("D42", "=P3DH!D" + str(b.rows["dta_nonreliant"]), "bn", "link")
    label(43, "DTC/CET1"); put("D43", "=D42/D20", "pct"); fill(43, COMBOS, "=$D$42/{c}20", "pct")
    label(44, "ROI"); fill(44, COMBOS, "=({c}12-$D$12)/{t}38", "pct")
    label(45, "Tangible equity at CET1 target (€bn)", True); fill(45, ALL, "=$D$1*{c}8+{c}30-{c}20", "bn")
    label(46, "Excess CET1 over target (€bn)", True); fill(46, ALL, "={c}20-$D$1*{c}8", "bn")

    # ---- share performance
    label(47, "Share performance"); ws["C47"].font = BOLD
    label(48, "Number of Shares ( in billions)")
    put("D48", f"=Market!B{MROW['shares']}/1000", "0.0000", "link")
    fill(48, COMBOS, "=$D$48+{c}3*{t}38/$D$49", "0.0000")
    put("K48", "=$D$48-($D$20-K20)/$D$49", "0.0000")
    label(49, "Price"); put("D49", f"=Market!B{MROW['price']}", "0.00", "link")
    fill(49, COMBOS + ["K"], "={c}33/{c}48", "0.00")
    label(50, "Upside for NBG holders"); fill(50, COMBOS + ["K"], "={c}49/$D$49-1", "pct")
    label(51, "EPS"); put("D51", "=D9/D48", "eps"); fill(51, COMBOS + ["K"], "={c}12/{c}48", "eps")
    ws["C52"] = '="EPS (at "&TEXT($D$1*100,"0")&"% CET1)"'
    fill(52, ["D"], "=({c}9-MAX({c}46,0)*$D$3*(1-$N$2))/({c}48-MAX({c}46,0)/$D$49)", "eps")
    fill(52, COMBOS + ["K"], "=({c}12-MAX({c}46,0)*$D$3*(1-$N$2))/({c}48-MAX({c}46,0)/$D$49)", "eps")
    label(53, "Upside for NBG holders (EPS at target CET1)"); fill(53, COMBOS + ["K"], "={c}52/$D$52-1", "pct")
    label(55, "NBG shareholder dilution"); ws["C55"].font = BOLD
    label(56, "Dilution total"); fill(56, COMBOS + ["K"], "=({c}48-$D$48)/$D$48", "pct")
    label(57, "Real dilution due to premium paid"); fill(57, COMBOS, "=1-($D$32+{c}4*{t}32)/($D$32+{c}4*{t}32*(1+{t}37))", "pct")
    label(58, "Real dilution due to premium only in share exchange"); fill(58, COMBOS, "=1-($D$32+{c}4*{t}32)/($D$32+{c}4*{t}32+{t}37*{c}4*{t}32*{c}3)", "pct")

    # ---- new blocks
    label(59, "ADDITIONAL DEAL INPUTS (new)", True); ws["C59"].font = BOLD
    fill(59, BANK_COLS, "={c}6")
    label(60, "Valuation of a bank without a market cap as P/TBV (x): row 167 / tangible equity", True)
    for c in TGT:
        put(f"{c}60", f"={c}167/{c}30", "x")
    label(61, "Tax rate (statutory, Bloomberg)", True)
    put("D61", "=$N$2", "pct")
    for c, m in zip(TGT, MCOLS[1:]):
        put(f"{c}61", f"=Market!{m}{MROW['tax']}", "pct", "link")
    label(62, "Operating expenses, last fiscal year (€bn, Bloomberg)", True)
    for c, m in zip(BANK_COLS, MCOLS):
        put(f"{c}62", f"=Market!{m}{MROW['opex']}/1000", "bn", "link")
    label(63, "Transaction cost (% of price)", True)
    label(64, "Fair value write-down (% of tangible equity)", True)
    label(65, "Change of risk exposure after the deal (%)", True)
    put("D65", g["rwa_nbg"], "pct", "input")
    for c, d in zip(TGT, deals):
        put(f"{c}63", d["txn"], "pct", "input")
        put(f"{c}64", d["fv"], "pct", "input")
        put(f"{c}65", d["rwa"], "pct", "input")
    label(66, "Instruments issued for the deal (€bn)", True); ws["C66"].font = BOLD
    fill(66, COMBOS, "={c}6")
    for r, text, k in ((67, "New CET1", "new_cet1"), (68, "New AT1", "new_at1"), (69, "New Tier 2", "new_t2"), (70, "New senior non-preferred (subordinated)", "new_snp"), (71, "New senior preferred", "new_sp")):
        label(r, text, True)
        for c, d in zip(COMBOS, deals):
            put(f"{c}{r}", d[k], "bn", "input")

    label(72, "PURCHASE ACCOUNTING (new)", True); ws["C72"].font = BOLD
    fill(72, COMBOS, "={c}6")
    rows = [
        (73, "Price for the stake", "={t}38", "bn"),
        (74, "Cash paid", "={c}2*{t}38", "bn"),
        (75, "Shares issued (value)", "={c}3*{t}38", "bn"),
        (76, "Target tangible equity (100%)", "={t}30", "bn"),
        (77, "Target common equity before adjustments (CC1)", "=" + P("cc1_cet1_before_adj", "{t}"), "bn"),
        (78, "Target intangible assets written off", "=" + P("cc1_intangibles", "{t}"), "bn"),
        (79, "Fair value write-down after tax (100%)", "={t}64*{t}30*(1-{t}61)", "bn"),
        (80, "Price less share of fair-valued tangible equity", "={c}73-{c}4*({c}76-{c}79)", "bn"),
        (81, "New goodwill", "=MAX({c}80,0)", "bn"),
        (82, "Gain from a bargain purchase", "=MAX(-{c}80,0)", "bn"),
        (83, "Transaction cost", "={t}63*{c}73", "bn"),
        (84, "Minority interest removed from CET1", "=(1-{c}4)*{c}76", "bn"),
        (85, "Minority interest counted in CET1", "=(1-{c}4)*MIN({t}20,{t}100*{t}8)", "bn"),
        (86, "Change of cash and liquid assets", "={c}67+{c}68+{c}69+{c}70+{c}71-{c}74-{c}83", "bn"),
        (88, "RWAs attributable to NBG shareholders (€bn)", "=$D$8*(1+$D$65)+{c}4*{t}8*(1+{t}65)", "bn"),
    ]
    for r, text, tmpl, kind in rows:
        label(r, text, True)
        fill(r, COMBOS, tmpl, kind)

    label(90, "REGULATORY VIEW (new, from P3DH)", True); ws["C90"].font = BOLD
    fill(90, ALL[:-1], "={c}6")
    bl = "=($D${r}*$D$8*(1+$D$65)+{{t}}{r}*{{t}}8*(1+{{t}}65))/{{c}}8"
    for r, text, key in ((91, "P2R, CET1 part", "p2r_cet1"), (92, "P2R, total", "p2r"), (93, "P2R, Tier 1 part", "p2r_t1")):
        label(r, text, True)
        fill(r, BANK_COLS, "=P3DH!{c}" + str(b.rows[key]), "pct2", "link")
        fill(r, COMBOS, bl.format(r=r), "pct2")
    for r, text, key, default in ((94, "Capital conservation buffer", "ccb", "0.025"), (95, "Countercyclical buffer", "ccyb", "0"), (96, "Systemic risk buffer", "syrb", "0")):
        label(r, text, True)
        fill(r, BANK_COLS, "=IF(P3DH!{c}" + str(b.rows[key]) + ">0,P3DH!{c}" + str(b.rows[key]) + "," + default + ")", "pct2", "link")
        fill(r, COMBOS, bl.format(r=r), "pct2")
    label(97, "G-SII / O-SII buffer (higher of the two)", True)
    fill(97, BANK_COLS, "=MAX(P3DH!{c}" + str(b.rows["gsii"]) + ",P3DH!{c}" + str(b.rows["osii"]) + ")", "pct2", "link")
    fill(97, COMBOS, "=MAX($D$97,{t}97)", "pct2")
    label(98, "Other buffer (residual of the combined buffer)", True)
    fill(98, BANK_COLS, "=IF(P3DH!{c}" + str(b.rows["cbr"]) + ">0,MAX(P3DH!{c}" + str(b.rows["cbr"]) + "-({c}94+{c}95+{c}96+{c}97),0),0)", "pct2", "link")
    fill(98, COMBOS, bl.format(r=98), "pct2")
    label(99, "Combined buffer requirement", True); fill(99, BANK_COLS + COMBOS, "=SUM({c}94:{c}98)", "pct2")
    label(100, "CET1 requirement (trigger of MDA)", True); fill(100, BANK_COLS + COMBOS, "=$N$13+{c}91+{c}99", "pct2")
    label(101, "Tier 1 requirement", True); fill(101, BANK_COLS + COMBOS, "=$N$14+{c}93+{c}99", "pct2")
    label(102, "Total capital requirement", True); fill(102, BANK_COLS + COMBOS, "=$N$7+{c}92+{c}99", "pct2")
    label(103, "CET1 headroom (€bn)", True); fill(103, BANK_COLS + COMBOS, "={c}20-{c}100*{c}8", "bn")
    label(104, "Tier 1 headroom (€bn)", True); fill(104, BANK_COLS + COMBOS, "=({c}20+{c}22)-{c}101*{c}8", "bn")
    label(105, "Total capital headroom (€bn)", True); fill(105, BANK_COLS + COMBOS, "=({c}20+{c}22+{c}23)-{c}102*{c}8", "bn")
    label(106, "Distance to MDA (bp of RWAs)", True); fill(106, BANK_COLS + COMBOS, "=MIN({c}103,{c}104,{c}105)/{c}8*10000", "bp")
    label(107, "Binding layer", True)
    fill(107, BANK_COLS + COMBOS, '=IF(AND({c}103<={c}104,{c}103<={c}105),"CET1",IF({c}104<={c}105,"Tier 1","Total capital"))', "text")
    label(108, "Tier 1 capital (€bn)", True); fill(108, BANK_COLS + COMBOS, "={c}20+{c}22", "bn")
    label(109, "Leverage exposure (€bn)", True)
    fill(109, BANK_COLS, "=P3DH!{c}" + str(b.rows["lev_exp"]), "bn", "link")
    fill(109, COMBOS, "=$D$109+{t}109+{c}86", "bn")
    label(110, "Leverage ratio", True); fill(110, BANK_COLS + COMBOS, "={c}108/{c}109", "pct2")
    label(111, "Leverage requirement", True)
    fill(111, BANK_COLS, "=IF(P3DH!{c}" + str(b.rows["lev_req"]) + ">0,P3DH!{c}" + str(b.rows["lev_req"]) + ",0.03)", "pct2", "link")
    fill(111, COMBOS, "=($D$111*$D$109+{t}111*{t}109)/($D$109+{t}109)", "pct2")
    label(112, "Leverage headroom (bp)", True); fill(112, BANK_COLS + COMBOS, "=({c}110-{c}111)*10000", "bp")
    label(113, "HQLA (€bn)", True)
    fill(113, BANK_COLS, "=P3DH!{c}" + str(b.rows["hqla"]), "bn", "link")
    fill(113, COMBOS, "=MAX($D$113+{t}113+{c}86,0)", "bn")
    label(114, "Net cash outflows (€bn)", True)
    fill(114, BANK_COLS, "=P3DH!{c}" + str(b.rows["net_outflow"]), "bn", "link")
    fill(114, COMBOS, "=$D$114+{t}114", "bn")
    label(115, "LCR", True); fill(115, BANK_COLS + COMBOS, "={c}113/{c}114", "pct")
    label(116, "Available stable funding (€bn)", True)
    fill(116, BANK_COLS, "=P3DH!{c}" + str(b.rows["asf"]), "bn", "link")
    fill(116, COMBOS, "=$D$116+{t}116+{c}67+{c}68+{c}69+{c}70+{c}71+{c}75-{c}4*{c}77", "bn")
    label(117, "Required stable funding (€bn)", True)
    fill(117, BANK_COLS, "=P3DH!{c}" + str(b.rows["rsf"]), "bn", "link")
    fill(117, COMBOS, "=$D$117+{t}117", "bn")
    label(118, "NSFR", True); fill(118, BANK_COLS + COMBOS, "={c}116/{c}117", "pct")
    label(119, "MREL requirement, % of TREA (KM2; 0 = no KM2)", True)
    fill(119, BANK_COLS, "=IF(P3DH!{c}" + str(b.rows["km2_req_trea"]) + ">0,P3DH!{c}" + str(b.rows["km2_req_trea"]) + ",0)", "pct2", "link")
    fill(119, COMBOS, "=IF({t}119>0,($D$119*$D$8*(1+$D$65)+{t}119*{t}8*(1+{t}65))/{c}8,$D$119)", "pct2")
    label(120, "MREL requirement with combined buffer", True); fill(120, BANK_COLS + COMBOS, "=IF({c}119>0,{c}119+{c}99,0)", "pct2")
    label(121, "MREL headroom vs requirement (bp of RWAs)", True); fill(121, BANK_COLS + COMBOS, "=IF({c}120>0,({c}26-{c}120)*10000,0)", "bp")
    label(122, "AT1 surplus (+) / shortfall (-) vs requirement (€bn)", True)
    label(123, "Tier 2 surplus (+) / shortfall (-) vs requirement (€bn)", True)
    label(124, "Senior surplus (+) / shortfall (-) vs MREL target (€bn)", True)
    for c in ["D"] + COMBOS:
        put(f"{c}122", f"={c}22-($N$8+$N$11*{c}92)*{c}8", "bn")
        put(f"{c}123", f"={c}23-($N$9+$N$12*{c}92)*{c}8", "bn")
        put(f"{c}124", f"={c}24-($D$2-($N$8+$N$11*{c}92)-($N$9+$N$12*{c}92)-{c}21)*{c}8", "bn")
    label(125, "Size class (total assets: <10, <100, <250, above, €bn)", True)
    fill(125, ALL, '=IF({c}7<10,"Small",IF({c}7<100,"Medium",IF({c}7<250,"Large","Very large")))', "text")
    label(126, "Country / geography", True)
    fill(126, BANK_COLS, "=P3DH!{c}" + str(b.rows["country"]), "text", "link")
    fill(126, COMBOS, '=IF($D$126={t}126,"Domestic","Cross-border")', "text")
    label(127, "Asset encumbrance (AE1)", True)
    enc, une = b.rows["ae_encumbered"], b.rows["ae_unencumbered"]
    fill(127, BANK_COLS, "=IF(P3DH!{c}" + str(enc) + "+P3DH!{c}" + str(une) + ">0,P3DH!{c}" + str(enc) + "/(P3DH!{c}" + str(enc) + "+P3DH!{c}" + str(une) + "),0)", "pct", "link")
    fill(127, COMBOS, f"=(P3DH!$D{enc}+P3DH!{{t}}{enc})/(P3DH!$D{enc}+P3DH!$D{une}+P3DH!{{t}}{enc}+P3DH!{{t}}{une})", "pct")
    label(128, "Non-performing loans (CR1)", True)
    npl, perf = b.rows["cr1_loans_npl"], b.rows["cr1_loans_performing"]
    fill(128, BANK_COLS, "=IF(P3DH!{c}" + str(npl) + "+P3DH!{c}" + str(perf) + ">0,P3DH!{c}" + str(npl) + "/(P3DH!{c}" + str(npl) + "+P3DH!{c}" + str(perf) + "),0)", "pct2", "link")
    fill(128, COMBOS, f"=(P3DH!$D{npl}+P3DH!{{t}}{npl})/(P3DH!$D{npl}+P3DH!$D{perf}+P3DH!{{t}}{npl}+P3DH!{{t}}{perf})", "pct2")

    label(129, "Valuation basis", True)
    put("D129", "Market cap")
    for c, m in zip(TGT, MCOLS[1:]):
        put(f"{c}129", f'=IF(Market!{m}{MROW["mcap"]}>0,"Market cap","Nearest peers")', "text")
    label(130, "IRRBB1: change of economic value of equity (€bn)", True); ws["C130"].font = BOLD
    fill(130, BANK_COLS + COMBOS, "={c}6")
    for i, (code, name) in enumerate(ma_data.IRRBB_ROWS.items()):
        r = 131 + i
        label(r, name, True)
        fill(r, BANK_COLS, "=P3DH!{c}" + str(b.rows[f"irrbb_{code}"]), "bn", "link")
        fill(r, COMBOS, "=$D" + str(r) + "+{t}" + str(r), "bn")
        r2 = 138 + i
        label(r2, f"{name}, % of Tier 1", True)
        fill(r2, BANK_COLS + COMBOS, "={c}" + str(r) + "/{c}108", "pct")
    label(137, "IRRBB1: % of Tier 1 (supervisory limit 15%)", True); ws["C137"].font = BOLD

    label(145, "CHECKS (1 = passed)", True); ws["C145"].font = BOLD
    label(146, "Cash and share split adds to 100%", True)
    fill(146, COMBOS, "=IF(ABS({c}2+{c}3-1)<0.000001,1,0)", "flag")
    label(147, "CC1 adds up to KM1 CET1 (within 2%)", True)
    eq, adj, ce = b.rows["cc1_cet1_before_adj"], b.rows["cc1_total_adj"], b.rows["cet1"]
    fill(147, BANK_COLS, "=IF(AND(P3DH!{c}" + str(eq) + ">0,P3DH!{c}" + str(adj) + ">0),IF(ABS(P3DH!{c}" + str(eq) + "-P3DH!{c}" + str(adj) + "-P3DH!{c}" + str(ce) + ")<=0.02*P3DH!{c}" + str(ce) + ",1,0),0)", "flag")
    label(148, "Information: KM2 TREA equals KM1 TREA (0 if the bank has no KM2)", True)
    fill(148, BANK_COLS, "=IF(P3DH!{c}" + str(b.rows["km2_trea"]) + ">0,IF(ABS(P3DH!{c}" + str(b.rows["km2_trea"]) + "/P3DH!{c}" + str(b.rows["trea"]) + "-1)<=0.02,1,0),0)", "flag")
    label(149, "Data of the target is from the quarter of NBG", True)
    fill(149, TGT, "=IF(P3DH!{c}3=P3DH!$D$3,1,0)", "flag")
    label(150, "Price is not above 3 times tangible equity of the stake", True)
    fill(150, COMBOS, "=IF({c}73<=3*{c}4*{c}76,1,0)", "flag")
    label(151, "All checks passed", True)
    label(152, "Market data complete: profit, opex, tax rate, and valuation above 0 (1 = yes)", True)
    fill(152, BANK_COLS, "=IF(AND({c}9>0,{c}62>0,{c}61>0,{c}32>0),1,0)", "flag")
    put("D151", '=IF(MIN(D147:G147,E149:G149,H146:J146,H150:J150,D152:G152,D156:J156)=1,"OK","CHECK")')
    label(153, "MREL DETAIL (new, from KM2)", True); ws["C153"].font = BOLD
    fill(153, BANK_COLS + COMBOS, "={c}6")
    ofel, osub, rsub = b.rows["km2_ofel"], b.rows["km2_ofel_sub"], b.rows["km2_req_trea_sub"]
    label(154, "Senior non-preferred: subordinated eligible liabilities (€bn)", True)
    fill(154, BANK_COLS, "=IF(P3DH!{c}" + str(osub) + ">0,P3DH!{c}" + str(osub) + "-P3DH!{c}" + str(b.rows["tc"]) + ",0)", "bn", "link")
    fill(154, COMBOS, "=$D154+$N$19*{t}154+{c}70", "bn")
    label(155, "Senior preferred: non-subordinated eligible liabilities (€bn)", True)
    fill(155, BANK_COLS, "=IF(P3DH!{c}" + str(ofel) + ">0,P3DH!{c}" + str(ofel) + "-P3DH!{c}" + str(osub) + ",0)", "bn", "link")
    fill(155, COMBOS, "=$D155+$N$19*{t}155+{c}71", "bn")
    label(156, "The two lines add up to row 24 (1 = yes)", True)
    fill(156, BANK_COLS + COMBOS, "=IF(ABS({c}154+{c}155-{c}24)<0.001,1,0)", "flag")
    label(157, "Subordinated resources, % of RWAs (own funds + senior non-preferred)", True)
    fill(157, BANK_COLS + COMBOS, "=({c}20+{c}22+{c}23+{c}154)/{c}8", "pct2")
    label(158, "Subordination requirement, % of TREA (KM2; 0 = none)", True)
    fill(158, BANK_COLS, "=IF(P3DH!{c}" + str(rsub) + ">0,P3DH!{c}" + str(rsub) + ",0)", "pct2", "link")
    fill(158, COMBOS, "=($D$158*$D$8*(1+$D$65)+{t}158*{t}8*(1+{t}65))/{c}8", "pct2")
    label(159, "Subordination headroom, with combined buffer (bp)", True)
    fill(159, BANK_COLS + COMBOS, "=IF({c}158>0,({c}157-({c}158+{c}99))*10000,0)", "bp")

    label(160, "PEER VALUATION OF A BANK WITHOUT A MARKET CAP (new, sheet Peers)", True); ws["C160"].font = BOLD
    fill(160, TGT, "={c}6")
    label(161, "Return on tangible equity of the target (profit of the year / tangible equity)", True); fill(161, TGT, "={c}9/{c}30", "pct")
    label(162, "Return on CET1 of the target (profit of the year / CET1)", True); fill(162, TGT, "={c}9/{c}20", "pct")
    label(163, "P/TBV of the k nearest peers by RoTE (median, x)", True)
    label(164, "P/CET1 of the k nearest peers by RoCET1 (median, x)", True)
    for t, c in enumerate(TGT):
        pc = peer_cols(t)
        put(f"{c}163", f"=Peers!{pc['m_tbv']}7", "x", "link")
        put(f"{c}164", f"=Peers!{pc['m_cet1']}7", "x", "link")
    label(165, "Value on tangible equity (€bn)", True); fill(165, TGT, "={c}163*{c}30", "bn")
    label(166, "Value on CET1 (€bn)", True); fill(166, TGT, "={c}164*{c}20", "bn")
    label(167, "Peer value used (€bn): basis in N18", True); fill(167, TGT, "=CHOOSE($N$18,{c}165,{c}166,AVERAGE({c}165,{c}166))", "bn")

    # ---- issuance needs and requirements weighted by RWAs
    label(169, "ISSUANCE NEEDS AND REQUIREMENTS WEIGHTED BY RWAs (new)", True); ws["C169"].font = BOLD
    fill(169, BANK_COLS + COMBOS, "={c}6")
    label(170, "RWAs (€bn)", True); fill(170, BANK_COLS + COMBOS, "={c}8", "bn")
    label(171, "RWA weight of NBG", True); fill(171, COMBOS, "=$D$8*(1+$D$65)/{c}8", "pct")
    label(172, "RWA weight of the target", True); fill(172, COMBOS, "={t}8*(1+{t}65)/{c}8", "pct")
    for r, text, src in ((173, "CET1 requirement, weighted by RWAs", 100), (174, "Tier 1 requirement, weighted by RWAs", 101), (175, "Total capital requirement, weighted by RWAs", 102)):
        label(r, text, True)
        fill(r, BANK_COLS, "={c}" + str(src), "pct2")
        fill(r, COMBOS, "=$D" + str(src) + "*{c}171+{t}" + str(src) + "*{c}172", "pct2")
    label(176, "MREL requirement with combined buffer, weighted by RWAs (0 = no KM2)", True)
    fill(176, BANK_COLS, "={c}120", "pct2")
    fill(176, COMBOS, "=IF({t}120>0,$D120*{c}171+{t}120*{c}172,$D120)", "pct2")
    label(177, "Subordination requirement with combined buffer, weighted by RWAs; N20 if none is filed and assets reach N21 (0 = none)", True)
    fill(177, BANK_COLS, "=IF({c}158>0,{c}158+{c}99,0)", "pct2")
    fill(177, COMBOS, "=IF(IF({t}177>0,$D177*{c}171+{t}177*{c}172,$D177)>0,IF({t}177>0,$D177*{c}171+{t}177*{c}172,$D177),IF({c}7>=$N$21,$N$20+{c}99,0))", "pct2")
    for r, text, src in ((178, "CET1 requirement (€bn)", 173), (179, "Tier 1 requirement (€bn)", 174), (180, "Total capital requirement (€bn)", 175), (181, "MREL requirement (€bn)", 176)):
        label(r, text, True)
        fill(r, BANK_COLS + COMBOS, "={c}" + str(src) + "*{c}170", "bn")
    label(182, "Subordination requirement (€bn); for a combination not below N22 of the leverage exposure", True)
    fill(182, BANK_COLS, "={c}177*{c}170", "bn")
    fill(182, COMBOS, "=IF({c}177>0,MAX({c}177*{c}170,$N$22*{c}109),0)", "bn")
    label(183, "Tier 1 resources (€bn)", True); fill(183, BANK_COLS + COMBOS, "={c}108", "bn")
    label(184, "Total capital resources (€bn)", True); fill(184, BANK_COLS + COMBOS, "={c}20+{c}22+{c}23", "bn")
    label(185, "MREL resources (€bn)", True); fill(185, BANK_COLS + COMBOS, "={c}25", "bn")
    label(186, "Subordinated resources: own funds and senior non-preferred (€bn)", True); fill(186, BANK_COLS + COMBOS, "={c}20+{c}22+{c}23+{c}154", "bn")
    label(187, "Need at the requirements: CET1 to meet the CET1 requirement (€bn)", True); fill(187, BANK_COLS + COMBOS, "=MAX(0,{c}178-{c}20)", "bn")
    label(188, "Need: Tier 1 (AT1) to meet the Tier 1 requirement, after row 187 (€bn)", True); fill(188, BANK_COLS + COMBOS, "=MAX(0,{c}179-{c}183-{c}187)", "bn")
    label(189, "Need: Tier 2 to meet the total capital requirement, after rows 187 and 188 (€bn)", True); fill(189, BANK_COLS + COMBOS, "=MAX(0,{c}180-{c}184-{c}187-{c}188)", "bn")
    label(190, "Need: eligible liabilities to meet the MREL requirement, after rows 187 to 189 (€bn)", True)
    fill(190, BANK_COLS + COMBOS, "=MAX(0,{c}181-{c}185-{c}187-{c}188-{c}189)", "bn")
    label(191, "Need: subordinated instruments to meet the subordination requirement (€bn)", True)
    fill(191, BANK_COLS + COMBOS, "=MAX(0,{c}182-{c}186-{c}187-{c}188-{c}189)", "bn")
    label(192, "Total issuance need at the requirements (€bn)", True); fill(192, BANK_COLS + COMBOS, "={c}187+{c}188+{c}189+MAX({c}190,{c}191)", "bn")
    label(193, "Need at the targets: CET1 to reach the CET1 target D1 (€bn)", True); fill(193, BANK_COLS + COMBOS, "=MAX(0,$D$1*{c}170-{c}20)", "bn")
    label(194, "Need at the targets: eligible liabilities to reach the MREL target D2, after row 193 (€bn)", True)
    fill(194, BANK_COLS + COMBOS, "=MAX(0,$D$2*{c}170-{c}185-{c}193)", "bn")
    label(195, "Total issuance need at the targets (€bn), not less than row 192", True); fill(195, BANK_COLS + COMBOS, "=MAX({c}193+{c}194,{c}192)", "bn")
    label(196, "AT1, Tier 2, and eligible liabilities of the target that count in the group (€bn)", True); fill(196, COMBOS, "=$N$19*({t}22+{t}23+{t}24)", "bn")
    label(197, "Need at the MREL target if none of them counted (€bn)", True); fill(197, COMBOS, "=MAX(0,$D$2*{c}170-({c}185-{c}196)-{c}193)", "bn")
    label(198, "Mitigation by the capital structure of the target (€bn)", True); fill(198, COMBOS, "={c}197-{c}194", "bn")
    label(199, "Goodwill of the deal, deducted from CET1 (€bn)", True); fill(199, COMBOS, "={c}81", "bn")
    label(200, "CET1 ratio effect of the goodwill (bp of RWAs)", True); fill(200, COMBOS, "=-{c}81/{c}8*10000", "bp")
    label(201, "Change of CET1 compared with NBG alone (€bn)", True); fill(201, COMBOS, "={c}20-$D$20", "bn")


    # ---- buckets for AT1 and Tier 2, and the instruments to issue
    label(203, "CAPITAL BUCKETS FOR AT1 AND TIER 2 FROM THE P2R, AND INSTRUMENTS TO ISSUE (new)", True); ws["C203"].font = BOLD
    fill(203, BANK_COLS + COMBOS, "={c}6")
    label(204, "P2R, weighted by RWAs (%)", True); fill(204, BANK_COLS + COMBOS, "={c}92", "pct2")
    label(205, "Largest AT1 bucket: Pillar 1 (N8) + share of the P2R (N11) (% of RWAs)", True); fill(205, BANK_COLS + COMBOS, "=$N$8+$N$11*{c}204", "pct2")
    label(206, "Largest Tier 2 bucket: Pillar 1 (N9) + share of the P2R (N12) (% of RWAs)", True); fill(206, BANK_COLS + COMBOS, "=$N$9+$N$12*{c}204", "pct2")
    label(207, "Smallest CET1: Pillar 1 (N13) + share of the P2R (N10) (% of RWAs)", True); fill(207, BANK_COLS + COMBOS, "=$N$13+$N$10*{c}204", "pct2")
    label(208, "AT1 bucket (€bn)", True); fill(208, BANK_COLS + COMBOS, "={c}205*{c}170", "bn")
    label(209, "Tier 2 bucket (€bn)", True); fill(209, BANK_COLS + COMBOS, "={c}206*{c}170", "bn")
    label(210, "AT1 outstanding (€bn)", True); fill(210, BANK_COLS + COMBOS, "={c}22", "bn")
    label(211, "Tier 2 outstanding (€bn)", True); fill(211, BANK_COLS + COMBOS, "={c}23", "bn")
    label(212, "AT1 that can still be issued within the bucket (€bn)", True); fill(212, BANK_COLS + COMBOS, "=MAX(0,{c}208-{c}210)", "bn")
    label(213, "Tier 2 that can still be issued within the bucket (€bn)", True); fill(213, BANK_COLS + COMBOS, "=MAX(0,{c}209-{c}211)", "bn")
    label(214, "AT1 above the bucket: counts for the MREL, not for the capital requirement (€bn)", True); fill(214, BANK_COLS + COMBOS, "=MAX(0,{c}210-{c}208)", "bn")
    label(215, "Tier 2 above the bucket: counts for the MREL, not for the capital requirement (€bn)", True); fill(215, BANK_COLS + COMBOS, "=MAX(0,{c}211-{c}209)", "bn")
    label(216, "To issue: AT1 for the Tier 1 need, within the bucket (€bn)", True); fill(216, BANK_COLS + COMBOS, "=MIN({c}188,{c}212)", "bn")
    label(217, "To issue: Tier 2 for the total capital need, within the bucket (€bn)", True); fill(217, BANK_COLS + COMBOS, "=MIN({c}189,{c}213)", "bn")
    label(218, "Need that does not fit the buckets, to be met with CET1 (€bn)", True); fill(218, BANK_COLS + COMBOS, "=({c}188-{c}216)+({c}189-{c}217)", "bn")
    label(219, "To issue: senior non-preferred for the subordination need (€bn)", True); fill(219, BANK_COLS + COMBOS, "={c}191", "bn")
    label(220, "To issue: senior preferred for the MREL need at the target, after the layers above (€bn)", True)
    fill(220, BANK_COLS + COMBOS, "=MAX(0,{c}194-{c}216-{c}217-{c}219)", "bn")
    label(221, "To issue: CET1 (CET1 need at the target plus row 218) (€bn)", True); fill(221, BANK_COLS + COMBOS, "={c}193+{c}218", "bn")
    label(222, "Instruments to issue in total (€bn): CET1, AT1, Tier 2, senior non-preferred, senior preferred", True); fill(222, BANK_COLS + COMBOS, "={c}216+{c}217+{c}219+{c}220+{c}221", "bn")

    ws.column_dimensions["A"].width = 2
    ws.column_dimensions["B"].width = 2
    ws.column_dimensions["C"].width = 58
    for c in ALL:
        ws.column_dimensions[c].width = 13
    ws.column_dimensions["L"].width = 3
    ws.column_dimensions["M"].width = 38
    ws.column_dimensions["N"].width = 10
    ws.column_dimensions["O"].width = 46
    ws.freeze_panes = "D7"


# row kinds for the page and for tests: row -> format kind
ROW_KIND = {5: "text", 7: "bn", 8: "bn", 9: "bn", 10: "bn", 11: "bn", 12: "bn", 13: "pct", 14: "pct", 15: "bn", 16: "pct", 17: "pct2", 20: "bn", 21: "pct", 22: "bn",
            23: "bn", 24: "bn", 25: "bn", 26: "pct", 27: "bn", 28: "pct", 29: "pct", 30: "bn", 31: "bn", 32: "bn", 33: "bn", 34: "x", 35: "x", 36: "x", 37: "pct",
            38: "bn", 39: "bn", 40: "x", 41: "pct", 42: "bn", 43: "pct", 44: "pct", 45: "bn", 46: "bn", 48: "0.0000", 49: "eps", 50: "pct", 51: "eps", 52: "eps",
            53: "pct", 56: "pct", 57: "pct", 58: "pct"}
ROW_KIND.update({154: "bn", 155: "bn", 156: "flag", 157: "pct2", 158: "pct2", 159: "bp", 60: "x", 71: "bn", 61: "pct", 62: "bn", 63: "pct", 64: "pct", 65: "pct", 67: "bn", 68: "bn", 69: "bn", 70: "bn", 73: "bn", 74: "bn", 75: "bn", 76: "bn", 77: "bn",
                 78: "bn", 79: "bn", 80: "bn", 81: "bn", 82: "bn", 83: "bn", 84: "bn", 85: "bn", 86: "bn", 88: "bn", 91: "pct2", 92: "pct2", 93: "pct2", 94: "pct2",
                 95: "pct2", 96: "pct2", 97: "pct2", 98: "pct2", 99: "pct2", 100: "pct2", 101: "pct2", 102: "pct2", 103: "bn", 104: "bn", 105: "bn", 106: "bp",
                 107: "text", 108: "bn", 109: "bn", 110: "pct2", 111: "pct2", 112: "bp", 113: "bn", 114: "bn", 115: "pct", 116: "bn", 117: "bn", 118: "pct",
                 119: "pct2", 120: "pct2", 121: "bp", 122: "bn", 123: "bn", 124: "bn", 125: "text", 126: "text", 127: "pct", 128: "pct2", 146: "flag", 147: "flag",
                 148: "flag", 149: "flag", 150: "flag", 151: "text", 152: "flag", 129: "text", 161: "pct", 162: "pct", 163: "x", 164: "x", 165: "bn", 166: "bn", 167: "bn",
                 170: "bn", 171: "pct", 172: "pct", 173: "pct2", 174: "pct2", 175: "pct2", 176: "pct2", 177: "pct2", **{r: "bn" for r in range(178, 200)}, 200: "bp", 201: "bn", 203: "text", **{r: "pct2" for r in range(204, 208)}, **{r: "bn" for r in range(208, 223)}, **{r: "bn" for r in range(131, 137)}, **{r: "pct" for r in range(138, 144)}})
# Cells whose format differs from the rest of the row (an amount of NBG next to ratios of the combinations)
CELL_KIND = {("D", 29): "bn", ("D", 41): "bn"}
SECTIONS = [
    ("M&A analysis", 5, 17), ("Equity and market cap", 19, 46), ("Share performance and dilution", 47, 58),
    ("Deal inputs (new)", 60, 70), ("Purchase accounting (new)", 72, 88), ("Regulatory view (new)", 90, 129), ("IRRBB (new)", 130, 143), ("Checks (new)", 145, 152), ("MREL detail (new)", 153, 159),
    ("Peer valuation (new)", 160, 167), ("Issuance needs (new)", 169, 201), ("Capital buckets and instruments (new)", 203, 222),
]


YEARS = ["2026E", "2027E", "2028E", "2029E"]
YC = ["D", "E", "F", "G"]
MKT_YC = ["B", "C", "D", "E"]


# Layout of one deal on sheet Merger: sections with rows (key, label, kind). It follows Figure 89 of the original sheet.
MERGER_SECTIONS: list[tuple[str, list[tuple[str, str, str]]]] = [
    ("Deal structure", [("price", "Buyer price (EUR)", "eps"), ("prem", "Purchase price premium", "pct"), ("dealval", "Deal value for the stake (EUR bn)", "bn"),
                        ("eqpct", "% equity financing", "pct"), ("cashpct", "% cash", "pct"), ("eqfin", "Equity financing (EUR bn)", "bn"), ("newsh", "New shares (mn)", "int")]),
    ("Target valuation at the deal", [("impe", "Implied P/E", "x"), ("imptnav", "Implied P/TNAV", "x")]),
    ("Deal effects and assumptions", [
        ("syn_cost", "Cost synergies, % of target cost base", "pct"), ("syn_cost_grp", "   % of combined cost base", "pct"),
        ("restr", "Restructuring costs, % of run-rate cost synergies", "pct"), ("syn_rev", "Revenue synergies / (attrition), % of target revenues", "pct"),
        ("syn_rev_grp", "   % of combined revenues", "pct"), ("phase", "Phase-in of synergies", "pct"), ("tax", "Tax rate on deal effects", "pct"),
        ("payout", "Dividend payout of the group", "pct"), ("dfr", "Deposit rate on cash paid (expected average)", "pct2"),
        ("rwa_g_a", "RWA growth of NBG (% a year)", "pct"), ("rwa_g_t", "RWA growth of the target (% a year)", "pct"),
        ("cost_g", "Growth of costs, and of years without consensus (% a year)", "pct"), ("np_g", "Profit growth of a target without consensus (% a year)", "pct"),
        ("cir", "Cost/income ratio of a target without consensus", "pct"), ("rwa_opt", "RWA optimisation (EUR bn)", "bn"), ("rwa_pa", "Purchase accounting RWA adjustment (EUR bn)", "bn")]),
    ("Buyer: NBG (EUR m)", [("b_eps", "EPS before the deal (EUR)", "eps"), ("b_np", "Net profit", "int"), ("b_rev", "Total revenues", "int"), ("b_cost", "Total costs", "int"),
                            ("b_sh", "Shares (mn)", "int")]),
    ("Target (EUR m)", [("t_rev", "Total revenues", "int"), ("t_cost", "Total costs", "int"), ("t_np", "Net profit", "int"), ("t_phase", "% synergies", "pct"),
                        ("t_cost_syn", "Cost synergies (pre-tax)", "int"), ("t_rev_syn", "Revenue synergies / (attrition) (pre-tax)", "int")]),
    ("Pro forma: adjustments (EUR m)", [("a_np", "NBG net profit", "int"), ("a_tnp", "Target net profit (stake)", "int"), ("a_cs", "Cost synergies (after tax)", "int"),
                                        ("a_rs", "Restructuring (after tax)", "int"), ("a_rv", "Revenue synergies (after tax)", "int"), ("a_fin", "Deal financing (after tax)", "int"),
                                        ("a_eff", "Deal effects", "int"), ("a_tot", "Total net profit", "int")]),
    ("Shares (mn)", [("s_acq", "Acquirer shares", "int"), ("s_new", "New shares issued", "int"), ("s_tot", "New share total", "int")]),
    ("Regulatory capital (EUR bn)", [("c_acq", "NBG CET1 (organic)", "bn"), ("c_gw", "Target CET1 less price paid (goodwill effect)", "bn"), ("c_sh", "Value of shares issued", "bn"),
                                     ("c_oth", "Minority interest, fair value, costs, new CET1", "bn"), ("c_cum", "Cumulative retained profit of the target and the deal", "bn"),
                                     ("c_new", "CET1 new", "bn"), ("r_a", "NBG RWAs", "bn"), ("r_t", "Target RWAs", "bn"), ("r_opt", "RWA optimisation", "bn"),
                                     ("r_pa", "Purchase accounting adjustment", "bn"), ("r_new", "RWAs new", "bn"), ("c_ratio", "CET1 / RWAs", "pct"),
                                     ("c_req", "CET1 requirement (MDA trigger) of the group", "pct2"), ("c_head", "Headroom (bp)", "bp")]),
    ("Pro forma balance sheet (EUR bn)", [("bs_ta", "Total assets", "bn"), ("bs_loans", "Loans (gross, CR1)", "bn")]),
    ("Tangible equity and valuation", [("v_tn_a", "NBG tangible equity (organic)", "bn"), ("v_tn_pf", "Pro forma tangible equity", "bn"), ("v_tps_a", "NBG TNAV per share (EUR)", "eps"),
                                       ("v_tps_pf", "Pro forma TNAV per share (EUR)", "eps"), ("v_tps_imp", "TNAV/share impact", "pct"), ("v_pe", "Clean P/E", "x"),
                                       ("v_rote", "RoTE", "pct"), ("v_ptnav", "P/TNAV", "x")]),
    ("Earnings impact and return on investment", [("e_eps0", "EPS (before the deal)", "eps"), ("e_eps1", "EPS (pro forma)", "eps"), ("e_imp", "Earnings impact", "pct"),
                                                  ("e_lab", "Accretive / dilutive", "text"), ("e_roi", "Return on investment", "pct")]),
]


def merger_offsets() -> tuple[dict[str, int], int]:
    off: dict[str, int] = {}
    r = 2
    for title, items in MERGER_SECTIONS:
        off["_" + title] = r
        r += 1
        for key, _, _ in items:
            off[key] = r
            r += 1
        r += 1
    return off, r


MOFF, MEND = merger_offsets()
MBLOCK = MEND + 2
MKIND = {key: kind for _, items in MERGER_SECTIONS for key, _, kind in items}
MLABEL = {key: label for _, items in MERGER_SECTIONS for key, label, _ in items}


def merger_start(i: int) -> int:
    return 4 + i * MBLOCK


def write_merger(ws, b: Builder, deals: list[dict], market: dict) -> None:
    ws["A1"] = "Four-year merger model for each deal. It follows Figure 89 of the original sheet. EUR bn for capital, EUR m for profit."
    ws["A1"].font = BOLD
    ws["A2"] = "Blue on yellow: input. Green: link to Market, P3DH, or Calc. Deal terms (price, cash share, stake) come from sheet Calc. A target without consensus uses the last 12 months and the opex of Market."
    npl, perf = b.rows["cr1_loans_npl"], b.rows["cr1_loans_performing"]
    for i, d in enumerate(deals):
        R, T, X, m = merger_start(i), TGT[i], COMBOS[i], MCOLS[1 + i]

        def cr(metric: str, k: int, col: str = m) -> str:
            return f"Market!{col}{cons_row(metric, k)}"

        def a(key: str) -> int:
            return R + MOFF[key]

        def put(col: str, key: str, value, role: str | None = None) -> None:
            cell = ws[f"{col}{a(key)}"]
            cell.value = value
            cell.number_format = FORMATS.get(MKIND[key], MKIND[key])
            if role == "input":
                cell.font, cell.fill = BLUE, INPUT_FILL
            elif role == "link":
                cell.font = GREEN

        ws[f"C{R}"] = f'="Deal {i + 1}: "&Calc!{X}6'
        ws[f"C{R}"].font = Font(bold=True, size=12)
        for k, y in enumerate(YEARS):
            c = ws[f"{YC[k]}{R + 1}"]
            c.value, c.font, c.fill = y, HEAD_FONT, HEAD
        ws[f"C{R + 1}"] = "Years"
        for title, items in MERGER_SECTIONS:
            r = R + MOFF["_" + title]
            ws[f"C{r}"] = title
            ws[f"C{r}"].font = BOLD
            for col in ["C"] + YC:
                ws[f"{col}{r}"].fill = SECTION
            for key, label, _ in items:
                ws[f"C{a(key)}"] = label

        # deal structure
        put("D", "price", "=Calc!$D$49", "link")
        put("D", "prem", f"=Calc!{T}37", "link")
        put("D", "dealval", f"=Calc!{T}38", "link")
        put("D", "eqpct", f"=Calc!{X}3", "link")
        put("D", "cashpct", f"=Calc!{X}2", "link")
        put("D", "eqfin", f"=Calc!{X}75", "link")
        put("D", "newsh", f"=(Calc!{X}48-Calc!$D$48)*1000", "link")
        for k, c in enumerate(YC):
            put(c, "impe", f"=$D${a('dealval')}/(Calc!${X}$4*{c}{a('t_np')}/1000)")
            put(c, "imptnav", f"=$D${a('dealval')}/(Calc!${X}$4*Calc!${T}$30)")
        # assumptions
        put("D", "syn_cost", 0.30, "input")
        put("D", "syn_cost_grp", f"=$D${a('syn_cost')}*-D{a('t_cost')}/(-D{a('b_cost')}-D{a('t_cost')})")
        put("D", "restr", 1.0, "input")
        put("D", "syn_rev", -0.03, "input")
        put("D", "syn_rev_grp", f"=$D${a('syn_rev')}*D{a('t_rev')}/(D{a('b_rev')}+D{a('t_rev')})")
        for c, v in zip(YC, (0.0, 0.3, 0.6, 1.0)):
            put(c, "phase", v, "input")
        put("D", "tax", "=Calc!$N$2", "link")
        put("D", "payout", f"={cr('DPS', 0, 'B')}/{cr('EPS', 0, 'B')}", "link")
        for k_, c in enumerate(YC):
            put(c, "dfr", f"=Market!{MKT_YC[k_]}{MKT_DFR_ROW}", "link")
            put(c, "rwa_opt", 0.0, "input")
            put(c, "rwa_pa", 0.0, "input")
        put("D", "rwa_g_a", 0.04, "input")
        put("D", "rwa_g_t", 0.04, "input")
        put("D", "cost_g", 0.03, "input")
        put("D", "np_g", 0.0, "input")
        put("D", "cir", 0.55, "input")

        for k, c in enumerate(YC):
            prev = YC[k - 1] if k else None
            # buyer
            put(c, "b_eps", f"={cr('EPS', k, 'B')}", "link")
            put(c, "b_np", f"={cr('NI', k, 'B')}", "link")
            put(c, "b_rev", f"={cr('SALES', k, 'B')}", "link")
            put(c, "b_cost", f"=-Market!$B${MROW['opex']}*(1+$D${a('cost_g')})^{k + 1}")
            put(c, "b_sh", f"={c}{a('b_np')}/{c}{a('b_eps')}")
            # target: consensus of the year when the bank has it. Otherwise the last 12 months, the opex, and the growth inputs
            ni, sa, op = cr("NI", k), cr("SALES", k), cr("OPP", k)
            if k == 0:
                put(c, "t_cost", f"=IF(AND({sa}<>0,{op}<>0),-({sa}-{op}),-Market!${m}${MROW['opex']})")
                put(c, "t_rev", f"=IF({sa}<>0,{sa},-{c}{a('t_cost')}/$D${a('cir')})")
                put(c, "t_np", f"=IF({ni}<>0,{ni},Market!${m}${MROW['ni_base']})")
            else:
                put(c, "t_cost", f"=IF(AND({sa}<>0,{op}<>0),-({sa}-{op}),{prev}{a('t_cost')}*(1+$D${a('cost_g')}))")
                put(c, "t_rev", f"=IF({sa}<>0,{sa},{prev}{a('t_rev')}*(1+$D${a('cost_g')}))")
                put(c, "t_np", f"=IF({ni}<>0,{ni},{prev}{a('t_np')}*(1+$D${a('np_g')}))")
            put(c, "t_phase", f"={c}{a('phase')}")
            put(c, "t_cost_syn", f"=-{c}{a('t_cost')}*$D${a('syn_cost')}*{c}{a('t_phase')}")
            put(c, "t_rev_syn", f"={c}{a('t_rev')}*$D${a('syn_rev')}*{c}{a('t_phase')}")
            # adjustments
            put(c, "a_np", f"={c}{a('b_np')}")
            put(c, "a_tnp", f"=Calc!${X}$4*{c}{a('t_np')}")
            put(c, "a_cs", f"={c}{a('t_cost_syn')}*(1-$D${a('tax')})")
            if k == 0:
                put(c, "a_rs", f"=-$D${a('restr')}*(-$D${a('t_cost')}*$D${a('syn_cost')})*(1-$D${a('tax')})")
            else:
                put(c, "a_rs", 0)
            put(c, "a_rv", f"={c}{a('t_rev_syn')}*(1-$D${a('tax')})")
            put(c, "a_fin", f"=-Calc!${X}$74*1000*{c}{a('dfr')}*(1-$D${a('tax')})")
            put(c, "a_eff", f"=SUM({c}{a('a_cs')}:{c}{a('a_fin')})")
            put(c, "a_tot", f"={c}{a('a_np')}+{c}{a('a_tnp')}+{c}{a('a_eff')}")
            # shares
            put(c, "s_acq", f"={c}{a('b_sh')}")
            put(c, "s_new", f"=$D${a('newsh')}")
            put(c, "s_tot", f"={c}{a('s_acq')}+{c}{a('s_new')}")
            # capital
            ret = f"(1-$D${a('payout')})"
            if k == 0:
                put(c, "c_acq", "=Calc!$D$20", "link")
                put(c, "c_cum", f"=({c}{a('a_tnp')}+{c}{a('a_eff')})/1000*{ret}")
                put(c, "r_a", "=Calc!$D$8*(1+Calc!$D$65)", "link")
                put(c, "r_t", f"=Calc!${T}$8*(1+Calc!${T}$65)", "link")
                put(c, "bs_ta", f"=Calc!{X}7", "link")
                put(c, "bs_loans", f"=P3DH!$D{npl}+P3DH!$D{perf}+P3DH!{T}{npl}+P3DH!{T}{perf}", "link")
                put(c, "v_tn_a", "=Calc!$D$30", "link")
            else:
                put(c, "c_acq", f"={prev}{a('c_acq')}+{c}{a('b_np')}/1000*{ret}")
                put(c, "c_cum", f"={prev}{a('c_cum')}+({c}{a('a_tnp')}+{c}{a('a_eff')})/1000*{ret}")
                put(c, "r_a", f"={prev}{a('r_a')}*(1+$D${a('rwa_g_a')})")
                put(c, "r_t", f"={prev}{a('r_t')}*(1+$D${a('rwa_g_t')})")
                put(c, "bs_ta", f"={prev}{a('bs_ta')}*{c}{a('r_new')}/{prev}{a('r_new')}")
                put(c, "bs_loans", f"={prev}{a('bs_loans')}*{c}{a('r_new')}/{prev}{a('r_new')}")
                put(c, "v_tn_a", f"={prev}{a('v_tn_a')}+{c}{a('b_np')}/1000*{ret}")
            put(c, "c_gw", f"=Calc!${T}$20-Calc!${X}$73", "link")
            put(c, "c_sh", f"=Calc!${X}$75", "link")
            put(c, "c_oth", f"=Calc!${X}$85-Calc!${X}$84-Calc!${X}$4*Calc!${X}$79-Calc!${X}$83+Calc!${X}$67", "link")
            put(c, "c_new", f"=SUM({c}{a('c_acq')}:{c}{a('c_cum')})")
            put(c, "r_opt", f"={c}{a('rwa_opt')}")
            put(c, "r_pa", f"={c}{a('rwa_pa')}")
            put(c, "r_new", f"=SUM({c}{a('r_a')}:{c}{a('r_pa')})")
            put(c, "c_ratio", f"={c}{a('c_new')}/{c}{a('r_new')}")
            put(c, "c_req", f"=Calc!${X}$100", "link")
            put(c, "c_head", f"=({c}{a('c_ratio')}-{c}{a('c_req')})*10000")
            # valuation
            put(c, "v_tn_pf", f"={c}{a('v_tn_a')}+(Calc!${X}$30-Calc!$D$30)+{c}{a('c_cum')}")
            put(c, "v_tps_a", f"={c}{a('v_tn_a')}*1000/{c}{a('s_acq')}")
            put(c, "v_tps_pf", f"={c}{a('v_tn_pf')}*1000/{c}{a('s_tot')}")
            put(c, "v_tps_imp", f"={c}{a('v_tps_pf')}/{c}{a('v_tps_a')}-1")
            put(c, "v_pe", f"=$D${a('price')}/{c}{a('e_eps1')}")
            put(c, "v_rote", f"={c}{a('a_tot')}/({c}{a('v_tn_pf')}*1000)")
            put(c, "v_ptnav", f"=$D${a('price')}*{c}{a('s_tot')}/1000/{c}{a('v_tn_pf')}")
            # earnings impact
            put(c, "e_eps0", f"={c}{a('b_eps')}")
            put(c, "e_eps1", f"={c}{a('a_tot')}/{c}{a('s_tot')}")
            put(c, "e_imp", f"={c}{a('e_eps1')}/{c}{a('e_eps0')}-1")
            put(c, "e_lab", f'=IF({c}{a("e_imp")}>=0,"Accretive","Dilutive")')
            put(c, "e_roi", f"=({c}{a('a_tnp')}+{c}{a('a_cs')}+{c}{a('a_rv')}+{c}{a('a_fin')})/(Calc!${X}$73*1000)")
    ws.column_dimensions["A"].width = 2
    ws.column_dimensions["B"].width = 2
    ws.column_dimensions["C"].width = 62
    for c in YC:
        ws.column_dimensions[c].width = 13
    ws.freeze_panes = "D4"


def build_model_sheets(wb: openpyxl.Workbook, banks: list[ma_data.BankData], deals: list[dict], g: dict, market: dict) -> None:
    b = Builder(wb)
    calc = wb.create_sheet("Calc")
    p3 = wb.create_sheet("P3DH")
    mk = wb.create_sheet("Market")
    pr = wb.create_sheet("Peers")
    write_p3dh(p3, banks, b.rows)
    write_market(mk, market)
    write_peers(pr, market)
    write_calc(calc, b, banks, deals, g)
    write_merger(wb.create_sheet("Merger"), b, deals, market)


ORIGINAL_INPUTS: dict[str, Any] = {
    "N2": 0.25, "N3": 14, "N6": 0, "N16": 1, "D3": 0.03, "D41": 3.1, "D42": 2.7, "D4": 0.025,
    "D7": 80, "E7": 30, "F7": 30, "G7": 27, "D8": 41.5, "E8": 11, "F8": 10.5, "G8": 12.3,
    "D9": 1.1, "E9": 0.2, "F9": 0.5, "G9": 0.25, "D20": 7.2, "E20": 1.7, "F20": 2.2, "G20": 2.17,
    "D22": 0.5, "E22": 0.3, "F22": 0.22, "G22": 0, "D23": 1.1, "E23": 0.43, "F23": 0.3, "G23": 0, "D24": 3.1, "E24": 0.65, "F24": 0.95, "G24": 0,
    "D30": 8.3, "E30": 2.4, "F30": 2.48, "G30": 2.7, "D48": 0.9, "D49": 17.5, "E32": 2 / 0.9, "F32": 4.8, "G32": 2.5,
    "E61": 0.25, "F61": 0.25, "G61": 0.25, "E62": 0.48, "F62": 0.38, "G62": 0.38,
}


def original_overrides() -> dict[tuple[str, str], Any]:
    """Cells of Calc that hold the typed inputs of the user workbook. Used to separate formula fixes from data changes."""
    return {("Calc", k): v for k, v in ORIGINAL_INPUTS.items()}


IMPACT_LINES = [
    (13, "ROCET1", "pct", "DHIJ"), (14, "ROCET1, change to NBG", "pct", "HIJ"), (15, "Synergies required (EUR bn)", "bn", "HIJ"), (20, "CET1 (EUR bn)", "bn", "HIJ"),
    (21, "CET1 ratio", "pct", "HIJ"), (26, "MREL ratio", "pct", "HIJ"), (27, "MREL needed (EUR bn)", "bn", "HIJ"), (33, "Average market cap (EUR bn)", "bn", "HIJ"),
    (34, "P/TBV", "x", "HIJ"), (48, "Number of shares (bn)", "0.0000", "HIJ"), (49, "Implied price (EUR)", "eps", "HIJK"), (50, "Upside for NBG holders", "pct", "HIJK"),
    (52, "EPS at target CET1 (EUR)", "eps", "HIJK"), (53, "EPS upside", "pct", "HIJK"), (56, "Dilution total", "pct", "HIJK"),
]


def impact_table(wb: openpyxl.Workbook) -> list[list[Any]]:
    model = ma_sheet.Model.from_openpyxl(wb)
    base = model.run()
    alt = model.run(original_overrides())
    rows = []
    for r, text, kind, cols in IMPACT_LINES:
        for c in cols:
            o = base.number("Original (user)", f"{c}{r}")
            rows.append([text, base.get("Calc", f"{c}6"), o, alt.number("Calc", f"{c}{r}"), base.number("Calc", f"{c}{r}"), kind])
    return rows


REVIEW: list[tuple[str, str, str, str]] = [
    ("H48:J48", "Formula error", "New shares are the price paid in shares divided by NBG market cap in EUR bn. This gives a ratio, not a number of shares. It overstates new shares by 1/0.9 (11%).",
     "New shares = share of the price paid in shares / NBG share price (row 48)."),
    ("H3, J3", "Formula error", "Only I3 has a share split. For BIL, 90% cash leaves 10% in shares, but the model issued no shares. For HCOB the split was also blank.",
     "Shares = 1 - cash for every deal (row 3)."),
    ("K57:K58", "Formula error", "The formulas point at H32 and H37 (a combined bank and an empty cell). They have no meaning for the NBG case.", "Removed for column K."),
    ("K33, K12", "Formula error", "The case 'NBG at 13% CET1' pays out the excess CET1 but keeps market cap (K33 typed 15.8) and profit. This makes a price gain from nothing.",
     "Market cap falls by the excess CET1 paid out (value in N6). Profit falls by the after-tax deposit income on it (K10). The price effect is 0%."),
    ("D13", "Formula error", "Deposit income on excess CET1 is removed without tax. H10 uses a tax factor of 0.75.", "One tax rate (N2) in both. The same adjustment applies to every column (only for positive excess CET1)."),
    ("H32:J32", "Formula error", "Market cap by P/TBV uses typed weights 0.8 and 0.2 for every deal. It also multiplies the P/TBV at 13% by tangible equity at the actual CET1 (row 30), not at 13%.",
     "Weights follow the tangible equity at 13% (row 45). The base is row 45."),
    ("H31:J32, K33", "Method", "Cash paid leaves the group. It reduces CET1 and tangible equity one for one, because only new shares add equity. The original ignored this in market cap. "
     "Method P/TBV: P/TBV at 13% times tangible equity at 13% does not change when cash is paid. Method P/E: the lost deposit income is capitalised at the P/E, which removes only about 25% of the cash. A cash deal looked almost free.",
     "Excess CET1 is valued at N6 (1.0 = book value) in both methods. The P/E method uses profit without income on excess CET1 and adds the excess CET1 (row 31). P/TBV method: row 32. N3 is the P/E of NBG on the same basis. Set N6 to 0 for the original method."),
    ("H4:J4 with H38:J38", "Method", "Profit counts at the stake (90%). Price, cash paid, CET1 and RWAs count at 100%.",
     "Price = stake x valuation x (1 + premium). Minority interest in CET1 (rows 84 and 85). Return metrics use RWAs attributable to NBG holders (row 88)."),
    ("H7:J7", "Method", "Size adds the two balance sheets. Cash paid leaves. The intangible assets of the target go. New goodwill comes.", "Row 7 includes these three items."),
    ("H22:J24", "Method", "Text strings such as '0.8 (-0.2)' cannot feed other cells. The AT1 and Tier 2 requirement used the NBG P2R only.",
     "Numeric rows 22 to 24. Surplus rows 122 to 124 use the pro-forma P2R (row 92)."),
    ("F26:G26, I25:J26, G22:G24", "Missing cells", "MREL rows are empty for some banks and for two combinations.", "All filled from P3DH (KM1 and KM2). HCOB files no KM2, so its MREL line has capital only."),
    ("C10, C17", "Label", "C10 says 'at D2' but the formula uses D3. C17 says '14%' but D1 is 13%.", "Labels read the inputs."),
    ("H11:J11", "Typed numbers", "Integration cost has typed numbers inside the formula (0.48, 0.38, 0.38 and 0.75). They are probably pasted from other workbooks, and the source is not in this file. BoC and HCOB have the same opex.",
     "Inputs: N4 and N5. Row 61 (tax rate) and row 62 (opex) are Bloomberg values for every bank (sheet Market). See the table of typed numbers below."),
    ("D32, E32, E30, F30, H31", "Typed numbers", "Typed arithmetic: 0.9*17.5, 2/0.9, 2.7-0.3, 2.7-0.22, and 14 in the P/E formula. They look like values from other workbooks, and the source is not in this file.",
     "NBG market cap = shares x price (Bloomberg). Tangible equity from CC1. P/E is input N3 (default: the P/E of NBG without excess CET1). BIL and HCOB: see G30 and G32."),
    ("E30, F30", "Data", "BIL and BoC 'tangible equity' is accounting equity less AT1. It does not deduct intangible assets.", "Tangible equity = CC1 row 6 less row 8 (P3DH)."),
    ("E24", "Data", "BIL senior is 0.65. P3DH gives EUR 2.58bn: KM2 own funds and eligible liabilities (4.89) less own funds (2.30). KM2 and TLAC1 count only items after deductions, so the 2.58bn is MREL-eligible by definition. "
     "It is 0.48bn senior non-preferred (subordinated) and 2.11bn senior preferred. Senior preferred counts only inside the cap of CRR Article 72b(3). BoC: 0.96bn, all senior preferred. NBG: 3.12bn, all senior preferred.",
     "P3DH values. Rows 154 and 155 split them. Row 157 to 159 test the subordination requirement (none is filed for these banks)."),
    ("G30, G32", "Data", "HCOB tangible equity is 2.7 and the valuation 2.5 (0.926x). P3DH gives 3.71 for tangible equity (CC1) and 2.18 for CET1. The gap of EUR 1.5bn is CET1 deductions in CC1.",
     "Tangible equity from CC1. A bank without a market cap is worth the median multiple of the k listed European banks (P3DH) with the closest return, on tangible equity and on CET1 (rows 160 to 167, sheet Peers). "
     "A linear fit of P/TBV on RoTE gives BIL a higher value than the nearest peers: a few banks with a high return and a high multiple raise the line (sheet Peers shows the fit for information). "
     "Your 0.926x has no source in the file. For BIL, CET1 is 21% below tangible equity because of other CET1 deductions (EUR 0.45bn), so the CET1 basis gives a lower value."),
    ("D7:D30", "Data", "NBG inputs are rounded or older: size 80 (P3DH 83.4), RWAs 41.5 (42.3), CET1 7.2 (7.18), Tier 2 1.1 (1.02), tangible equity 8.3 (8.26).", "P3DH values at 30/06/2026."),
    ("D48, D49", "Data", "Shares 0.9bn and price 17.5. Bloomberg gives the current number of shares and the live price.", "Linked to sheet Market."),
    ("D3", "Assumption checked", "DFR 3% for every year. The ECB deposit rate was 2.00% until 16 June 2026, 2.25% until 15 September, and 2.50% since. The ESTR OIS curve gives the average of each calendar year "
     "(sheet Market: the realised path plus forwards for the current year, forwards for later years). 3% is near the averages of the later years, but it is too high for the current year.",
     "D3 is the average of the year in N15 (default 2027E). Sheet Merger uses the average of each year. Sheet Market shows the curve, the path, and the average of each year, half year, and quarter."),
    ("0.75 in H10, H11", "Assumption", "Tax of 25% for every bank (the factor 0.75).", "N2 and row 61 link to the statutory tax rate of each bank in Bloomberg (sheet Market). Compare them with your rates of row 61 in the original sheet (BIL 23.87%, BoC 15%, HCOB 32%)."),
    ("D9:G9", "Assumption", "Profits 1.1 (NBG) and 0.5 (BoC) have no year. Bloomberg gives the last-year profit and the consensus for the next years (sheet Market). The workbook looks forward, so the profit must belong to a named year.",
     "NBG, BoC, and every bank with consensus: consensus of the year in N15 (green cells). BIL and HCOB have no consensus. They use the net income of the last 12 months in Bloomberg (sheet Market). "
     "Compare it with your 0.20 and 0.25."),
    ("D29", "Assumption", "Waived dividend 0.8. Compare it with the consensus dividend (sheet Market, rows 42 to 45: DPS) times the shares (row 11).", "Kept. Sheet Market shows the references."),
    ("D41:D42, H28:J29", "Data", "P3DH has DTA data. CC2 shows NBG deferred tax assets of EUR 3.58bn at 30/06/2026. EUR 3.18bn do not rely on future profitability (the DTCs). "
     "The other 0.40bn matches CC1 row 75 (0.399bn, below the threshold, 250% risk weight, counted in CET1). CC1 shows only EUR 2m deducted. "
     "Your 3.1 and 2.7 have the same gap of 0.4, so they are probably an earlier date of the same split. The lever (D41 - D42 = 0.4) adds these DTAs to CET1 a second time.",
     "D41 and D42 link to P3DH. The lever has a switch (N16, default 0). Set N16 to 1 for the original scenario."),
    ("D2", "Assumption checked", "MREL target 29%. The KM2 requirement of NBG with the combined buffer is 26.7%. The target has a cushion of 2.3 points.", "Kept. Row 120 shows the requirement."),
    ("D1", "Assumption checked", "CET1 target 13%. The CET1 requirement of NBG (trigger of MDA) is 9.70%. The target is 3.3 points above it.", "Kept. Row 100 shows the requirement."),
    ("D4", "Assumption checked", "P2R of NBG 2.5% equals KM1 (row 7d) at 30/06/2026.", "Linked to P3DH."),
    ("D124", "Limitation", "The senior need counts all CET1 towards MREL. CET1 used for the combined buffer does not count towards MREL.", "Not changed. The senior need is too low by the combined buffer."),
    ("M6:Y40 (picture)", "Reference", "The original sheet holds a picture: Figure 89, a hypothetical ETE/BOCH merger model for 2026E to 2029E. It is the layout for a multi-year model.",
     "Sheet Merger follows the picture for each deal. The picture stays on sheet Original (user)."),
    ("Merger", "Data", "Bloomberg consensus covers NBG for 4 years (few brokers in the last year) and Bank of Cyprus for 3 years. BIL and HCOB have no consensus.",
     "A year without consensus grows from the year before. BIL and HCOB use the net income of the last 12 months and the opex of Bloomberg with the growth inputs of each deal."),
    ("E9:G9, E32:G32, E61:G62", "Data policy", "Profit, valuation, opex, and tax rate of BIL and HCOB were typed numbers without a source in the file.",
     "Every value comes from P3DH or Bloomberg. The link is the LEI of the bank. Only the deal terms (cash share, stake, premium) are inputs. Row 152 checks that every bank has a profit, an opex, a tax rate, and a valuation."),
    ("E37:G37", "Lever", "The premium of BIL (-10%) and HCOB (0%) was set against the typed valuation of 0.926x tangible equity.",
     "BIL and HCOB default to 0%. BoC keeps 15% over its market cap. Change the premium in row 37."),
    ("H22:J24, rows 169 to 201", "Method", "The original had no issuance need. Requirements of the combination were not weighted by RWAs, and the shortfall of each layer was not turned into an amount to issue.",
     "Rows 173 to 177 weight the requirement of each bank by its RWAs. Rows 178 to 195 give the amounts to issue for CET1, AT1, Tier 2, and eligible liabilities, at the requirements and at the targets D1 and D2. "
     "CET1, AT1, and Tier 2 that are issued also count for the MREL. Rows 196 to 198 show how much the capital structure of the target reduces the need. N19 sets the share of its instruments that count."),
    ("N20 to N22, rows 177 and 182", "Assumption", "NBG files a subordination requirement of 0% (KM2 row EU-8), and BIL, Eurobank, Piraeus, and Bank of Cyprus leave it empty. The combination of NBG and BIL has EUR 113bn of assets. "
     "All 22 banks above EUR 250bn and 16 of 19 banks of EUR 100bn to 250bn that file KM2 report a requirement: median 19.1% and 15.9% of TREA, and 13.50% for AIB, Bank of Ireland, Erste, BNP Paribas, Rabobank, and Belfius.",
     "Without a filed requirement, a combination of N21 (EUR 100bn) or more gets N20 (13.5% of TREA) plus the combined buffer, and not less than N22 (5%) of the leverage exposure. "
     "I could not check the legal text here. The rule behind 13.5% is probably the one for banks above EUR 100bn: verify it with the resolution authority. Set N20 to 0 to remove the assumption."),
    ("rows 203 to 222", "Method", "The original had no AT1 and Tier 2 buckets.", "The buckets are the Pillar 1 share plus the share of the P2R that CRR Article 104a allows to meet with AT1 (18.75%) and Tier 2 (25%). "
     "The P2R is weighted by RWAs. Rows 212 and 213 show the room that is left, and rows 216 to 222 the instruments to issue, cheapest first: AT1 and Tier 2 within the buckets, then senior non-preferred for the subordination need, then senior preferred."),
    ("N19", "Limitation", "The AT1, Tier 2, and eligible liabilities of a target count in the group in full. In practice instruments of a subsidiary count at group level in part (CRR Articles 83 to 88), "
     "and as external MREL only if the subsidiary is a resolution entity. Otherwise they are internal MREL.", "N19 (default 100%). Set it lower to test. P3DH shows no AT1 bond for BIL in Bloomberg, but 300m of AT1 in TLAC1."),
    ("H4, E37", "Lever", "The stake in BIL is 90% because the State of Luxembourg holds 10% and does not sell. Price = stake x valuation x (1 + premium), so a premium of -10% on top of a stake of 90% counts the 10% twice.",
     "Stake 90% (H4). Premium 0%. Use the premium only for a real price difference."),
]


TYPED_META = {
    "D1": ("CET1 target of NBG", "Scenario lever. Kept."), "D2": ("MREL target of NBG", "Scenario lever. Kept."),
    "D3": ("Deposit rate (DFR)", "Replaced by the OIS-based average of the analysis year (sheet Market)."), "D4": ("P2R of NBG", "Linked to P3DH (KM1)."),
    "H2": ("Cash share, deal 1", "Lever. Kept."), "I2": ("Cash share, deal 2", "Lever. Kept."), "J2": ("Cash share, deal 3", "Lever. Kept."),
    "I3": ("Share part, deal 2", "Formula: 1 - cash share."), "H4": ("Stake, deal 1", "Lever. Kept."), "I4": ("Stake, deal 2", "Lever. Kept."), "J4": ("Stake, deal 3", "Lever. Kept."),
    "D7": ("Total assets NBG", "P3DH."), "E7": ("Total assets BIL", "P3DH."), "F7": ("Total assets BoC", "P3DH."), "G7": ("Total assets HCOB", "P3DH."),
    "D8": ("RWAs NBG", "P3DH (KM1)."), "E8": ("RWAs BIL", "P3DH (KM1)."), "F8": ("RWAs BoC", "P3DH (KM1)."), "G8": ("RWAs HCOB", "P3DH (KM1)."),
    "D9": ("Profit NBG", "Bloomberg consensus of the analysis year."), "E9": ("Profit BIL", "Bloomberg: net income of the last 12 months (no consensus)."), "F9": ("Profit BoC", "Bloomberg consensus of the analysis year."),
    "G9": ("Profit HCOB", "Bloomberg: net income of the last 12 months (no consensus)."),
    "D20": ("CET1 NBG", "P3DH (KM1)."), "E20": ("CET1 BIL", "P3DH (KM1)."), "F20": ("CET1 BoC", "P3DH (KM1)."), "G20": ("CET1 HCOB", "P3DH (KM1)."),
    "D22": ("AT1 NBG", "P3DH: Tier 1 less CET1."), "E22": ("AT1 BIL", "P3DH."), "F22": ("AT1 BoC", "P3DH."),
    "D23": ("Tier 2 NBG", "P3DH: total capital less Tier 1."), "E23": ("Tier 2 BIL", "P3DH."), "F23": ("Tier 2 BoC", "P3DH."),
    "D24": ("Senior NBG", "P3DH: KM2 less own funds."), "E24": ("Senior BIL", "P3DH: KM2 less own funds."), "F24": ("Senior BoC", "P3DH: KM2 less own funds."),
    "D29": ("Waived dividend", "Lever. Kept. Reference on sheet Market."), "D30": ("Tangible equity NBG", "P3DH: CC1 row 6 less row 8."), "G30": ("Tangible equity HCOB", "P3DH: CC1 row 6 less row 8."),
    "F32": ("Market cap BoC", "Bloomberg."), "G32": ("Valuation HCOB", "Median multiple of the nearest listed peers x P3DH equity (rows 160 to 167)."),
    "E37": ("Premium, deal 1", "Lever. Kept."), "F37": ("Premium, deal 2", "Lever. Kept."), "G37": ("Premium, deal 3", "Lever. Kept."),
    "D41": ("Total DTCs", "P3DH (CC2): total DTAs."), "D42": ("DTC in CET1", "P3DH (CC2): DTAs that do not rely on future profitability."),
    "D48": ("Shares NBG (bn)", "Bloomberg."), "D49": ("Price NBG", "Bloomberg."), "K33": ("Market cap NBG after payout", "Formula: market cap less excess CET1 paid out."),
    "E30f": ("Tangible equity BIL: 2.7 - 0.3", "P3DH: CC1 row 6 less row 8."), "F30f": ("Tangible equity BoC: 2.7 - 0.22", "P3DH: CC1 row 6 less row 8."),
    "D32f": ("Market cap NBG: 0.9 x 17.5", "Shares x price (Bloomberg)."), "E32f": ("Valuation BIL: 2 / 0.9", "Median multiple of the nearest listed peers x P3DH equity (rows 160 to 167)."),
    "H10": ("Tax factor 0.75 on lost deposit income", "(1 - tax rate N2)."), "H11": ("Integration: 20%/5 x opex x 0.75", "Inputs N4, N5, opex and tax rate per bank."),
    "H31": ("P/E 14 in the market cap formula", "N3 (P/E of NBG without excess CET1)."), "H32": ("Weights 0.8 and 0.2 for NBG and the target", "Weights by tangible equity at the CET1 target."),
    "H22": ("8% and 1.5/8: AT1 requirement", "Regulatory constants in N7 to N14."), "H23": ("8% and 2/8: Tier 2 requirement", "Regulatory constants in N7 to N14."),
    "H24": ("8% and 3.5/8: AT1 + Tier 2 requirement", "Regulatory constants in N7 to N14."),
}


def typed_numbers() -> list[list[Any]]:
    """Every typed number in the original sheet: constants and numbers inside formulas."""
    if not ORIGINAL.exists():
        return []
    ws = openpyxl.load_workbook(ORIGINAL).active
    rows: list[list[Any]] = []
    for row in ws.iter_rows():
        for c in row:
            v = c.value
            if v is None or (isinstance(v, str) and not v.startswith("=")) or isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                meta = TYPED_META.get(c.coordinate, ("", ""))
                rows.append([c.coordinate, "constant", v, meta[0], meta[1]])
                continue
            lits = [t for k, t in ma_sheet.tokenize(v[1:]) if k == "num" and float(t) not in (0.0, 1.0, 100.0)]
            if lits:
                key = c.coordinate if c.coordinate in TYPED_META else (c.coordinate + "f" if c.coordinate + "f" in TYPED_META else c.coordinate)
                meta = TYPED_META.get(key) or TYPED_META.get("H" + str(c.row), ("", ""))
                rows.append([c.coordinate, "inside formula", v, meta[0], meta[1]])
    return rows


def write_review(ws, impact: list[list[Any]], typed: list[list[Any]] | None = None) -> None:
    ws["A1"] = "Review of the sheet Original (user). Each finding, and what Calc does."
    ws["A1"].font = BOLD
    for i, h in enumerate(["#", "Where", "Type", "Finding", "Treatment in Calc"], start=1):
        c = ws.cell(row=3, column=i, value=h)
        c.font, c.fill = HEAD_FONT, HEAD
    for n, (where, kind, finding, fix) in enumerate(REVIEW, start=1):
        r = 3 + n
        for i, v in enumerate([n, where, kind, finding, fix], start=1):
            c = ws.cell(row=r, column=i, value=v)
            c.alignment = Alignment(wrap_text=True, vertical="top")
    r0 = 3 + len(REVIEW) + 3
    ws.cell(row=r0 - 1, column=1, value="Effect of the corrections").font = BOLD
    heads = ["Line", "Deal", "Original", "Formulas corrected, original inputs", "Formulas corrected, P3DH and market data"]
    for i, h in enumerate(heads, start=1):
        c = ws.cell(row=r0, column=i + 1, value=h)
        c.font, c.fill = HEAD_FONT, HEAD
        c.alignment = Alignment(wrap_text=True)
    for j, (text, deal, o, a, c_, kind) in enumerate(impact, start=1):
        r = r0 + j
        ws.cell(row=r, column=2, value=text)
        ws.cell(row=r, column=3, value=deal)
        for k, v in enumerate([o, a, c_]):
            cell = ws.cell(row=r, column=4 + k, value=None if v != v else v)
            cell.number_format = FORMATS.get(kind, kind)
    if typed:
        r1 = r0 + len(impact) + 4
        ws.cell(row=r1 - 1, column=1, value="Typed numbers of the original sheet").font = BOLD
        for i, h in enumerate(["Cell", "Kind", "Content", "Meaning", "Treatment in Calc"], start=2):
            c = ws.cell(row=r1, column=i - 1 if False else i - 1, value=h)
            c.font, c.fill = HEAD_FONT, HEAD
        for j, row in enumerate(typed, start=1):
            for i, v in enumerate(row, start=1):
                ws.cell(row=r1 + j, column=i, value=("formula: " + v) if isinstance(v, str) and v.startswith("=") else v)
    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 26
    ws.column_dimensions["C"].width = 20
    ws.column_dimensions["D"].width = 80
    ws.column_dimensions["E"].width = 60
    ws.column_dimensions["F"].width = 28


GUIDE = [
    "M&A calc, version 2. NBG with up to three target banks.",
    "",
    "Sheets",
    "Calc: the calculation for one year (cell N15: 1 = 2026E ... 4 = 2029E; default 2027E). Rows 1 to 58 keep the cells of the original sheet. Green rows (column C) are new. Every number is a formula.",
    "Merger: the four-year model (2026E to 2029E) for each deal. It follows Figure 89 (the picture in the original sheet): synergies, restructuring, financing, capital, RWAs, profit, EPS, TNAV per share, return on investment.",
    "P3DH: data of the EBA Pillar 3 Data Hub (clean layer): capital, buffers, leverage, liquidity, MREL (KM2), deferred tax assets (CC2, CC1), intangible assets, IRRBB.",
    "Market: Bloomberg data from the database, by LEI: price, shares, market cap, profit, consensus, opex, tax rate, the ESTR OIS curve, and the average deposit rate per year, half year, and quarter. Do not publish this sheet.",
    "Peers: listed European banks of P3DH with P/TBV, P/CET1, and returns. The median multiple of the nearest peers values a bank that has no market cap. Do not publish this sheet.",
    "Review: findings about the original sheet and what Calc does. A table shows the effect of the corrections.",
    "Original (user): the sheet that you gave, unchanged.",
    "",
    "Colours",
    "Blue on yellow: an input that you can change. Green font: a link to P3DH or Market. Black: a formula.",
    "",
    "How to use",
    "Change the blue cells. The Streamlit page M&A scenario uses the same formulas and shows the same numbers.",
    "To use other targets, build the file again: python scripts/build_ma_workbook.py --targets name1 name2 name3.",
    "To refresh data: run scripts/refresh_p3dh.py for P3DH. Run scripts/pull_bloomberg.py (Bloomberg) for the sheets Market and Peers.",
    "",
    "Basis",
    "The model shows the position on the day the deal closes and the effect on the first full year. It has no later years.",
    "P3DH has no profit, price or valuation. They come from Bloomberg (sheet Market). A bank without listed shares (BIL, HCOB) is valued with its nearest listed peers (sheet Peers, rows 160 to 167 of Calc). Row 37 (premium) and the cash share and stake are your levers.",
    "Amounts in EUR bn. Ratios are fractions shown as percentages.",
]


def write_guide(ws) -> None:
    for i, line in enumerate(GUIDE, start=1):
        ws.cell(row=i, column=1, value=line)
        if line in ("Sheets", "Colours", "How to use", "Basis") or i == 1:
            ws.cell(row=i, column=1).font = BOLD
    ws.column_dimensions["A"].width = 140


def finish_workbook(wb: openpyxl.Workbook) -> None:
    impact = impact_table(wb)
    guide, review = wb.create_sheet("Guide"), wb.create_sheet("Review")
    write_guide(guide)
    write_review(review, impact, typed_numbers())
    order = ["Guide", "Review", "Calc", "Merger", "P3DH", "Market", "Peers", "Original (user)"]
    wb._sheets = [wb[n] for n in order]
    wb.active = 2
    wb.calculation.fullCalcOnLoad = True


def apply_overrides(wb: openpyxl.Workbook, overrides: dict[tuple[str, str], Any]) -> None:
    """Write input values into the workbook. A cell whose value does not change keeps its formula or link."""
    run = ma_sheet.Model.from_openpyxl(wb).run()
    for (sheet, cell), v in overrides.items():
        cur = run.get(sheet, cell)
        if isinstance(v, str):
            same = v == cur
        else:
            same = isinstance(cur, (int, float)) and not isinstance(cur, bool) and abs(float(cur) - float(v)) <= 1e-9 * max(1.0, abs(float(cur)))
        if not same:
            wb[sheet][cell] = v
            wb[sheet][cell].font, wb[sheet][cell].fill = BLUE, INPUT_FILL


def build_workbook(banks: list[ma_data.BankData], deals: list[dict], g: dict, market: dict, with_original: bool = True,
                   overrides: dict[tuple[str, str], Any] | None = None) -> openpyxl.Workbook:
    """banks[0] is NBG, banks[1:4] are the targets."""
    assert len(banks) == 4 and len(deals) == 3
    if with_original and ORIGINAL.exists():
        wb = openpyxl.load_workbook(ORIGINAL)
        wb.active.title = "Original (user)"
    else:
        wb = openpyxl.Workbook()
        wb.active.title = "Original (user)"
    build_model_sheets(wb, banks, deals, g, market)
    if overrides:
        apply_overrides(wb, overrides)
    if with_original:
        finish_workbook(wb)
    return wb


def evaluate(wb: openpyxl.Workbook, overrides: dict[tuple[str, str], Any] | None = None) -> ma_sheet.Run:
    return ma_sheet.Model.from_openpyxl(wb).run(overrides)
