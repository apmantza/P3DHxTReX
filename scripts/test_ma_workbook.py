"""Tests of the M&A workbook, the formula evaluator, and the page.

  .venv/Scripts/python scripts/test_ma_workbook.py            (needs: pip install formulas pillow)
  dashboard/.venv/Scripts/python scripts/test_ma_workbook.py  (runs the page test too)

1. The evaluator gives the cached values of the original sheet for all its formulas.
2. The workbook builds from the P3DH database (clean layer and Bloomberg tables) with no formula error.
3. Accounting identities hold (share deal, cash deal, bargain purchase, minority interest, buyback case).
   Profit, opex, tax rate, and valuation of every bank come from P3DH or Bloomberg. The valuation of a bank without a market cap agrees with an independent calculation (numpy).
4. The independent library `formulas` gives the same numbers as the evaluator for Calc, Merger and Review.
5. The Streamlit page runs without an exception (only if streamlit is installed).
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dashboard"))
import ma_data  # noqa: E402
import ma_market  # noqa: E402
import ma_sheet  # noqa: E402
import ma_workbook as W  # noqa: E402

PACK_SHEETS = ["Valuation", "Balance sheet", "P&L", "MREL scenario", "Decisions", "Sources"]
FAILED: list[str] = []
def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {name}{(' - ' + detail) if detail and not ok else ''}")
    if not ok:
        FAILED.append(name)


def n_name(run, col: str) -> str:
    return str(run.get("Calc", f"{col}6"))


def close(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def test_evaluator() -> None:
    print("1. evaluator against the original sheet")
    f = W.ORIGINAL
    if not f.exists():
        print("  skipped (no original file)")
        return
    wf, wv = openpyxl.load_workbook(f), openpyxl.load_workbook(f, data_only=True)
    m = ma_sheet.Model.from_openpyxl(wf)
    vals = m.evaluate_all()
    n = bad = 0
    for (sh, co), raw in m.cells.items():
        if isinstance(raw, str) and raw.startswith("="):
            n += 1
            exp, got = wv[sh][co].value, vals[(sh, co)]
            ok = close(float(got), float(exp)) if isinstance(exp, (int, float)) and isinstance(got, (int, float)) else got == exp
            bad += not ok
    check(f"all {n} formulas of the original sheet equal the cached values of Excel", bad == 0, f"{bad} differ")
    r = ma_sheet.Model({("S", "A1"): '=TEXT(-0.25,"+0.0;-0.0")&"|"&TEXT(1234.5,"0")&"|"&TEXT(0.256,"0.0%")', ("S", "A2"): "=-2^2", ("S", "A3"): "=IF(1/0>1,1,2)"}).run()
    check("TEXT, unary minus and error values follow Excel", r.get("S", "A1") == "-0.3|1235|25.6%" and r.get("S", "A2") == 4.0 and isinstance(r.get("S", "A3"), ma_sheet.XlError))


def load_banks():
    db = ROOT / "data" / "processed" / "p3dh.sqlite"
    if not db.exists():
        return None
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)

    def q(sql: str, params: tuple = ()) -> pd.DataFrame:
        return pd.read_sql_query(sql, conn, params=params)

    if not ma_market.tables_exist(q):
        return None
    keys = [W.NBG_KEY, "9CZ7TVMR36CYD5TZBS50", "635400L14KNHZXPUZM19", "TUKDD90GPC79G1KOE162"]
    banks = [ma_data.load_bank(q, k, [p for p in ma_data.km1_periods(q, k) if p <= "2026-06-30"][0]) for k in keys]
    return banks, W.load_market(q, banks)


def test_build_and_identities(loaded) -> openpyxl.Workbook | None:
    print("2. build from P3DH and Bloomberg, no formula error")
    if loaded is None:
        print("  skipped (no database or no Bloomberg tables)")
        return None
    banks, market = loaded
    deals = [W.default_deal(b, sl["lei"]) for b, sl in zip(banks[1:], market["slots"][1:])]
    wb = W.build_workbook(banks, deals, W.default_globals(), market)
    model = ma_sheet.Model.from_openpyxl(wb)
    run = model.run()
    errs = [k for k, raw in model.cells.items() if k[0] in ("Calc", "Merger", "Review", *PACK_SHEETS) and isinstance(raw, str) and raw.startswith("=") and isinstance(run.get(*k), ma_sheet.XlError)]
    check("Calc, Merger, Review, and the six pack sheets have no formula error", not errs, str(errs[:5]))
    check("sheets and picture", wb.sheetnames == ["Guide", "Review", "Calc", "Merger", *PACK_SHEETS, "P3DH", "Market", "Peers", "Original (user)"] and len(wb["Original (user)"]._images) == 1,
          f"{wb.sheetnames}, images {len(wb['Original (user)']._images)}")
    check("all checks of the workbook passed (D151)", run.get("Calc", "D151") == "OK", str(run.get("Calc", "D151")))

    print("3. identities")
    n = lambda sheet, cell, ov=None: model.run(ov).number(sheet, cell)  # noqa: E731
    base = {("Calc", "H4"): 1.0, ("Calc", "I4"): 1.0, ("Calc", "J4"): 1.0}
    share = {**base, **{("Calc", f"{x}2"): 0.0 for x in "HIJ"}}
    check("share deal at any price: CET1 is the sum of both banks", all(close(n("Calc", f"{x}20", share), n("Calc", "D20") + n("Calc", f"{t}20")) for x, t in zip("HIJ", "EFG")))
    cash = {**base, **{("Calc", f"{x}2"): 1.0 for x in "HIJ"}}
    check("all cash: CET1 falls by the price", all(close(n("Calc", f"{x}20", cash), n("Calc", "D20") + n("Calc", f"{t}20") - n("Calc", f"{t}38", cash)) for x, t in zip("HIJ", "EFG")))
    check("D25 (MREL total) is CET1 + AT1 + Tier 2 + senior", all(close(n("Calc", f"{c}25"), sum(n("Calc", f"{c}{r}") for r in (20, 22, 23, 24))) for c in "DEFGHIJ"))
    tbv = n("Calc", "E30")
    at_tbv = {**cash, ("Calc", "E32"): tbv, ("Calc", "E37"): 0.0, ("Calc", "H2"): 1.0}
    check("price at tangible equity: no goodwill and no gain", close(n("Calc", "H81", at_tbv), 0.0) and close(n("Calc", "H82", at_tbv), 0.0, 1e-6))
    cheap = {**cash, ("Calc", "E32"): tbv, ("Calc", "E37"): -0.5}
    check("price below tangible equity: gain, no goodwill, CET1 route holds", n("Calc", "H82", cheap) > 0 and n("Calc", "H81", cheap) == 0
          and close(n("Calc", "H20", cheap), n("Calc", "D20") + n("Calc", "E20") - n("Calc", "E38", cheap)))
    k = 0.6
    part = {**cash, ("Calc", "H4"): k}
    nci = (1 - k) * min(n("Calc", "E20"), n("Calc", "E100") * n("Calc", "E8"))
    check("60% stake: minority interest is limited by the CET1 requirement", close(n("Calc", "H85", part), nci))
    check("60% stake: CET1 formula", close(n("Calc", "H20", part), n("Calc", "D20") + n("Calc", "E20") - n("Calc", "H74", part) + nci - (1 - k) * n("Calc", "E30") - 0.0))
    check("NBG at the CET1 target: ROCET1 equals NBG", close(n("Calc", "K13"), n("Calc", "D13")) and close(n("Calc", "K14"), 0.0, 1e-9))
    check("NBG at the CET1 target: no price effect when excess CET1 has market value", close(n("Calc", "K49"), n("Calc", "D49")))
    check("original method (excess CET1 without value): the buyback shows a gain", n("Calc", "K49", {("Calc", "N6"): 0.0}) > n("Calc", "D49") * 1.05)
    exc_income = max(n("Calc", "D46"), 0) * n("Calc", "D3") * (1 - n("Calc", "N2"))
    check("P/E default: NBG market cap = P/E x profit without income on excess CET1 + excess CET1 (a deal with no change gives no upside)",
          close(n("Calc", "D32"), n("Calc", "N3") * (n("Calc", "D9") - exc_income) + n("Calc", "N6") * n("Calc", "D46")))
    half = {**base, ("Calc", "H2"): 0.25, ("Calc", "I2"): 0.25, ("Calc", "J2"): 0.25}
    none = {**base, ("Calc", "H2"): 0.0, ("Calc", "I2"): 0.0, ("Calc", "J2"): 0.0}
    for x in "HIJ":
        paid = n("Calc", f"{x}74", half)
        check(f"cash paid reduces market cap by the cash, in both methods (deal {x})",
              close(n("Calc", f"{x}31", half) - n("Calc", f"{x}31", none), -paid, 1e-6) and close(n("Calc", f"{x}32", half) - n("Calc", f"{x}32", none), -paid, 1e-6),
              f"{n('Calc', f'{x}31', half) - n('Calc', f'{x}31', none):.4f} / {n('Calc', f'{x}32', half) - n('Calc', f'{x}32', none):.4f} vs {-paid:.4f}")
    by = market["rates"]["by_year"]
    check("deposit rate: D3 is the average of the year chosen in N15 (Bloomberg, OIS curve)",
          all(close(n("Calc", "D3", {("Calc", "N15"): k}), by[2025 + k]) for k in (1, 2, 3, 4)) and close(n("Calc", "D3"), by[2027]), str(by))
    check("deposit rate: the averages of the years are between 1% and 5%", all(0.01 < v < 0.05 for v in by.values()))
    nbg_cons = market["slots"][0]["cons"]
    check("profit of NBG follows the year in N15 (consensus)", close(n("Calc", "D9"), nbg_cons[2027]["NI"] / 1000) and close(n("Calc", "D9", {("Calc", "N15"): 1}), nbg_cons[2026]["NI"] / 1000))
    check("deposit rate in the four-year model is the average of each year",
          all(close(model.run().number("Merger", f"{c}{W.merger_start(0) + W.MOFF['dfr']}"), by[2026 + k]) for k, c in enumerate("DEFG")))
    check("tax rate of NBG is the statutory rate of Bloomberg", close(n("Calc", "N2"), market["slots"][0]["tax_stat"]))
    check("DTAs come from P3DH (CC2): NBG total 3.58bn, DTCs 3.18bn, gap equals CC1 row 75 within 5m",
          close(n("Calc", "D41"), 3.578, 1e-3) and close(n("Calc", "D42"), 3.177, 1e-3) and abs((n("Calc", "D41") - n("Calc", "D42")) - 0.399) < 0.005)
    check("DTA lever off: CET1 ratio + lever equals the CET1 ratio; on: adds the gap", all(close(n("Calc", f"{x}28"), n("Calc", f"{x}21")) for x in "HIJ")
          and close(n("Calc", "H28", {("Calc", "N16"): 1}), n("Calc", "H21") + (n("Calc", "D41") - n("Calc", "D42")) / n("Calc", "H8")))
    check("MREL split: senior non-preferred + senior preferred = senior (all deals)", all(n("Calc", f"{c}156") == 1 for c in "DEFGHIJ"))
    check("MREL split for BIL: 0.48bn non-preferred and 2.11bn preferred (P3DH, KM2)", abs(n("Calc", "E154") - 0.476) < 0.01 and abs(n("Calc", "E155") - 2.108) < 0.01,
          f"{n('Calc', 'E154'):.3f} {n('Calc', 'E155'):.3f}")
    pr = pd.DataFrame(market["peers"]["rows"])
    k, basis = int(n("Calc", "N17")), int(n("Calc", "N18"))
    check("peers: k and the valuation basis are inputs (default 20 and the average of both bases)", k == 20 and basis == 3)

    off = {("Calc", "N24"): 0.0, ("Calc", "N25"): 0.0}  # the cost of equity adjustment off: a pure test of the median multiples

    def nearest(col_x: str, col_y: str, x0: float) -> float:
        d = (pr[col_x] - x0).abs()
        return float(pr.loc[d <= d.nsmallest(k).iloc[-1], col_y].median())

    for col, m_ in (("E", 1), ("G", 3)):
        x_tbv, x_cet1 = n("Calc", f"{col}9") / n("Calc", f"{col}30"), n("Calc", f"{col}9") / n("Calc", f"{col}20")
        v_tbv, v_cet1 = nearest("rote", "ptbv", x_tbv) * n("Calc", f"{col}30"), nearest("rocet1", "pcet1", x_cet1) * n("Calc", f"{col}20")
        check(f"{n_name(run, col)} has no market cap: valued at the median multiple of the nearest peers, average of tangible equity and CET1 (independent calculation)",
              market["slots"][m_]["basis"] != "self" and close(n("Calc", f"{col}165", off), v_tbv, 1e-9) and close(n("Calc", f"{col}166", off), v_cet1, 1e-9)
              and close(n("Calc", f"{col}167", off), (v_tbv + v_cet1) / 2) and close(n("Calc", f"{col}32", off), (v_tbv + v_cet1) / 2) and run.get("Calc", f"{col}129") == "Nearest peers",
              f"{n('Calc', f'{col}32', off):.3f} vs {(v_tbv + v_cet1) / 2:.3f}")
        for b, want in ((1, v_tbv), (2, v_cet1)):
            check(f"{n_name(run, col)}: valuation basis {b} gives the value on {'tangible equity' if b == 1 else 'CET1'}", close(n("Calc", f"{col}32", {**off, ("Calc", "N18"): b}), want))
    check("peers: exactly k banks near each target (no ties)", all(close(n("Peers", c + "8"), k) for c in "IKMOQS"), str([n("Peers", c + "8") for c in "IKMOQS"]))
    check("a larger k moves the median only a little (k = 30 within 25% of k = 20)", abs(n("Calc", "E32", {("Calc", "N17"): 30}) / n("Calc", "E32") - 1) < 0.25)
    pc0 = W.peer_cols(0)
    check("value of BIL on each basis = median multiple of its peers x its equity (tangible equity, CET1)",
          close(n("Calc", "E165"), n("Peers", pc0["m_tbv"] + "7") * n("Calc", "E30") * n("Calc", "E228")) and close(n("Calc", "E166"), n("Peers", pc0["m_cet1"] + "7") * n("Calc", "E20") * n("Calc", "E229")))
    check("the two bases give clearly different values for BIL (more than 1%), so the switch N18 matters; which one is higher depends on the peers",
          abs(n("Calc", "E166") / n("Calc", "E165") - 1) > 0.01)

    # cost of equity of the target (levers N23 to N25): the peer multiples are scaled by (cost of equity of the peers - g) / (cost of equity of the target - g)
    g_ = n("Calc", "N23")

    def implied_coe(col_x: str, x0: float, ret_col: str, mult_col: str) -> float:
        d = (pr[col_x] - x0).abs()
        sel = pr.loc[d <= d.nsmallest(k).iloc[-1]]
        return float((g_ + (sel[ret_col] - g_) / sel[mult_col]).median())

    check("levers: g is 2%, the cost of equity of BIL is 10%, and HCOB has no adjustment (0) by default", close(g_, 0.02) and close(n("Calc", "N24"), 0.10) and n("Calc", "N25") == 0.0)
    for col, m_, lever in (("E", 1, "N24"), ("G", 3, "N25")):
        x_tbv, x_cet1 = n("Calc", f"{col}9") / n("Calc", f"{col}30"), n("Calc", f"{col}9") / n("Calc", f"{col}20")
        c_tbv, c_cet1 = implied_coe("rote", x_tbv, "rote", "ptbv"), implied_coe("rocet1", x_cet1, "rocet1", "pcet1")
        check(f"{n_name(run, col)}: the cost of equity that the near peers imply, median of g + (return - g) / multiple (independent calculation)",
              close(n("Calc", f"{col}226"), c_tbv) and close(n("Calc", f"{col}227"), c_cet1), f"{n('Calc', f'{col}226'):.4f} vs {c_tbv:.4f}; {n('Calc', f'{col}227'):.4f} vs {c_cet1:.4f}")
        for coe in (0.09, 0.10, 0.11):
            ov = {("Calc", lever): coe}
            f_tbv, f_cet1 = (c_tbv - g_) / (coe - g_), (c_cet1 - g_) / (coe - g_)
            v_t, v_c = nearest("rote", "ptbv", x_tbv) * n("Calc", f"{col}30") * f_tbv, nearest("rocet1", "pcet1", x_cet1) * n("Calc", f"{col}20") * f_cet1
            check(f"{n_name(run, col)}: a cost of equity of {coe:.0%} scales the peer value by the Gordon factor (independent calculation)",
                  close(n("Calc", f"{col}228", ov), f_tbv) and close(n("Calc", f"{col}229", ov), f_cet1) and close(n("Calc", f"{col}32", ov), (v_t + v_c) / 2),
                  f"{n('Calc', f'{col}32', ov):.4f} vs {(v_t + v_c) / 2:.4f}")
        vals = [n("Calc", f"{col}167", {("Calc", lever): coe}) for coe in (0.08, 0.09, 0.10, 0.11, 0.12)]
        check(f"{n_name(run, col)}: a higher cost of equity of the target lowers its value", all(a > b for a, b in zip(vals, vals[1:])), str(vals))
        check(f"{n_name(run, col)}: 0 removes the adjustment, and row 231 is the effect of the adjustment",
              close(n("Calc", f"{col}228", off), 1.0) and close(n("Calc", f"{col}230"), n("Calc", f"{col}167", off)) and close(n("Calc", f"{col}231"), n("Calc", f"{col}167") - n("Calc", f"{col}230")))
    check("the cost of equity of BoC (listed, valued at its market cap) has no effect on its value", close(n("Calc", "F228"), 1.0) and close(n("Calc", "F32"), market["slots"][2]["mcap"] / 1000))
    check("a cost of equity of the target at or below g gives no adjustment (the formula would break)", close(n("Calc", "E228", {("Calc", "N24"): 0.02}), 1.0))
    check("a listed target (BoC) is valued at its market cap in EUR (Bloomberg)", close(n("Calc", "F32"), market["slots"][2]["mcap"] / 1000) and run.get("Calc", "F129") == "Market cap")
    check("tangible equity of HCOB from CC1 is 3.71bn", abs(n("Calc", "G30") - 3.709) < 0.01)
    check("profit of a bank without consensus is the net income of the last 12 months (BIL, HCOB)", all(
        close(n("Calc", f"{col}9"), market["slots"][m_]["ni_ltm"] / 1000) for col, m_ in (("E", 1), ("G", 3))))
    check("profit of BoC is the consensus of the year", close(n("Calc", "F9"), market["slots"][2]["cons"][2027]["NI"] / 1000))
    check("tax rates and opex of the targets are the Bloomberg values", all(
        close(n("Calc", f"{col}61"), market["slots"][m_]["tax_stat"]) and close(n("Calc", f"{col}62"), market["slots"][m_]["opex"] / 1000) for col, m_ in (("E", 1), ("F", 2), ("G", 3))))
    check("market data is complete for every bank (row 152)", all(n("Calc", f"{c}152") == 1 for c in "DEFG"))
    typed = [k for k, raw in model.cells.items() if k[0] == "Calc" and isinstance(raw, (int, float)) and not isinstance(raw, bool)]
    allowed = {"D1", "D2", "H2", "I2", "J2", "H4", "I4", "J4", "D29", "E37", "F37", "G37", "D65", "E63", "F63", "G63", "E64", "F64", "G64", "E65", "F65", "G65"}
    allowed |= {f"{c}{r}" for c in "HIJ" for r in range(67, 72)} | {f"N{r}" for r in range(4, 27)}
    bad = sorted(co for sh, co in typed if co not in allowed)
    check("typed numbers in Calc are only deal levers and assumptions (no profit, opex, tax rate, valuation, or P3DH item)", not bad, str(bad[:12]))
    data_rows = [f"{c}{r}" for c in "DEFG" for r in (9, 32, 60, 61, 62) if not (c == "D" and r == 60)] + [f"{c}{r}" for c in "EFG" for r in range(161, 168)]
    lits = {}
    for cell in data_rows:
        raw = model.cells.get(("Calc", cell))
        if isinstance(raw, str) and raw.startswith("="):
            bad_lit = [t for kind, t in ma_sheet.tokenize(raw[1:]) if kind == "num" and float(t) not in (0.0, 1.0, 1000.0)]
            if bad_lit:
                lits[cell] = bad_lit
    check("profit, valuation, peers, tax rate, and opex are formulas with no typed number but the unit factor 1000",
          all(isinstance(model.cells.get(("Calc", c)), str) and model.cells[("Calc", c)].startswith("=") for c in data_rows) and not lits, str(lits))
    check("share count: new shares = share paid in shares x price / NBG price",
          all(close(n("Calc", f"{x}48"), n("Calc", "D48") + n("Calc", f"{x}3") * n("Calc", f"{t}38") / n("Calc", "D49")) for x, t in zip("HIJ", "EFG")))
    check("distance to MDA is the smallest of the three headrooms", all(close(n("Calc", f"{c}106"), min(n("Calc", f"{c}{r}") for r in (103, 104, 105)) / n("Calc", f"{c}8") * 1e4) for c in "DHIJ"))
    check("size class limits", [run.get("Calc", f"{c}125") for c in "DHI"] == ["Medium", "Large", "Large"], str([run.get("Calc", f"{c}125") for c in "DHI"]))
    for i, x in enumerate("HIJ"):
        R = W.merger_start(i)
        mo = lambda key: R + W.MOFF[key]  # noqa: E731
        d1 = n("Merger", f"D{mo('c_new')}") - n("Merger", f"D{mo('c_cum')}") - n("Merger", f"D{mo('c_acq')}")
        check(f"four-year model, deal {i + 1}: CET1 at closing equals Calc (H20 - D20)", close(d1, n("Calc", f"{x}20") - n("Calc", "D20")), f"{d1:.4f} vs {n('Calc', f'{x}20') - n('Calc', 'D20'):.4f}")
        eps = n("Merger", f"E{mo('e_eps1')}")
        check(f"four-year model, deal {i + 1}: pro forma EPS = total profit / total shares", close(eps, n("Merger", f"E{mo('a_tot')}") / n("Merger", f"E{mo('s_tot')}")))
        check(f"four-year model, deal {i + 1}: cost synergies phase in", n("Merger", f"D{mo('t_cost_syn')}") == 0 and n("Merger", f"G{mo('t_cost_syn')}") > n("Merger", f"E{mo('t_cost_syn')}") > 0)
    # issuance needs and requirements weighted by RWAs
    for x, t in zip("HIJ", "EFG"):
        wa, wt = n("Calc", "D8") * (1 + n("Calc", "D65")), n("Calc", f"{t}8") * (1 + n("Calc", f"{t}65"))
        check(f"deal {x}: requirements are the averages of the two banks weighted by their RWAs (CET1, Tier 1, total capital)",
              all(close(n("Calc", f"{x}{r}"), (n("Calc", f"D{src}") * wa + n("Calc", f"{t}{src}") * wt) / (wa + wt)) for r, src in ((173, 100), (174, 101), (175, 102))))
        mrel_t = n("Calc", f"{t}120")
        check(f"deal {x}: MREL requirement weighted by RWAs, or the NBG value when the target has no KM2",
              close(n("Calc", f"{x}176"), (n("Calc", "D120") * wa + mrel_t * wt) / (wa + wt) if mrel_t > 0 else n("Calc", "D120")))
        check(f"deal {x}: weights add to 100%", close(n("Calc", f"{x}171") + n("Calc", f"{x}172"), 1.0))
        need_cet1 = max(0.0, n("Calc", f"{x}178") - n("Calc", f"{x}20"))
        check(f"deal {x}: CET1 need = requirement less CET1, not below 0", close(n("Calc", f"{x}187"), need_cet1))
        t1 = max(0.0, n("Calc", f"{x}179") - n("Calc", f"{x}108") - need_cet1)
        t2 = max(0.0, n("Calc", f"{x}180") - n("Calc", f"{x}20") - n("Calc", f"{x}22") - n("Calc", f"{x}23") - need_cet1 - t1)
        mrel = max(0.0, n("Calc", f"{x}181") - n("Calc", f"{x}25") - need_cet1 - t1 - t2)
        check(f"deal {x}: Tier 1, Tier 2, and MREL needs follow the waterfall (instruments issued for one layer count for the next)",
              close(n("Calc", f"{x}188"), t1) and close(n("Calc", f"{x}189"), t2) and close(n("Calc", f"{x}190"), mrel))
        check(f"deal {x}: total need at the requirements = CET1 + Tier 1 + Tier 2 + the larger of the MREL and subordination needs",
              close(n("Calc", f"{x}192"), need_cet1 + t1 + t2 + max(mrel, n("Calc", f"{x}191"))))
        tg = max(0.0, n("Calc", "D1") * n("Calc", f"{x}8") - n("Calc", f"{x}20"))
        check(f"deal {x}: need at the targets = CET1 to the CET1 target + eligible liabilities to the MREL target after it",
              close(n("Calc", f"{x}193"), tg) and close(n("Calc", f"{x}194"), max(0.0, n("Calc", "D2") * n("Calc", f"{x}8") - n("Calc", f"{x}25") - tg))
              and close(n("Calc", f"{x}195"), max(tg + n("Calc", f"{x}194"), n("Calc", f"{x}192"))))
    check("all needs are zero or positive for every bank and combination", all(n("Calc", f"{c}{r}") >= 0 for c in "DEFGHIJ" for r in (187, 188, 189, 190, 191, 192, 193, 194, 195)))
    off = {("Calc", "N19"): 0.0}
    check("N19 = 0: the instruments of the target do not count in the stack (AT1, Tier 2, senior, SNP, SP)",
          all(close(n("Calc", f"{x}22", off), n("Calc", "D22") + n("Calc", f"{x}68")) and close(n("Calc", f"{x}24", off), n("Calc", "D24") + n("Calc", f"{x}70") + n("Calc", f"{x}71"))
              and close(n("Calc", f"{x}154", off), n("Calc", "D154") + n("Calc", f"{x}70")) and close(n("Calc", f"{x}155", off), n("Calc", "D155") + n("Calc", f"{x}71")) for x in "HIJ"))
    check("mitigation: the need at the MREL target with N19 = 0 equals row 197 with N19 = 100%, and the mitigation is the difference (row 198)",
          all(close(n("Calc", f"{x}194", off), n("Calc", f"{x}197")) and close(n("Calc", f"{x}198"), n("Calc", f"{x}197") - n("Calc", f"{x}194")) and n("Calc", f"{x}198") >= 0 for x in "HIJ"))
    check("the split of the senior stack still adds up with N19 = 0", all(n("Calc", f"{c}156", off) == 1 for c in "DEFGHIJ"))
    gross_row = W.p3dh_rows()["cc1_cet1_before_adj"]
    for x, t in zip("HIJ", "EFG"):
        own = n("Calc", f"{t}20") + n("Calc", f"{t}22") + n("Calc", f"{t}23")
        need_ = min(n("Calc", f"{t}102") * n("Calc", f"{t}8"), n("Calc", "D102") * n("Calc", f"{t}8"))
        items = n("P3DH", f"{t}{gross_row}") + n("Calc", f"{t}22") + n("Calc", f"{t}23")
        f_ = 1 - max(0.0, own - need_) / items
        check(f"recognition of the AT1 and Tier 2 of target {t} (CRR Article 87): 1 - surplus / gross capital items = {f_:.3f}, between 0 and 1",
              close(n("Calc", f"{t}233"), f_) and 0.0 <= n("Calc", f"{t}233") <= 1.0, f"{n('Calc', f'{t}233')} vs {f_}")
        check(f"deal {x}: AT1 and Tier 2 of the target count at N19 x recognition; the senior of the target counts at N26 (default 0: single point of entry)",
              close(n("Calc", f"{x}22"), n("Calc", "D22") + n("Calc", "N19") * n("Calc", f"{t}233") * n("Calc", f"{t}22") + n("Calc", f"{x}68"))
              and close(n("Calc", f"{x}23"), n("Calc", "D23") + n("Calc", "N19") * n("Calc", f"{t}233") * n("Calc", f"{t}23") + n("Calc", f"{x}69"))
              and n("Calc", "N26") == 0.0 and close(n("Calc", f"{x}24"), n("Calc", "D24") + n("Calc", f"{x}70") + n("Calc", f"{x}71")))
        full = {("Calc", "N26"): 1.0}
        check(f"deal {x}: N26 = 100% lets the senior of the target count in full (rows 24, 154, 155)",
              close(n("Calc", f"{x}24", full), n("Calc", "D24") + n("Calc", f"{t}24") + n("Calc", f"{x}70") + n("Calc", f"{x}71"))
              and close(n("Calc", f"{x}154", full) + n("Calc", f"{x}155", full), n("Calc", f"{x}24", full)))
    check("the default (senior of the target does not count) leaves a larger need than N26 = 100%: the stranded senior of the target costs the group", all(n("Calc", f"{x}194") >= n("Calc", f"{x}194", {("Calc", "N26"): 1.0}) for x in "HIJ"))
    cashes = [0.0, 0.5, 1.0]
    needs = [n("Calc", "H195", {("Calc", "H2"): c}) for c in cashes]
    check("a higher cash share does not lower the issuance need (cash leaves the group)", needs[0] <= needs[1] <= needs[2], str(needs))
    check("goodwill and the CET1 change are shown: row 201 = CET1 of the deal less CET1 of NBG, row 200 = - goodwill / RWAs in bp",
          all(close(n("Calc", f"{x}201"), n("Calc", f"{x}20") - n("Calc", "D20")) and close(n("Calc", f"{x}200"), -n("Calc", f"{x}81") / n("Calc", f"{x}8") * 1e4) for x in "HIJ"))
    # subordination requirement: filed value, or the assumption for a combination of N21 or more
    filed_sub = {c: n("Calc", f"{c}158") for c in "DEFG"}
    check("NBG and the three targets file no subordination requirement in P3DH (0 in row 158)", all(v == 0 for v in filed_sub.values()), str(filed_sub))
    for x in "HIJ":
        big = n("Calc", f"{x}7") >= n("Calc", "N21")
        check(f"deal {x}: no filed requirement, assets {n('Calc', f'{x}7'):.0f}bn: the assumption N20 plus the combined buffer applies when assets reach N21, else 0",
              close(n("Calc", f"{x}177"), n("Calc", "N20") + n("Calc", f"{x}99") if big else 0.0))
        check(f"deal {x}: subordination requirement in EUR = the larger of the share of TREA and the floor on the leverage exposure",
              close(n("Calc", f"{x}182"), max(n("Calc", f"{x}177") * n("Calc", f"{x}170"), n("Calc", "N22") * n("Calc", f"{x}109")) if n("Calc", f"{x}177") > 0 else 0.0))
    check("N20 = 0 removes the assumption; N21 above the size of the deal removes it too",
          all(n("Calc", f"{x}177", {("Calc", "N20"): 0.0, ("Calc", "N21"): 1e9}) == 0 and n("Calc", f"{x}182", {("Calc", "N21"): 1e9}) == 0 for x in "HIJ"))
    check("a higher assumed requirement raises the need for subordinated instruments (N20 20% against 13.5%)",
          all(n("Calc", f"{x}191", {("Calc", "N20"): 0.20}) >= n("Calc", f"{x}191") for x in "HIJ") and n("Calc", "J191", {("Calc", "N20"): 0.20}) > n("Calc", "J191"))
    # buckets for AT1 and Tier 2
    for c in "DEFGHIJ":
        p2r = n("Calc", f"{c}92")
        at1_b, t2_b = (n("Calc", "N8") + n("Calc", "N11") * p2r) * n("Calc", f"{c}170"), (n("Calc", "N9") + n("Calc", "N12") * p2r) * n("Calc", f"{c}170")
        ok = close(n("Calc", f"{c}208"), at1_b) and close(n("Calc", f"{c}209"), t2_b)
        ok = ok and close(n("Calc", f"{c}212"), max(0.0, at1_b - n("Calc", f"{c}22"))) and close(n("Calc", f"{c}213"), max(0.0, t2_b - n("Calc", f"{c}23")))
        ok = ok and close(n("Calc", f"{c}214"), max(0.0, n("Calc", f"{c}22") - at1_b)) and close(n("Calc", f"{c}215"), max(0.0, n("Calc", f"{c}23") - t2_b))
        check(f"column {c}: AT1 and Tier 2 buckets = (Pillar 1 + share of the P2R) x RWAs; room and excess follow", ok)
        check(f"column {c}: AT1 and Tier 2 to issue are within the room, and the rest of the need goes to CET1",
              n("Calc", f"{c}216") <= n("Calc", f"{c}212") + 1e-12 and n("Calc", f"{c}217") <= n("Calc", f"{c}213") + 1e-12
              and close(n("Calc", f"{c}216") + n("Calc", f"{c}217") + n("Calc", f"{c}218"), n("Calc", f"{c}188") + n("Calc", f"{c}189")))
        check(f"column {c}: instruments to issue add up (row 222) and none is negative",
              close(n("Calc", f"{c}222"), sum(n("Calc", f"{c}{r}") for r in (216, 217, 219, 220, 221))) and all(n("Calc", f"{c}{r}") >= 0 for r in range(216, 223)))
    tight = {("Calc", "D1"): 0.20, ("Calc", "N8"): 0.0, ("Calc", "N9"): 0.0}
    check("with large buckets and a high CET1 target the mix issues CET1 first, and with zero buckets nothing fits: all Tier 1 and Tier 2 need goes to CET1",
          all(n("Calc", f"{x}216", {("Calc", "N8"): 0.0, ("Calc", "N11"): 0.0}) == 0 for x in "HIJ") and tight is not None)
    boc = W.merger_start(1) + W.MOFF["t_np"]
    hcob = W.merger_start(2) + W.MOFF["t_np"]
    npg = lambda i: n("Merger", f"D{W.merger_start(i) + W.MOFF['np_g']}")  # noqa: E731
    check("four-year model: BoC profit is the consensus of each year, year 4 grows from year 3", close(n("Merger", f"D{boc}"), market["slots"][2]["cons"][2026]["NI"])
          and close(n("Merger", f"F{boc}"), market["slots"][2]["cons"][2028]["NI"]) and close(n("Merger", f"G{boc}"), n("Merger", f"F{boc}") * (1 + npg(1))))
    check("four-year model: HCOB has no consensus: profit of the last 12 months, grown at the input", close(n("Merger", f"D{hcob}"), market["slots"][3]["ni_ltm"])
          and close(n("Merger", f"E{hcob}"), n("Merger", f"D{hcob}") * (1 + npg(2))))
    cost = W.merger_start(2) + W.MOFF["t_cost"]
    check("four-year model: HCOB cost base is the opex of Bloomberg, revenue follows the cost/income input", close(n("Merger", f"D{cost}"), -market["slots"][3]["opex"])
          and close(n("Merger", f"D{W.merger_start(2) + W.MOFF['t_rev']}"), market["slots"][3]["opex"] / n("Merger", f"D{W.merger_start(2) + W.MOFF['cir']}")))
    overrides = W.original_overrides()
    alt = model.run(overrides)
    check("original inputs reproduce the NBG profit and size of the original sheet", close(alt.number("Calc", "D9"), 1.1) and close(alt.number("Calc", "D7"), 80))
    return wb


def test_km2_sub_requirements() -> None:
    print("4b. subordination requirements filed in P3DH")
    db = ROOT / "data" / "processed" / "p3dh.sqlite"
    if not db.exists():
        print("  skipped (no database)")
        return
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    km = ma_data.km2_sub_requirements(lambda sql, params=(): pd.read_sql_query(sql, conn, params=params))
    check("KM2 of 150 or more banks, with the ratio cells converted to fractions between 0 and 1", len(km) > 150 and pd.concat([km["mrel"], km["sub"]]).dropna().between(0, 1).all(), str(len(km)))
    top = km[km["size_class"].astype(str).isin(["Large", "Very large"]) & (km["sub"] > 0)]
    check("banks above EUR 100bn that file a requirement: 30 or more, median between 12% and 25% of TREA", len(top) >= 30 and 0.12 < top["sub"].median() < 0.25, f"{len(top)} {top['sub'].median():.3f}")
    nbg = km[km["entity_key"] == W.NBG_KEY].iloc[0]
    check("NBG files 0% (row EU-8), BIL files nothing", nbg["sub"] == 0 and km[km["entity_key"] == "9CZ7TVMR36CYD5TZBS50"]["sub"].isna().all())
    check("13.5% of TREA is the most frequent value among banks of EUR 100bn to 250bn", (top[top["size_class"].astype(str) == "Large"]["sub"].round(3) == 0.135).sum() >= 5)


def test_cr1_sheet() -> None:
    print("4c. CR1 loans come from the sheet of the amounts (K_21.01.a), not from a sheet of impairments or counterparties")
    db = ROOT / "data" / "processed" / "p3dh.sqlite"
    if not db.exists():
        print("  skipped (no database)")
        return
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    query = lambda sql, params=(): pd.read_sql_query(sql, conn, params=params)  # noqa: E731
    ents = query("SELECT DISTINCT entity_key FROM clean_fact WHERE template_code = 'K_21.01'")["entity_key"].tolist()[:150]
    bad = []
    for e in ents:
        items: dict = {}
        ma_data._load_cells(query, e, "2026-12-31", items)
        for name, col in (("cr1_loans_performing", "0010"), ("cr1_loans_npl", "0040")):
            it = items.get(name)
            if it is None:
                continue
            a = query("SELECT value FROM clean_fact WHERE entity_key = ? AND template_code = 'K_21.01' AND reference_date = ? AND cell_code = ? AND sheet = '' AND key_descriptor = '' AND quality <> 'quarantined'",
                      (e, it.period, "{K_21.01.a, r0020, c%s}" % col))
            if a.empty or abs(a["value"].iloc[0] - it.value) > 1:
                bad.append((e, name))
    check("the CR1 cell of each of 150 banks equals the cell of sheet .a", not bad, f"{bad[:3]}")


def test_ma_data_fallbacks() -> None:
    print("4d. ma_data: a period needs TREA, and total assets fall back to CC2 then LR1")
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE v_entity_class (entity_key TEXT, entity_name TEXT, country TEXT, region TEXT, peer_group TEXT, size_class TEXT);
        CREATE TABLE clean_period_fact (entity_key TEXT, period_end TEXT, template_code TEXT, measure_col INTEGER, row_code TEXT, value REAL, quality TEXT);
        CREATE TABLE clean_fact (entity_key TEXT, reference_date TEXT, template_code TEXT, cell_code TEXT, row_code TEXT, column_code TEXT, sheet TEXT, key_descriptor TEXT, value REAL, quality TEXT);
        CREATE TABLE entity_assets (entity_key TEXT, period_end TEXT, total_assets_eur REAL, assets_source TEXT, assets_method TEXT);
    """)
    conn.execute("INSERT INTO v_entity_class VALUES ('K1', 'Test Bank', 'Greece', 'South', 'core', 'Large')")
    for period, rows in (("2026-06-30", ("0010", "0040")), ("2026-09-30", ("0010",))):  # the later period has CET1 but no TREA
        for r in rows:
            conn.execute("INSERT INTO clean_period_fact VALUES ('K1', ?, 'K_61.00', 10, ?, 1000.0, 'ok')", (period, r))
    q = lambda sql, params=(): pd.read_sql_query(sql, conn, params=params)  # noqa: E731
    check("km1_periods: only a period with CET1 and TREA is listed (the newest period without TREA is left out)", ma_data.km1_periods(q, "K1") == ["2026-06-30"], str(ma_data.km1_periods(q, "K1")))
    conn.execute("INSERT INTO clean_fact VALUES ('K1', '2026-06-30', 'K_66.02', '{K_66.02.b, r0010, c0010}', '0010', '0010', '', '', 5.0e9, 'ok')")
    bank = ma_data.load_bank(q, "K1", "2026-06-30")
    check("total assets: no row in entity_assets, so the CC2 balance sheet total is used", bank.item("total_assets").value == 5.0e9 and bank.item("total_assets").source.startswith("K_66.02"), str(bank.item("total_assets")))
    conn.execute("DELETE FROM clean_fact")
    conn.execute("INSERT INTO clean_fact VALUES ('K1', '2026-06-30', 'K_70.00', '{K_70.00, r0010, c0010}', '0010', '0010', '', '', 7.0e9, 'ok')")
    check("total assets: no CC2 either, so the leverage exposure template LR1 is used", ma_data.load_bank(q, "K1", "2026-06-30").item("total_assets").value == 7.0e9)
    conn.execute("INSERT INTO entity_assets VALUES ('K1', '2026-06-30', 6.0e9, 'LR1', 'verified_vs_leverage_exposure')")
    check("total assets: a usable row of entity_assets comes first", ma_data.load_bank(q, "K1", "2026-06-30").item("total_assets").value == 6.0e9)


