"""Tests of the M&A model: identities on made-up banks, then a smoke test on the real database.

  .venv/Scripts/python scripts/test_ma_model.py
"""

from __future__ import annotations

import math
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dashboard"))
import ma_data  # noqa: E402
import ma_model as mm  # noqa: E402
from ma_data import BankData, Item  # noqa: E402

AS_OF = "2026-06-30"
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {name}{(' - ' + detail) if detail and not ok else ''}")
    if not ok:
        FAILED.append(name)


def close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def make(key: str, **values: float) -> BankData:
    base = {"cet1": 10e9, "t1": 11e9, "tc": 13e9, "trea": 80e9, "p2r": 0.02, "p2r_cet1": 0.01125, "p2r_t1": 0.015, "ccb": 0.025,
            "ccyb": 0.005, "osii": 0.01, "cbr": 0.04, "lev_exp": 250e9, "lev_req": 0.03, "hqla": 40e9, "net_outflow": 25e9,
            "asf": 150e9, "rsf": 120e9, "total_assets": 260e9, "cc1_cet1_before_adj": 11e9, "cc1_intangibles": -1e9,
            "km2_ofel": 25e9, "km2_ofel_sub": 20e9, "km2_trea": 80e9, "km2_tem": 250e9, "km2_req_trea": 0.22, "km2_req_tem": 0.06}
    base.update(values)
    bank = BankData(key=key, name=key, country="XX", region="R", peer_group="core", size_class="Large", as_of=AS_OF)
    bank.items = {n: Item(v, AS_OF, "test", "ok") for n, v in base.items()}
    return bank


def unit_tests() -> None:
    print("identities on made-up banks")
    acq = make("A")
    tgt = make("T", cet1=4e9, t1=4e9, tc=4.6e9, trea=30e9, lev_exp=90e9, total_assets=95e9, hqla=12e9, net_outflow=9e9, asf=50e9,
               rsf=40e9, cc1_cet1_before_adj=4.6e9, cc1_intangibles=-0.4e9, km2_ofel=8e9, km2_ofel_sub=6e9, km2_trea=30e9, km2_tem=90e9,
               ccyb=0.01, osii=0.0, cbr=0.035, p2r=0.03, p2r_cet1=0.016875, p2r_t1=0.0225, km2_req_trea=0.2)
    shares = mm.Deal(cash_share=0.0)
    v, a, t = mm.core(acq, tgt, shares)
    check("share deal at any price: CET1 is the sum", close(v["cet1"], a["cet1"] + t["cet1"]))
    check("RWA is the sum", close(v["trea"], 110e9))
    check("share deal leaves liquidity unchanged", close(v["dliq"], 0.0) and close(v["hqla"], 52e9))
    check("blended CCyB is RWA weighted", close(v["ccyb"], (0.005 * 80 + 0.01 * 30) / 110))
    check("O-SII buffer is the maximum", close(v["sii"], 0.01))

    cash = mm.Deal(cash_share=1.0, multiple=1.2)
    v, a, t = mm.core(acq, tgt, cash)
    price = 1.2 * (4.6e9 - 0.4e9)
    check("price is multiple times TBV", close(v["price"], price))
    check("all cash: CET1 falls by the price", close(v["cet1"], 14e9 - price))
    check("cash leaves HQLA and exposure by the same amount", close(v["hqla"], 52e9 - price) and close(v["lev_exp"], 340e9 - price))
    check("goodwill is price minus equity", close(v["goodwill"], price - 4.6e9))
    eq_route = (a["cet1"] + 0.0 - v["goodwill"] - 0.4e9 - (4.6e9 - 0.4e9 - t["cet1"]))
    check("CET1 equals the equity route (equity - goodwill - intangibles - other deductions)", close(v["cet1"], eq_route))

    costs = mm.Deal(cash_share=0.0, transaction_pct=0.02, integration_pct=0.1, fv_markdown_pct=0.05, tax_rate=0.25)
    v, a, t = mm.core(acq, tgt, costs)
    tbv = 4.2e9
    expected = 14e9 - 0.02 * v["price"] - 0.1 * tbv * 0.75 - 0.05 * tbv * 0.75
    check("costs and fair value marks reduce CET1 after tax", close(v["cet1"], expected))

    bargain = mm.Deal(cash_share=1.0, multiple=0.5)
    v, a, t = mm.core(acq, tgt, bargain)
    check("bargain purchase: no goodwill, a gain", v["goodwill"] == 0 and v["bargain_gain"] > 0)
    check("bargain purchase: CET1 formula holds", close(v["cet1"], 14e9 - v["price"]))

    part = mm.Deal(stake=0.6, cash_share=1.0)
    v, a, t = mm.core(acq, tgt, part)
    req_t = 0.045 + t["p2r_cet1"] + t["cbr"]
    nci = 0.4 * min(t["cet1"], req_t * t["trea"])
    check("60% stake: NCI is limited by the CET1 requirement", close(v["nci_eligible"], nci))
    check("60% stake: CET1 formula", close(v["cet1"], 14e9 - v["price"] + nci - 0.4 * 4.6e9))
    check("60% stake: RWA is fully consolidated", close(v["trea"], 110e9))

    fund = mm.Deal(cash_share=1.0, new_cet1=1e9, new_at1=0.5e9, new_snp=2e9)
    v, a, t = mm.core(acq, tgt, fund)
    check("new funding adds to cash", close(v["dliq"], 3.5e9 - v["price"]))
    check("new MREL debt adds to eligible liabilities, not to capital", close(v["ofel"] - (a["ofel"] + t["ofel"]), (v["cet1"] - 14e9) + 0.5e9 + 2e9))
    check("subordinated resources exclude senior preferred", close(v["ofel_sub"] - v["ofel"], a["ofel_sub"] + t["ofel_sub"] - a["ofel"] - t["ofel"]))

    floor = 0.14
    deal = mm.Deal(cash_share=0.6, multiple=1.0, floor_cet1=floor)
    r = mm.run(acq, tgt, deal)
    at_limit = replace(deal, cash_share=r.values["cap_max_cash_share"])
    check("capacity: cash limit gives exactly the floor", close(mm.core(acq, tgt, at_limit)[0]["cet1_ratio"], floor, 1e-9))
    at_mult = replace(deal, multiple=r.values["cap_max_multiple"])
    check("capacity: multiple limit gives exactly the floor", close(mm.core(acq, tgt, at_mult)[0]["cet1_ratio"], floor, 1e-9))

    layers = mm.core(acq, tgt, shares)[0]
    check("MDA distance is the smallest layer", close(layers["mda_eur"], min(layers["headroom_cet1_eur"], layers["headroom_t1_eur"], layers["headroom_tc_eur"])))
    check("size class thresholds", [mm.size_class(x) for x in (9.9e9, 1e10, 99e9, 1e11, 2.4e11, 2.5e11)] == ["Small", "Medium", "Medium", "Large", "Large", "Very large"])
    grid = mm.grid(acq, tgt, mm.Deal(), [0.8, 1.0, 1.2], [0.0, 0.5, 1.0], "cet1_ratio")
    check("grid is monotonic in price and cash", (grid.diff(axis=0).iloc[1:] <= 1e-12).all().all() and (grid.diff(axis=1).iloc[:, 1:] <= 1e-12).all().all())

    nokm2 = make("N")
    for n in [k for k in nokm2.items if k.startswith("km2_")]:
        del nokm2.items[n]
    v, _, _ = mm.core(nokm2, tgt, shares)
    check("missing KM2 falls back to total capital", close(v["ofel"], 13e9 + 8e9) and math.isnan(v["req_trea"]))
    try:
        mm.core(make("X", cet1=None), tgt, shares)
        check("missing CET1 raises an error", False)
    except mm.ModelInputError:
        check("missing CET1 raises an error", True)


