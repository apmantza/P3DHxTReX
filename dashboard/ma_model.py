"""Pro-forma model of a bank combination. All inputs come from P3DH (see ma_data.py).

The model is static: it shows the position on the day the deal closes. It has no earnings forecast.
The formulas are in docs/ma_model.md. This module does not use Streamlit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import pandas as pd

from ma_data import IRRBB_ROWS, BankData

NAN = float("nan")
P1_CET1, P1_T1, P1_TC = 0.045, 0.06, 0.08
P2R_CET1_SHARE, P2R_T1_SHARE = 0.5625, 0.75
DEFAULT_CCB = 0.025
LEV_MIN = 0.03
IRRBB_LIMIT = 0.15
BUFFER_RULES = ("max", "acquirer", "target", "custom")
P2R_RULES = ("blend", "acquirer", "target", "custom")
BASES = ("tbv", "cet1", "amount")


class ModelInputError(ValueError):
    """A mandatory input is missing."""


@dataclass
class Deal:
    stake: float = 1.0
    basis: str = "tbv"
    multiple: float = 1.0
    amount: float = 0.0
    cash_share: float = 0.5
    tax_rate: float = 0.25
    fv_markdown_pct: float = 0.0
    integration_pct: float = 0.0
    transaction_pct: float = 0.0
    rwa_acq_change: float = 0.0
    rwa_tgt_change: float = 0.0
    exposure_elim_pct: float = 0.0
    instr_recognition: float = 1.0
    new_cet1: float = 0.0
    new_at1: float = 0.0
    new_t2: float = 0.0
    new_snp: float = 0.0
    new_snr: float = 0.0
    buffer_rule: str = "max"
    buffer_custom: float = 0.0
    p2r_rule: str = "blend"
    p2r_custom: float = 0.0
    floor_cet1: float | None = None


@dataclass
class Result:
    values: dict[str, float]
    acq: dict[str, float]
    tgt: dict[str, float]
    flags: list[tuple[str, str]] = field(default_factory=list)
    inputs: pd.DataFrame = field(default_factory=pd.DataFrame)


def _nz(x: float | None, default: float = 0.0) -> float:
    return default if x is None or (isinstance(x, float) and math.isnan(x)) else x


def _div(a: float | None, b: float | None) -> float:
    if a is None or b is None or b == 0 or math.isnan(a) or math.isnan(b):
        return NAN
    return a / b


def _blend(pairs: list[tuple[float, float]]) -> float:
    """Weighted average. Each pair is (value, weight)."""
    w = sum(p[1] for p in pairs)
    return sum(p[0] * p[1] for p in pairs) / w if w else NAN


def _base(bank: BankData, flags: list[tuple[str, str]], side: str) -> dict[str, float]:
    """Standalone position of one bank, in EUR and as fractions."""
    miss = [n for n in ("cet1", "t1", "tc", "trea") if bank.get(n) is None]
    if miss:
        raise ModelInputError(f"{bank.name}: KM1 values missing at {bank.as_of}: {', '.join(miss)}")
    b: dict[str, float] = {"cet1": bank.get("cet1"), "trea": bank.get("trea")}
    b["at1"] = bank.get("t1") - bank.get("cet1")
    b["t2"] = bank.get("tc") - bank.get("t1")
    b["t1"], b["tc"] = bank.get("t1"), bank.get("tc")
    b["lev_exp"] = _nz(bank.get("lev_exp"), NAN)
    b["total_assets"] = _nz(bank.get("total_assets") or bank.get("cc2_total_assets") or bank.get("lr1_total_assets"), NAN)
    for n in ("hqla", "net_outflow", "asf", "rsf"):
        b[n] = _nz(bank.get(n), NAN)
    p2r = bank.get("p2r")
    if p2r is None:
        flags.append(("warn", f"{side}: no P2R in KM1. The model uses 0."))
    b["p2r"] = _nz(p2r)
    b["p2r_cet1"] = _nz(bank.get("p2r_cet1"), b["p2r"] * P2R_CET1_SHARE)
    b["p2r_t1"] = _nz(bank.get("p2r_t1"), b["p2r"] * P2R_T1_SHARE)
    b["ccb"] = _nz(bank.get("ccb"), DEFAULT_CCB)
    b["ccb_macro"] = _nz(bank.get("ccb_macro"))
    b["ccyb"] = _nz(bank.get("ccyb"))
    b["syrb"] = _nz(bank.get("syrb"))
    b["sii"] = max(_nz(bank.get("gsii")), _nz(bank.get("osii")))
    parts = b["ccb"] + b["ccb_macro"] + b["ccyb"] + b["syrb"] + b["sii"]
    cbr = bank.get("cbr")
    b["cbr_other"] = max(cbr - parts, 0.0) if cbr is not None and cbr - parts > 0.0005 else 0.0
    b["cbr"] = parts + b["cbr_other"]
    b["lev_buffer"] = _nz(bank.get("lev_buffer"))
    lev_req = bank.get("lev_req")
    b["lev_req"] = lev_req if lev_req is not None else LEV_MIN + _nz(bank.get("lev_p2r")) + b["lev_buffer"]
    b["equity"] = _nz(bank.get("cc1_cet1_before_adj") or bank.get("cc2_equity"), NAN)
    b["intangibles"] = abs(_nz(bank.get("cc1_intangibles")))
    ofel = bank.get("km2_ofel")
    b["km2_found"] = float(ofel is not None)
    b["ofel"] = ofel if ofel is not None else b["tc"]
    b["ofel_sub"] = bank.get("km2_ofel_sub") if ofel is not None and bank.get("km2_ofel_sub") is not None else b["tc"]
    b["trea2"] = _nz(bank.get("km2_trea"), b["trea"])
    b["tem"] = _nz(bank.get("km2_tem"), b["lev_exp"])
    b["req_trea"] = _nz(bank.get("km2_req_trea"), NAN)
    b["req_tem"] = _nz(bank.get("km2_req_tem"), NAN)
    b["ae_enc"] = _nz(bank.get("ae_encumbered"), NAN)
    b["ae_unenc"] = _nz(bank.get("ae_unencumbered"), NAN)
    b["npl"] = _nz(bank.get("cr1_loans_npl"), NAN)
    b["loans_perf"] = _nz(bank.get("cr1_loans_performing"), NAN)
    return b


def _standalone_metrics(b: dict[str, float]) -> dict[str, float]:
    m = dict(b)
    m["cet1_ratio"], m["t1_ratio"], m["tc_ratio"] = _div(b["cet1"], b["trea"]), _div(b["t1"], b["trea"]), _div(b["tc"], b["trea"])
    m["lev_ratio"] = _div(b["t1"], b["lev_exp"])
    m["lcr"] = _div(b["hqla"], b["net_outflow"])
    m["nsfr"] = _div(b["asf"], b["rsf"])
    m["req_cet1"] = P1_CET1 + b["p2r_cet1"] + b["cbr"]
    m["req_t1"] = P1_T1 + b["p2r_t1"] + b["cbr"]
    m["req_tc"] = P1_TC + b["p2r"] + b["cbr"]
    m["mrel_ratio"] = _div(b["ofel"], b["trea2"])
    m["mrel_tem_ratio"] = _div(b["ofel"], b["tem"])
    m["mrel_req_total"] = b["req_trea"] + b["cbr"]
    m["ae_ratio"] = _div(b["ae_enc"], b["ae_enc"] + b["ae_unenc"])
    m["npl_ratio"] = _div(b["npl"], b["npl"] + b["loans_perf"])
    _layers(m)
    return m


def _layers(m: dict[str, float]) -> None:
    """Capital headroom against the three SREP layers. The smallest EUR headroom is the distance to MDA."""
    head = {
        "CET1": m["cet1"] - m["req_cet1"] * m["trea"],
        "Tier 1": m["t1"] - m["req_t1"] * m["trea"],
        "Total capital": m["tc"] - m["req_tc"] * m["trea"],
    }
    m["headroom_cet1_eur"], m["headroom_t1_eur"], m["headroom_tc_eur"] = head["CET1"], head["Tier 1"], head["Total capital"]
    layer = min(head, key=head.get)
    m["mda_layer"] = layer
    m["mda_eur"] = head[layer]
    m["mda_bp"] = head[layer] / m["trea"] * 1e4
    m["lev_headroom_bp"] = (m["lev_ratio"] - m["lev_req"]) * 1e4 if not math.isnan(m["lev_ratio"]) else NAN


def standalone(bank: BankData) -> dict[str, float]:
    return _standalone_metrics(_base(bank, [], ""))


def _price(a: dict[str, float], t: dict[str, float], deal: Deal, flags: list[tuple[str, str]]) -> tuple[float, float, float]:
    """Return the price paid for the stake, the tangible book value of the target, and the common equity of the target."""
    equity = t["equity"]
    if math.isnan(equity):
        equity = t["cet1"] + t["intangibles"]
        flags.append(("warn", "Target: CC1 and CC2 have no common equity. The model uses CET1 plus intangible assets."))
    tbv = max(equity - t["intangibles"], 0.0)
    if deal.basis == "amount":
        return deal.amount, tbv, equity
    base = tbv if deal.basis == "tbv" else t["cet1"]
    return deal.stake * deal.multiple * base, tbv, equity


def core(acq: BankData, tgt: BankData, deal: Deal, flags: list[tuple[str, str]] | None = None) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    """Return the pro-forma values and the standalone values of both banks."""
    fl = flags if flags is not None else []
    a, t = _base(acq, fl, "Acquirer"), _base(tgt, fl, "Target")
    k = deal.stake
    price, tbv, equity = _price(a, t, deal, fl)
    cash = deal.cash_share * price
    shares = price - cash
    fv_at = deal.fv_markdown_pct * tbv * (1 - deal.tax_rate)
    integ_pre = deal.integration_pct * tbv
    integ_at = integ_pre * (1 - deal.tax_rate)
    txn = deal.transaction_pct * price
    req_t_cet1 = P1_CET1 + t["p2r_cet1"] + t["cbr"]
    nci_elig = (1 - k) * min(t["cet1"], req_t_cet1 * t["trea"]) if k < 1 else 0.0
    nci_out = (1 - k) * equity if k < 1 else 0.0
    funding = deal.new_cet1 + deal.new_at1 + deal.new_t2 + deal.new_snp + deal.new_snr
    dliq = funding - cash - txn - integ_pre

    v: dict[str, float] = {"price": price, "tbv_target": tbv, "equity_target": equity, "cash": cash, "shares": shares,
                           "txn_cost": txn, "integration_after_tax": integ_at, "fv_after_tax": fv_at, "dliq": dliq,
                           "nci_eligible": nci_elig, "nci_removed": nci_out, "funding": funding}
    v["goodwill_gross"] = price - k * (equity - fv_at)
    v["goodwill"] = max(v["goodwill_gross"], 0.0)
    v["bargain_gain"] = max(-v["goodwill_gross"], 0.0)

    v["cet1"] = a["cet1"] + t["cet1"] - cash + nci_elig - nci_out - k * fv_at - integ_at - txn + deal.new_cet1
    v["at1"] = a["at1"] + deal.instr_recognition * t["at1"] + deal.new_at1
    v["t2"] = a["t2"] + deal.instr_recognition * t["t2"] + deal.new_t2
    v["t1"] = v["cet1"] + v["at1"]
    v["tc"] = v["t1"] + v["t2"]
    ra, rt = a["trea"] * (1 + deal.rwa_acq_change), t["trea"] * (1 + deal.rwa_tgt_change)
    v["trea"] = ra + rt
    v["lev_exp"] = a["lev_exp"] + t["lev_exp"] * (1 - deal.exposure_elim_pct) + dliq
    v["total_assets"] = a["total_assets"] + t["total_assets"] + dliq + v["goodwill"]
    v["cet1_ratio"], v["t1_ratio"], v["tc_ratio"] = _div(v["cet1"], v["trea"]), _div(v["t1"], v["trea"]), _div(v["tc"], v["trea"])
    v["lev_ratio"] = _div(v["t1"], v["lev_exp"])

    wa, wt = ra, rt
    v["ccb"] = a["ccb"]
    for n in ("ccb_macro", "ccyb", "syrb", "cbr_other"):
        v[n] = _blend([(a[n], wa), (t[n], wt)])
    rule = deal.buffer_rule
    v["sii"] = {"max": max(a["sii"], t["sii"]), "acquirer": a["sii"], "target": t["sii"], "custom": deal.buffer_custom}[rule]
    v["cbr"] = v["ccb"] + v["ccb_macro"] + v["ccyb"] + v["syrb"] + v["sii"] + v["cbr_other"]
    if deal.p2r_rule == "blend":
        for n in ("p2r", "p2r_cet1", "p2r_t1"):
            v[n] = _blend([(a[n], wa), (t[n], wt)])
    elif deal.p2r_rule == "custom":
        v["p2r"], v["p2r_cet1"], v["p2r_t1"] = deal.p2r_custom, deal.p2r_custom * P2R_CET1_SHARE, deal.p2r_custom * P2R_T1_SHARE
    else:
        src = a if deal.p2r_rule == "acquirer" else t
        v["p2r"], v["p2r_cet1"], v["p2r_t1"] = src["p2r"], src["p2r_cet1"], src["p2r_t1"]
    v["req_cet1"] = P1_CET1 + v["p2r_cet1"] + v["cbr"]
    v["req_t1"] = P1_T1 + v["p2r_t1"] + v["cbr"]
    v["req_tc"] = P1_TC + v["p2r"] + v["cbr"]
    wl_a, wl_t = a["lev_exp"], t["lev_exp"] * (1 - deal.exposure_elim_pct)
    v["lev_req"] = (_blend([(a["lev_req"] - a["lev_buffer"], wl_a), (t["lev_req"] - t["lev_buffer"], wl_t)])
                    + max(a["lev_buffer"], t["lev_buffer"]))
    _layers(v)

    v["hqla"] = max(a["hqla"] + t["hqla"] + dliq, 0.0)
    v["net_outflow"] = a["net_outflow"] + t["net_outflow"]
    v["lcr"] = _div(v["hqla"], v["net_outflow"])
    v["asf"] = a["asf"] + t["asf"] + funding + shares - k * equity
    v["rsf"] = a["rsf"] + t["rsf"]
    v["nsfr"] = _div(v["asf"], v["rsf"])

    d_own = (v["cet1"] - a["cet1"] - t["cet1"]) + (v["at1"] - a["at1"] - t["at1"]) + (v["t2"] - a["t2"] - t["t2"])
    v["ofel"] = a["ofel"] + t["ofel"] + d_own + deal.new_snp + deal.new_snr
    v["ofel_sub"] = a["ofel_sub"] + t["ofel_sub"] + d_own + deal.new_snp
    v["trea2"] = a["trea2"] * (1 + deal.rwa_acq_change) + t["trea2"] * (1 + deal.rwa_tgt_change)
    v["tem"] = a["tem"] + t["tem"] * (1 - deal.exposure_elim_pct) + dliq
    req_t = t["req_trea"] if not math.isnan(t["req_trea"]) else a["req_trea"]
    req_tt = t["req_tem"] if not math.isnan(t["req_tem"]) else a["req_tem"]
    v["req_trea"] = _blend([(a["req_trea"], a["trea2"] * (1 + deal.rwa_acq_change)), (req_t, t["trea2"] * (1 + deal.rwa_tgt_change))])
    v["req_tem"] = _blend([(a["req_tem"], a["tem"]), (req_tt, t["tem"] * (1 - deal.exposure_elim_pct))])
    v["mrel_ratio"] = _div(v["ofel"], v["trea2"])
    v["mrel_tem_ratio"] = _div(v["ofel"], v["tem"])
    v["mrel_req_total"] = v["req_trea"] + v["cbr"]
    v["mrel_headroom_eur"] = v["ofel"] - v["mrel_req_total"] * v["trea2"]
    v["mrel_headroom_bp"] = (v["mrel_ratio"] - v["mrel_req_total"]) * 1e4
    v["mrel_tem_headroom_bp"] = (v["mrel_tem_ratio"] - v["req_tem"]) * 1e4

    v["ae_ratio"] = _div(a["ae_enc"] + t["ae_enc"], a["ae_enc"] + a["ae_unenc"] + t["ae_enc"] + t["ae_unenc"])
    v["npl_ratio"] = _div(a["npl"] + t["npl"], a["npl"] + a["loans_perf"] + t["npl"] + t["loans_perf"])
    return v, _standalone_metrics(a), _standalone_metrics(t)


def irrbb_table(acq: BankData, tgt: BankData, pf_t1: float) -> pd.DataFrame:
    rows = []
    for code, name in IRRBB_ROWS.items():
        ea, et = acq.irrbb_eve.get(code), tgt.irrbb_eve.get(code)
        na, nt = acq.irrbb_nii.get(code), tgt.irrbb_nii.get(code)
        ea_v, et_v = (ea.value if ea else NAN), (et.value if et else NAN)
        pf = ea_v + et_v if not (math.isnan(ea_v) or math.isnan(et_v)) else NAN
        rows.append({"scenario": name, "acquirer": ea_v, "target": et_v, "pro forma": pf,
                     "pro forma % of Tier 1": _div(pf, pf_t1) * 100 if not math.isnan(pf) else NAN,
                     "acquirer ΔNII": na.value if na else NAN, "target ΔNII": nt.value if nt else NAN})
    return pd.DataFrame(rows)


def inputs_table(acq: BankData, tgt: BankData) -> pd.DataFrame:
    rows = []
    for side, bank in (("Acquirer", acq), ("Target", tgt)):
        for name, it in bank.items.items():
            rows.append({"side": side, "input": name, "value": it.value, "period": it.period, "quality": it.quality, "source": it.source})
        for store, label in ((bank.irrbb_eve, "irrbb_eve"), (bank.irrbb_nii, "irrbb_nii")):
            for code, it in store.items():
                rows.append({"side": side, "input": f"{label}_{code}", "value": it.value, "period": it.period, "quality": it.quality, "source": it.source})
    return pd.DataFrame(rows)


def data_flags(acq: BankData, tgt: BankData, v: dict[str, float], a: dict[str, float], t: dict[str, float]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if acq.key == tgt.key:
        out.append(("warn", "The acquirer and the target are the same entity."))
    if t["trea"] > a["trea"]:
        out.append(("warn", "The target has more risk exposure than the acquirer. The deal is a reverse takeover in size."))
    for side, bank in (("Acquirer", acq), ("Target", tgt)):
        weak = sorted(n for n, it in bank.items.items() if it.value is not None and not it.verified and n != "km2_ofel_pct_trea")
        if weak:
            out.append(("info", f"{side}: inputs without full verification: {', '.join(weak)}."))
        old = sorted(f"{n} ({it.period})" for n, it in bank.items.items() if it.period and it.period != bank.as_of and it.value is not None)
        if old:
            out.append(("info", f"{side}: inputs from an older filing than {bank.as_of}: {', '.join(old)}."))
        if bank.get("km2_ofel") is None:
            out.append(("warn", f"{side}: no KM2 (MREL) filing. The model uses total capital as own funds and eligible liabilities."))
    if math.isnan(t["req_trea"]):
        out.append(("warn", "Target: no MREL requirement. The model uses the acquirer requirement for the target part."))
    if math.isnan(a["req_trea"]):
        out.append(("warn", "Acquirer: no MREL requirement in KM2. MREL headroom is not available."))
    for side, m in (("Acquirer", a), ("Target", t)):
        for names, what in ((("lev_exp",), "leverage exposure"), (("hqla", "net_outflow"), "LCR inputs"), (("asf", "rsf"), "NSFR inputs")):
            if any(math.isnan(m[n]) for n in names):
                out.append(("warn", f"{side}: no {what} in KM1. The pro-forma value is not available."))
        if math.isnan(m["total_assets"]):
            out.append(("warn", f"{side}: no total assets. The pro-forma size class is not available."))
    return out


def run(acq: BankData, tgt: BankData, deal: Deal) -> Result:
    flags: list[tuple[str, str]] = []
    v, a, t = core(acq, tgt, deal, flags)
    flags += data_flags(acq, tgt, v, a, t)
    v.update(capacity(acq, tgt, deal, v))
    seen, uniq = set(), []
    for f in flags:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    return Result(values=v, acq=a, tgt=t, flags=uniq, inputs=inputs_table(acq, tgt))


def capacity(acq: BankData, tgt: BankData, deal: Deal, v: dict[str, float]) -> dict[str, float]:
    """Largest cash part and largest price multiple that keep the pro-forma CET1 ratio at or above the floor.

    CET1 falls one for one with the cash paid, so both limits follow from two model runs.
    """
    if deal.floor_cet1 is None:
        return {}
    floor = deal.floor_cet1
    base = replace(deal, cash_share=0.0)
    v0, _, _ = core(acq, tgt, base)
    max_cash = v0["cet1"] - floor * v0["trea"]
    out = {"cap_max_cash": max_cash, "cap_max_cash_share": _div(max_cash, v["price"]) if v["price"] else NAN}
    if deal.basis != "amount" and (deal.cash_share > 0 or deal.transaction_pct > 0):
        d1, d2 = replace(deal, multiple=1.0), replace(deal, multiple=2.0)
        c1, c2 = core(acq, tgt, d1)[0]["cet1"], core(acq, tgt, d2)[0]["cet1"]
        slope = c2 - c1
        need = floor * v["trea"]
        out["cap_max_multiple"] = 1.0 + (need - c1) / slope if slope < 0 else NAN
    return out


def grid(acq: BankData, tgt: BankData, deal: Deal, multiples: list[float], cash_shares: list[float], metric: str) -> pd.DataFrame:
    """Value of a pro-forma metric for each price multiple and cash share."""
    data = {}
    for cs in cash_shares:
        data[f"{cs:.0%}"] = [core(acq, tgt, replace(deal, multiple=m, cash_share=cs))[0][metric] for m in multiples]
    return pd.DataFrame(data, index=[f"{m:.2f}x" for m in multiples])


def size_class(total_assets: float) -> str:
    if math.isnan(total_assets):
        return "Unclassified"
    if total_assets < 1e10:
        return "Small"
    if total_assets < 1e11:
        return "Medium"
    if total_assets < 2.5e11:
        return "Large"
    return "Very large"