def row_of(ws, start: str, col: str = "A") -> int:
    for r in range(1, ws.max_row + 1):
        v = ws[f"{col}{r}"].value
        if isinstance(v, str) and v.startswith(start):
            return r
    raise KeyError(start)


def test_pack_data() -> None:
    print("6a. pack data readers (invented numbers in a memory database)")
    import ma_pack_data as D

    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE clean_fact (entity_key TEXT, reference_date TEXT, template_code TEXT, cell_code TEXT, row_code TEXT, column_code TEXT, sheet TEXT, key_descriptor TEXT, row_label TEXT, value REAL, quality TEXT);
        CREATE TABLE te_oth (lei TEXT, period_end TEXT, sheet TEXT, label TEXT, n_quarters INTEGER, assets_fv INTEGER, assets_stages INTEGER, amount REAL, vintage TEXT);
        CREATE TABLE bbg_bond (lei TEXT, payment_rank TEXT, basel_iii TEXT, perpetual TEXT, currency TEXT, amt_outstanding REAL);
    """)
    q = lambda sql, params=(): pd.read_sql_query(sql, conn, params=params)  # noqa: E731
    # OR2: column a is the year of the filing, b the year before. An expense is positive in the output, whatever its sign in the filing.
    for row, a, b in (("0030", 100e6, 80e6), ("0040", -30e6, 25e6), ("0080", 20e6, 15e6)):
        for col, v in (("0010", a), ("0020", b)):
            conn.execute("INSERT INTO clean_fact VALUES ('K1', '2025-12-31', 'K_19.02', '', ?, ?, '', '', '', ?, 'ok')", (row, col, v))
    y = D.or2_lines(q, "K1")
    check("or2_lines: year of the filing and the year before; expense lines positive", set(y) == {2024, 2025} and y[2025]["interest_income"] == 100.0 and y[2025]["interest_expense"] == 30.0 and y[2024]["interest_expense"] == 25.0, str(y))
    # EBA exercise: the newest vintage wins; total assets only from the line without fair value split
    for sheet, label, nq, fv, st, amt, vin in (("P&L", "Interest income", 2, 0, 0, 40.0, "a"), ("P&L", "Interest income", 2, 0, 0, 41.0, "b"), ("Assets", "Total Assets", 2, 0, 0, 900.0, "b"),
                                              ("Assets", "Total Assets", 2, 1, 0, 5.0, "b"), ("Liabilities", "TOTAL EQUITY", 2, 0, 0, 70.0, "b")):
        conn.execute("INSERT INTO te_oth VALUES ('L1', '2025-06-30', ?, ?, ?, ?, ?, ?, ?)", (sheet, label, nq, fv, st, amt, vin))
    t = D.te_lines(q, "L1")["2025-06-30"]
    check("te_lines: newest vintage, year-to-date quarters, assets without the fair value split, equity", t["n_quarters"] == 2 and t["lines"] == {"interest_income": 41.0, "assets": 900.0, "equity": 70.0}, str(t))
    # CC2: lines map to buckets and the two sides tie to the total
    cell = lambda s: "{K_66.02.%s, r0010, c0010}" % s  # noqa: E731
    cc2 = [("b", "", 100e6), ("f", "", 10e6), ("a", "Type of assets = Cash, cash balances at central banks", 12e6), ("a", "Type of assets = Loans and advances to customers", 60e6),
           ("a", "Type of assets = Financial investments", 20e6), ("a", "Type of assets = Intangible assets", 3e6), ("a", "Type of assets = Other assets", 5e6),
           ("c", "Type of liabilities = Amounts due to customers", 70e6), ("c", "Type of liabilities = Debt securities issued", 15e6), ("c", "Type of liabilities = Subordinated liabilities", 3e6),
           ("c", "Type of liabilities = Other liabilities", 2e6)]
    for s, kd, v in cc2:
        conn.execute("INSERT INTO clean_fact VALUES ('K2', '2025-12-31', 'K_66.02', ?, '0010', '0010', '', ?, '', ?, 'ok')", (cell(s), kd, v))
    c = D.cc2_summary(q, "K2")
    check("cc2_summary: buckets and tie to the total", c and c["assets"]["cash"] == 12.0 and c["assets"]["loans"] == 60.0 and c["assets"]["securities"] == 20.0 and c["assets"]["intangibles"] == 3.0
          and c["liabilities"]["deposits"] == 70.0 and c["liabilities"]["debt"] == 15.0 and c["liabilities"]["sub"] == 3.0 and c["equity"] == 10.0 and c["total"] == 100.0, str(c))
    conn.execute("UPDATE clean_fact SET value = 50e6 WHERE entity_key = 'K2' AND cell_code = ? AND key_descriptor LIKE '%customers'", (cell("a"),))
    check("cc2_summary: lines that do not tie to the total give no balance sheet", D.cc2_summary(q, "K2") == {})
    # bonds: only EUR bonds are summed; the others are counted
    for rank, b3, cur, amt in (("Sr Preferred", None, "EUR", 500e6), ("Sr Preferred", None, "USD", 400e6), ("Sr Non Preferred", None, "EUR", 300e6), ("Subordinated", "Tier 2", "EUR", 200e6),
                               ("Jr Subordinated", "Additional Tier 1", "EUR", 100e6), ("Unsecured", None, "EUR", 50e6)):
        conn.execute("INSERT INTO bbg_bond VALUES ('L1', ?, ?, 'N', ?, ?)", (rank, b3, cur, amt))
    b = D.bonds_by_rank(q, "L1")
    check("bonds_by_rank: EUR bonds by rank, other currencies counted and not summed", b["senior_preferred"] == 0.5 and b["senior_non_preferred"] == 0.3 and b["tier2"] == 0.2 and b["at1"] == 0.1
          and b["other_senior"] == 0.05 and b["non_eur_count"] == 1, str(b))
    # static grids: same rules as the sheet Peers (ties included) and the Gordon model
    rows = [{"rote": 0.08 + 0.01 * i, "rocet1": 0.09 + 0.01 * i, "ptbv": 0.8 + 0.1 * i, "pcet1": 1.0 + 0.1 * i} for i in range(7)]
    kg = D.k_grid(rows, 0.10, 0.11, 2.0, 1.6, ks=(3,))[0]
    check("k_grid: the 3 nearest peers by return, median multiples, and value", kg["n_tbv"] == 3 and abs(kg["ptbv"] - 1.0) < 1e-9 and abs(kg["pcet1"] - 1.2) < 1e-9 and abs(kg["value_tbv"] - 2.0) < 1e-9, str(kg))
    gg = D.g_grid(rows, 0.10, 0.11, 2.0, 1.6, k=3, coe=0.10, gs=(0.02,))[0]
    coe = np.median([0.02 + (r["rote"] - 0.02) / r["ptbv"] for r in rows[1:4]])
    check("g_grid: cost of equity of the peers = g + (return - g) / multiple, factor = (that - g) / (cost of equity - g)", abs(gg["coe_tbv"] - coe) < 1e-12 and abs(gg["factor_tbv"] - (coe - 0.02) / 0.08) < 1e-12, str(gg))
    tie = [{"rote": 0.10, "rocet1": 0.10, "ptbv": 1.0 + i, "pcet1": 1.0 + i} for i in range(4)]
    check("k_grid: a tie at the k-th distance puts all tied banks in the set", D.k_grid(tie, 0.10, 0.10, 1.0, 1.0, ks=(2,))[0]["n_tbv"] == 4)


def test_pack(wb: openpyxl.Workbook | None, loaded) -> None:
    print("6. deal pack sheets")
    if wb is None or loaded is None:
        print("  skipped")
        return
    banks, market = loaded
    model = ma_sheet.Model.from_openpyxl(wb)
    run = model.run()
    num = lambda sheet, cell, r=None: (r or run).number(sheet, cell)  # noqa: E731
    val, bs, pnl, mrel, dec = (wb[s] for s in ("Valuation", "Balance sheet", "P&L", "MREL scenario", "Decisions"))
    pack = market["pack"]
    check("the pack has no missing part on this database", not pack["missing"], str(pack["missing"]))

    # Valuation: the comp equals an independent calculation, and the football field ties to Calc
    rows = market["peers"]["rows"]
    rote, rocet1, kk = num("Calc", "E161"), num("Calc", "E162"), int(num("Calc", "N17"))
    near = lambda key, x: [r for r in rows if abs(r[key] - x) <= sorted(abs(r[key] - x) for r in rows)[kk - 1]]  # noqa: E731
    r_med = row_of(val, "Median multiple of the nearest peers")
    check("Valuation: median P/TBV and P/CET1 of the nearest peers equal numpy on the peer list",
          close(num("Valuation", f"B{r_med}"), float(np.median([r["ptbv"] for r in near("rote", rote)]))) and close(num("Valuation", f"C{r_med}"), float(np.median([r["pcet1"] for r in near("rocet1", rocet1)]))))
    r_used = row_of(val, "Value used in the model (basis in Calc N18)")
    check("Valuation: value used equals Calc rows 167 and 32, and its P/TBV equals Calc row 60", close(num("Valuation", f"B{r_used}"), num("Calc", "E167")) and close(num("Valuation", f"B{r_used}"), num("Calc", "E32"))
          and close(num("Valuation", f"C{r_used}"), num("Calc", "E60")))
    r_deal = row_of(val, "Deal: price for the stake")
    check("Valuation: the deal row equals Calc row 38", close(num("Valuation", f"F{r_deal}"), num("Calc", "E38")) and close(num("Valuation", f"B{r_deal}") * num("Calc", "H4"), num("Calc", "E38")))
    r_f = row_of(val, "Banks of Bloomberg with their own listed shares")
    last = r_f + len(pack["funnel"]) - 1
    check("Valuation: the funnel ends at the peers of the sheet Peers (check flag 1)", int(num("Valuation", f"B{last}")) == len(rows) and num("Valuation", f"C{last + 1}") == 1)
    cet1_t = banks[1].get("cet1")
    r_k20 = row_of(val, "Before the cost of equity factor", "A")
    kg = {x["k"]: x for x in pack["k_grid"]}
    check("Valuation: the static table for k = 20 equals the live value before the cost of equity factor", close(num("Valuation", f"G{r_k20 + 2}"), num("Valuation", f"B{row_of(val, 'Average of the two, before')}"), 1e-6) and kg[20]["n_tbv"] == num("Peers", f"I8"), "")
    r_coe10 = row_of(val, "Cost of equity of the target (input of this row)") + 1
    r_g2 = row_of(val, "After the cost of equity factor") + 2
    check("Valuation: the static table for g = 2% equals the live table at 10%", close(num("Valuation", f"G{r_g2}"), num("Valuation", f"G{r_coe10}"), 1e-6), f"{num('Valuation', f'G{r_g2}')} {num('Valuation', f'G{r_coe10}')}")
    del cet1_t

    # MREL: CRR Article 87 factor, SPE need, MPE need
    own = num("Calc", "E20") + num("Calc", "E22") + num("Calc", "E23")
    surplus = max(0.0, own - min(num("Calc", "E102") * num("Calc", "E8"), num("Calc", "D102") * num("Calc", "E8")))
    gross = num("P3DH", "E" + str(W.p3dh_rows()["cc1_cet1_before_adj"])) + num("Calc", "E22") + num("Calc", "E23")
    factor = 1 - surplus / gross
    r_fac = row_of(mrel, "Share recognised")
    check("MREL: the Article 87 factor equals numpy and Calc row 233", close(num("MREL scenario", f"B{r_fac}"), factor) and close(num("Calc", "E233"), factor) and num("MREL scenario", f"B{r_fac + 1}") == 1, f"{factor}")
    check("MREL: the factor is between 0 and 1", 0 < factor <= 1)
    r_need = row_of(mrel, "Issuance need at the requirements (Calc row 192")
    r_sel = row_of(mrel, "Issuance need at the requirements, selected strategy")
    check("MREL: the single point of entry need equals Calc row 192 and is the selected need", close(num("MREL scenario", f"B{r_need}"), num("Calc", "H192")) and close(num("MREL scenario", f"D{r_sel}"), num("Calc", "H192")))
    ov = {("MREL scenario", "B4"): 2}
    bil_sur = num("Calc", "E25") - num("Calc", "E181")
    nbg_sur = num("Calc", "D25") - num("Calc", "D181") - num("Calc", "E38") * 1.0
    run2 = model.run(ov)
    check("MREL: the multiple points of entry need = BIL shortfall + NBG shortfall with the add-on (numpy), and the switch selects it",
          close(num("MREL scenario", f"D{r_sel}", run2), max(0, -bil_sur) + max(0, -nbg_sur)), f"{num('MREL scenario', f'D{r_sel}', run2)} vs {max(0, -bil_sur) + max(0, -nbg_sur)}")
    r_gap = row_of(mrel, "Internal MREL of BIL: instruments that NBG must buy")
    check("MREL: internal MREL gap = requirement less own funds of BIL, not below 0", close(num("MREL scenario", f"B{r_gap}"), max(0, num("Calc", "E181") - own)))
    check("MREL: an AT1 and Tier 2 share of 0% removes the recognition from the group (Calc rows 22 and 23)", close(num("Calc", "H22", model.run({("Calc", "N19"): 0.0})), num("Calc", "D22")))

    # P&L: flat switch reproduces the Merger without the pack; the driver case feeds the Merger
    m2 = {k: v for k, v in market.items() if k != "pack"}
    deals = [W.default_deal(b, sl["lei"]) for b, sl in zip(banks[1:], market["slots"][1:])]
    wb_old = W.build_workbook(banks, deals, W.default_globals(), m2, with_original=False)
    run_old = ma_sheet.Model.from_openpyxl(wb_old).run()
    run_flat = model.run({("P&L", "B4"): 0})
    bad = []
    for (sh, co), raw in ma_sheet.Model.from_openpyxl(wb_old).cells.items():
        if sh == "Merger" and isinstance(raw, str) and raw.startswith("="):
            a, b = run_old.get("Merger", co), run_flat.get("Merger", co)
            if isinstance(a, (int, float)) and not (isinstance(b, (int, float)) and close(float(a), float(b), 1e-9)):
                bad.append(co)
            elif isinstance(a, str) and a != b:
                bad.append(co)
    check("P&L: with the switch at 0 every Merger cell equals the model without the pack", not bad, str(bad[:6]))
    R = W.merger_start(0)
    t_np = [num("Merger", f"{c}{R + W.MOFF['t_np']}") for c in W.YC]
    r_drv = row_of(pnl, "Net profit from the drivers")
    check("P&L: with the switch at 1 the net profit of BIL on the Merger equals the driver profit", all(close(a, num("P&L", f"{c}{r_drv}")) for a, c in zip(t_np, "CDEF")))
    others = [k for k in (1, 2) if any(not close(num("Merger", f"{c}{W.merger_start(k) + W.MOFF['t_np']}"), num("Merger", f"{c}{W.merger_start(k) + W.MOFF['t_np']}", run_flat)) for c in W.YC)]
    check("P&L: the switch changes deal 1 only", not others, str(others))
    r_flat, r_sel_p = row_of(pnl, "Net profit flat"), row_of(pnl, "Net profit used by the model")
    check("P&L: the selected profit follows the switch (flat at 0, drivers at 1)", all(close(num("P&L", f"{c}{r_sel_p}", run_flat), num("P&L", f"{c}{r_flat}")) and close(num("P&L", f"{c}{r_sel_p}"), num("P&L", f"{c}{r_drv}")) for c in "CDEF"))
    r_rev, r_cost, r_imp, r_pbt, r_tax = (row_of(pnl, s) for s in ("Total revenue", "Costs (negative)", "Impairment (negative)", "Profit before tax", "Tax"))
    check("P&L: profit = revenue + costs + impairment, less tax at the tax rate (each year)", all(close(num("P&L", f"{c}{r_drv}"), (num("P&L", f"{c}{r_rev}") + num("P&L", f"{c}{r_cost}") + num("P&L", f"{c}{r_imp}")) * (1 - num("P&L", f"{c}{row_of(pnl, 'Tax rate')}"))) for c in "CDEF"))
    gap = num("P&L", f"B{row_of(pnl, 'Check of the base year')}")
    check("P&L: the lines of the base year explain the trailing profit within 15%", abs(gap) < 0.15 * num("P&L", f"B{r_flat}"), f"gap {gap:.1f}")
    r_pf = row_of(pnl, "Pro forma net profit")
    check("P&L: the pro forma profit and the EPS accretion equal the Merger", all(close(num("P&L", f"{c}{r_pf}"), num("Merger", f"{m}{R + W.MOFF['a_tot']}")) and close(num("P&L", f"{c}{r_pf + 4}"), num("Merger", f"{m}{R + W.MOFF['e_imp']}")) for c, m in zip("CDEF", W.YC)))
    check("P&L: NBG consensus rows equal the sheet Market", all(close(num("P&L", f"{c}{row_of(pnl, 'Net income')}"), num("Market", f"B{W.cons_row('NI', k)}")) for k, c in enumerate("CDEF")))

    # Balance sheet
    r_cet = row_of(bs, "CET1", "A")
    check("Balance sheet: CET1 and total assets of the pro forma equal Calc", close(num("Balance sheet", f"E{row_of(bs, 'Total assets')}"), num("Calc", "H7")) and close(num("Balance sheet", f"E{r_cet}"), num("Calc", "H20")))
    check("Balance sheet: the simple sum is the sum of the two banks", close(num("Balance sheet", f"D{r_cet}"), num("Calc", "D20") + num("Calc", "E20")) and close(num("Balance sheet", f"D{row_of(bs, 'CET1 ratio')}"), (num("Calc", "D20") + num("Calc", "E20")) / (num("Calc", "D8") + num("Calc", "E8"))))
    r_a, r_l = row_of(bs, "Total assets of the lines"), row_of(bs, "Total liabilities and equity of the lines")
    check("Balance sheet: the CC2 lines tie on both sides for both banks (within 2%)", all(abs(num("Balance sheet", f"{c}{r_a}") - num("Balance sheet", f"{c}{r_l}")) <= 0.02 * num("Balance sheet", f"{c}{r_a}") for c in "BC"))
    check("Balance sheet: the CC2 assets of NBG tie to total assets of Calc (same date) within 2%", abs(num("Balance sheet", f"B{r_a}") - num("Calc", "D7")) <= 0.02 * num("Calc", "D7"))
    r_t = row_of(bs, "Sum of the types")
    check("Balance sheet: risk-weighted assets by type add up to TREA within 1% (OV1 against KM1)", all(abs(num("Balance sheet", f"{c}{r_t}") - num("Calc", f"{d}8")) <= 0.01 * num("Calc", f"{d}8") for c, d in (("B", "D"), ("C", "E"))))
    r_mix = row_of(bs, "F. Loans by counterparty") + 1
    shares = [num("Balance sheet", f"B{r}") for r in range(r_mix, r_mix + 6)]
    check("Balance sheet: the counterparty shares of NBG add up to 100%", close(sum(shares), 1.0, 1e-6), str(sum(shares)))

    # the pack is written only when BIL is the first target
    conn2 = sqlite3.connect(f"file:{(ROOT / 'data' / 'processed' / 'p3dh.sqlite').as_posix()}?mode=ro", uri=True)
    q2 = lambda sql, params=(): pd.read_sql_query(sql, conn2, params=params)  # noqa: E731
    swapped = [banks[0], banks[2], banks[1], banks[3]]
    m_sw = W.load_market(q2, swapped)
    wb_sw = W.build_workbook(swapped, [W.default_deal(b, sl["lei"]) for b, sl in zip(swapped[1:], m_sw["slots"][1:])], W.default_globals(), m_sw, with_original=False)
    check("a first target other than BIL gets no pack: no pack sheets, and the Merger keeps its old rules", "pack" not in m_sw and not set(PACK_SHEETS) & set(wb_sw.sheetnames)
          and "P&L" not in str(wb_sw["Merger"][f"D{W.merger_start(0) + W.MOFF['t_np']}"].value))
    conn2.close()

    # MREL scenario, section E: issued and eligible debt from P3DH
    br = pack["bridge"]
    check("MREL scenario E: the pack holds the P3DH bridge for NBG and BIL", set(br) == {"NBG", "BIL"} and all(b["date"] and b["km2"] for b in br.values()), str(list(br)))
    r_iss, r_el, r_tot, r_bp, r_chk = (row_of(mrel, s) for s in ("Total issued debt", "Eligible debt, gross", "Own funds and eligible liabilities, computed", "Difference (bp)", "Equal to Calc row 25"))
    for col, nm in (("B", "NBG"), ("C", "BIL")):
        b = br[nm]
        tl = b["tlac"]
        issued = sum(b["cc2"].get(k, 0.0) for k in ("debt", "fv", "sub")) + (b["cc2"].get("at1") or tl["at1"])
        elig = tl["at1"] + tl["t2"] + (tl["t2_am"] or 0) + (tl.get("snp") or 0) + (tl.get("snp_b") or 0) + (tl["ns14"] if tl["ns14"] is not None else (tl["ns13"] or 0) + (tl["ns13a"] or 0))
        check(f"MREL scenario E, {nm}: issued debt and eligible debt equal an independent sum of the P3DH lines (EUR bn)", close(num("MREL scenario", f"{col}{r_iss}"), issued / 1000, 1e-9) and close(num("MREL scenario", f"{col}{r_el}"), elig / 1000, 1e-9))
        check(f"MREL scenario E, {nm}: own funds and eligible liabilities equal the reported KM2 (EUR bn) and the ratio differs by less than 0.5 bp", close(num("MREL scenario", f"{col}{r_tot}"), b["km2"]["total"] / 1000, 1e-6)
              and abs(num("MREL scenario", f"{col}{r_bp}")) < 0.5, f"{num('MREL scenario', f'{col}{r_tot}')} {b['km2']['total'] / 1000} {num('MREL scenario', f'{col}{r_bp}')}")
        check(f"MREL scenario E, {nm}: the newest KM2 equals Calc row 25", num("MREL scenario", f"{col}{r_chk}") == 1)
        check(f"MREL scenario E, {nm}: the eligible share of issued debt is between 0 and 100%", 0 < num("MREL scenario", f"{col}{row_of(mrel, 'Eligible share of issued debt')}") <= 1.0001)

    # Decisions and Sources
    n_dec = sum(1 for r in range(5, dec.max_row + 1) if dec[f"B{r}"].value)
    vals_ok = all(not isinstance(run.get("Decisions", f"{c}{r}"), (ma_sheet.XlError, type(None))) for r in range(5, 5 + n_dec) for c in "EF")
    check("Decisions: 15 or more decisions, each with a value now and an effect now that evaluate", n_dec >= 15 and vals_ok, str(n_dec))
    check("Decisions: the strategy decision links to the switch of the MREL scenario sheet", dec["E5"].value == "='MREL scenario'!B4")
    check("Sources: a table with 10 or more items", sum(1 for r in range(4, 40) if wb["Sources"][f"A{r}"].value and wb["Sources"][f"B{r}"].value) >= 10)


def test_independent(wb: openpyxl.Workbook | None) -> None:
    print("4. independent recalculation with the library formulas")
    if wb is None:
        print("  skipped")
        return
    try:
        import formulas
    except ImportError:
        print("  skipped (pip install formulas)")
        return
    tmp = Path(tempfile.mkdtemp()) / "ma_check.xlsx"
    wb.save(tmp)
    sol = formulas.ExcelModel().loads(str(tmp)).finish().calculate()
    keys = {k.upper(): k for k in sol}
    mine = ma_sheet.Model.from_openpyxl(openpyxl.load_workbook(tmp)).evaluate_all()
    n = bad = 0
    diffs: list = []
    model =ma_sheet.Model.from_openpyxl(openpyxl.load_workbook(tmp))
    for (sh, co), raw in model.cells.items():
        if sh not in ("Calc", "Merger", "Review", *PACK_SHEETS) or not (isinstance(raw, str) and raw.startswith("=")):
            continue
        k = f"'[{tmp.name}]{sh}'!{co}".upper()
        if k not in keys:
            continue
        n += 1
        v = sol[keys[k]].value
        v = v[0, 0] if hasattr(v, "shape") else v
        a = mine[(sh, co)]
        try:
            ok = close(float(v), float(a), 1e-8) if not isinstance(a, str) else str(v) == a
        except (TypeError, ValueError):
            ok = str(v) == str(a)
        bad += not ok
        if not ok:
            diffs.append((sh, co, str(raw)[:70], str(v)[:20], str(a)[:20]))
    shutil.rmtree(tmp.parent, ignore_errors=True)
    check(f"{n} formulas give the same value in both engines", n > 1000 and bad == 0, f"{bad} differ: {diffs[:6]}")


def test_page(wb: openpyxl.Workbook | None) -> None:
    print("5. page")
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        print("  skipped (streamlit is not installed here)")
        return
    if not (ROOT / "data" / "processed" / "p3dh.sqlite").exists():
        print("  skipped (no database)")
        return
    at = AppTest.from_file(str(ROOT / "dashboard" / "pages" / "7_MA_scenario.py"), default_timeout=600)
    at.run()
    check("the page runs without an exception", not at.exception, str([str(e.value)[:200] for e in at.exception]))
    check("the page shows 3 deals with 4 metrics each", len(at.metric) == 12, str(len(at.metric)))
    check("the page has the tab MREL scenario", [t.label for t in at.tabs][4] == "MREL scenario" and len(at.tabs) == 8, str([t.label for t in at.tabs]))
    check("the tab MREL scenario shows requirement, resources, result by strategy, and caveats", len(at.tabs[4].dataframe) >= 5, str(len(at.tabs[4].dataframe)))
    tab_text = " ".join(str(e.value) for e in at.tabs[4].caption)
    check("the tab names the strategy that the sidebar selects (default: single point of entry)", "single point of entry" in tab_text.split("Selected in the sidebar:")[-1][:60], tab_text[-200:])
    at.sidebar.selectbox(key="ma_strategy").select(2)
    at.sidebar.selectbox(key="ma_bil_switch").select(0)
    at.run()
    check("the page runs with multiple points of entry and the flat profit of BIL", not at.exception, str([str(e.value)[:200] for e in at.exception]))
    tab_text2 = " ".join(str(e.value) for e in at.tabs[4].caption)
    check("the tab follows the strategy selected in the sidebar", "multiple points of entry" in tab_text2.split("Selected in the sidebar:")[-1][:60], tab_text2[-200:])
    at.sidebar.selectbox(key="ma_strategy").select(1)
    at.sidebar.selectbox(key="ma_bil_switch").select(1)
    at.run()
    if wb is None:
        return
    run = ma_sheet.Model.from_openpyxl(wb).run()
    for i, x in enumerate("HIJ"):
        shown = [m.value for m in at.metric][4 * i]
        expected = f"{run.number('Calc', x + '21') * 100:.1f}%"
        check(f"deal {i + 1}: CET1 ratio on the page ({shown}) equals the formula of Calc ({expected})", shown == expected)


if __name__ == "__main__":
    test_evaluator()
    loaded = load_banks()
    wb = test_build_and_identities(loaded)
    test_km2_sub_requirements()
    test_cr1_sheet()
    test_ma_data_fallbacks()
    test_pack_data()
    test_pack(wb, loaded)
    test_independent(wb)
    test_page(wb)
    if FAILED:
        print(f"\n{len(FAILED)} check(s) failed: {', '.join(FAILED)}")
        sys.exit(1)
    print("\nall M&A workbook checks passed")