def database_tests() -> None:
    db = ROOT / "data" / "processed" / "p3dh.sqlite"
    if not db.exists():
        print("database tests skipped (no database)")
        return
    print("smoke test on the database")
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)

    def q(sql: str, params: tuple = ()) -> pd.DataFrame:
        return pd.read_sql_query(sql, conn, params=params)

    nbg = "5UMCZOEYKCVFAW8ZLO05"
    names = {"BoC": "Bank of Cyprus%", "BIL": "Banque Internationale%Luxembourg%", "Optima": "Optima%", "HCOB": "Hamburg Commercial%",
             "Banca Transilvania": "Banca Transilvania%", "BPER": "BPER%"}
    cand = ma_data.candidates(q)
    acq = ma_data.load_bank(q, nbg, AS_OF)
    check("NBG CET1 ratio at 2026-06-30 is 16.97%", close(mm.standalone(acq)["cet1_ratio"], 0.1697, 1e-3), f"{mm.standalone(acq)['cet1_ratio']:.4f}")
    check("NBG standalone MDA distance is positive", mm.standalone(acq)["mda_bp"] > 0)
    for label, pattern in names.items():
        row = q("SELECT entity_key FROM entity WHERE entity_name LIKE ? LIMIT 1", (pattern,))
        if row.empty:
            print(f"  skip {label}: not found")
            continue
        key = row.iloc[0, 0]
        periods = sorted(cand.loc[cand["entity_key"] == key, "period_end"])
        if not periods:
            print(f"  skip {label}: no KM1")
            continue
        as_of = max(p for p in periods if p <= AS_OF) if any(p <= AS_OF for p in periods) else periods[-1]
        tgt = ma_data.load_bank(q, key, as_of)
        r = mm.run(acq, tgt, mm.Deal(cash_share=0.5, floor_cet1=0.14))
        v = r.values
        sane = 0.03 < v["cet1_ratio"] < 0.4 and 0.0 < v["lev_ratio"] < 0.3 and v["trea"] > acq.get("trea")
        check(f"NBG + {label} ({tgt.name}, {as_of}): CET1 {v['cet1_ratio']:.1%}, leverage {v['lev_ratio']:.1%}, LCR {v['lcr']:.0%}", sane)
        t = mm.irrbb_table(acq, tgt, v["t1"])
        check(f"  IRRBB table has 6 scenarios", len(t) == 6)


if __name__ == "__main__":
    unit_tests()
    database_tests()
    if FAILED:
        print(f"\n{len(FAILED)} check(s) failed: {', '.join(FAILED)}")
        sys.exit(1)
    print("\nall M&A model checks passed")
