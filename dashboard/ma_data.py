"""Inputs of the M&A scenario model. Every number comes from the P3DH clean layer.

The loader does not use Streamlit. It takes a function query(sql, params) that returns a DataFrame,
so the same code runs in the dashboard (cached) and in tests (plain SQLite).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

Query = Callable[..., pd.DataFrame]

VERIFIED = {"ok", "ok_wide", "ok_history", "ok_tie", "rescaled", "rescaled_tie", "rescaled_nb", "converted", "unit_checked"}

# KM1 (K_61.00), column a (measure_col 10). Ratios are fractions in the clean layer.
KM1 = {
    "cet1": "0010", "t1": "0020", "tc": "0030", "trea": "0040",
    "p2r": "0080", "p2r_cet1": "0090", "p2r_t1": "0100", "ccb": "0120", "ccb_macro": "0130", "ccyb": "0140",
    "syrb": "0150", "gsii": "0160", "osii": "0170", "cbr": "0180", "ocr": "0190",
    "lev_exp": "0210", "lev_ratio": "0220", "lev_p2r": "0230", "lev_buffer": "0260", "lev_req": "0270",
    "hqla": "0280", "net_outflow": "0310", "lcr": "0320", "asf": "0330", "rsf": "0340", "nsfr": "0350",
}
# OV1 (K_60.00), column a.
OV1 = {"rwa_credit": "0010", "rwa_ccr": "0070", "rwa_cva": "0120", "rwa_securitisation": "0210",
       "rwa_market": "0260", "rwa_operational": "0320", "rwa_total": "0380"}
# Cells of other templates: name -> (template, row_code, column_code, sheet-or-cell filter).
CELLS = {
    "cc1_cet1_before_adj": ("K_66.01", "0110", "0010"),
    "cc1_intangibles": ("K_66.01", "0130", "0010"),
    "cc1_total_adj": ("K_66.01", "0360", "0010"),
    "cc1_minority": ("K_66.01", "0090", "0010"),
    "cc1_dta_deducted": ("K_66.01", "0140", "0010"),
    "cc1_dta_temporary": ("K_66.01", "0280", "0010"),
    "cc1_dta_below": ("K_66.01", "0890", "0010"),
    "cc1_at1": ("K_66.01", "0540", "0010"),
    "cc1_t2": ("K_66.01", "0710", "0010"),
    "km2_ofel": ("K_90.01", "0010", "0010"),
    "km2_ofel_sub": ("K_90.01", "0020", "0010"),
    "km2_trea": ("K_90.01", "0030", "0010"),
    "km2_ofel_pct_trea": ("K_90.01", "0040", "0010"),
    "km2_tem": ("K_90.01", "0060", "0010"),
    "km2_req_trea": ("K_90.01", "0120", "0010"),
    "km2_req_trea_sub": ("K_90.01", "0130", "0010"),
    "km2_req_tem": ("K_90.01", "0140", "0010"),
    "km2_req_tem_sub": ("K_90.01", "0150", "0010"),
    "ae_encumbered": ("K_20.01", "0010", "0010"),
    "ae_unencumbered": ("K_20.01", "0010", "0060"),
    "cr1_loans_performing": ("K_21.01", "0020", "0010"),
    "cr1_loans_npl": ("K_21.01", "0020", "0040"),
    "lr1_total_assets": ("K_70.00", "0010", "0010"),
}
IRRBB_ROWS = {"0010": "Parallel up", "0020": "Parallel down", "0030": "Steepener",
              "0040": "Flattener", "0050": "Short rates up", "0060": "Short rates down"}
CC2_ASSETS, CC2_EQUITY = "{K_66.02.b, r0010, c0010}", "{K_66.02.f, r0010, c0010}"


@dataclass(frozen=True)
class Item:
    value: float | None
    period: str | None = None
    source: str = ""
    quality: str = "missing"

    @property
    def verified(self) -> bool:
        return self.quality in VERIFIED


MISSING = Item(None)


@dataclass
class BankData:
    key: str
    name: str
    country: str
    region: str
    peer_group: str
    size_class: str
    as_of: str
    items: dict[str, Item] = field(default_factory=dict)
    irrbb_eve: dict[str, Item] = field(default_factory=dict)
    irrbb_nii: dict[str, Item] = field(default_factory=dict)

    def item(self, name: str) -> Item:
        return self.items.get(name, MISSING)

    def get(self, name: str, default: float | None = None) -> float | None:
        v = self.item(name).value
        return default if v is None or pd.isna(v) else float(v)


def km1_periods(query: Query, entity_key: str) -> list[str]:
    d = query("""SELECT DISTINCT period_end FROM clean_period_fact
                 WHERE entity_key = ? AND template_code = 'K_61.00' AND measure_col = 10 AND row_code IN ('0010', '0040')
                   AND value IS NOT NULL ORDER BY period_end DESC""", (entity_key,))
    return list(d["period_end"])


def candidates(query: Query) -> pd.DataFrame:
    """All entities with Tier 1 capital and TREA in KM1, with the classification and the periods they cover."""
    d = query("""SELECT p.entity_key, p.period_end, MAX(CASE WHEN p.row_code = '0010' THEN p.value END) AS cet1,
                        MAX(CASE WHEN p.row_code = '0040' THEN p.value END) AS trea
                 FROM clean_period_fact p WHERE p.template_code = 'K_61.00' AND p.measure_col = 10 AND p.row_code IN ('0010', '0040')
                 GROUP BY p.entity_key, p.period_end""")
    return d[d["cet1"].notna() & d["trea"].notna() & (d["trea"] > 0)]


def _meta(query: Query, key: str) -> dict:
    m = query("SELECT * FROM v_entity_class WHERE entity_key = ?", (key,))
    if m.empty:
        return {"name": key, "country": "", "region": "", "peer_group": "", "size_class": "Unclassified"}
    r = m.iloc[0]
    return {"name": r["entity_name"], "country": r["country"] or "", "region": r["region"] or "",
            "peer_group": r["peer_group"] or "", "size_class": str(r["size_class"] or "Unclassified")}


def _load_km1(query: Query, key: str, as_of: str, items: dict[str, Item]) -> None:
    codes = tuple(KM1.values())
    d = query(f"""SELECT row_code, value, quality FROM clean_period_fact
                  WHERE entity_key = ? AND template_code = 'K_61.00' AND measure_col = 10 AND period_end = ?
                    AND row_code IN ({','.join('?' * len(codes))}) AND value IS NOT NULL""", (key, as_of) + codes)
    by_code = {r.row_code: r for r in d.itertuples()}
    for name, code in KM1.items():
        r = by_code.get(code)
        if r is not None:
            items[name] = Item(float(r.value), as_of, f"K_61.00 row {code}", r.quality)


def _load_ov1(query: Query, key: str, as_of: str, items: dict[str, Item]) -> None:
    codes = tuple(OV1.values())
    d = query(f"""SELECT row_code, value, quality FROM clean_period_fact
                  WHERE entity_key = ? AND template_code = 'K_60.00' AND measure_col = 10 AND period_end = ?
                    AND row_code IN ({','.join('?' * len(codes))}) AND value IS NOT NULL""", (key, as_of) + codes)
    by_code = {r.row_code: r for r in d.itertuples()}
    for name, code in OV1.items():
        r = by_code.get(code)
        if r is not None:
            items[name] = Item(float(r.value), as_of, f"K_60.00 row {code}", r.quality)


def _pick(frame: pd.DataFrame) -> pd.Series | None:
    """A verified value comes before an unverified one."""
    if frame.empty:
        return None
    return frame.assign(rank=(~frame["quality"].isin(VERIFIED)).astype(int)).sort_values("rank").iloc[0]


def _latest_filing(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep the cells of one filing only: the newest one that has a cell. Cells of two filings must not mix."""
    if frame.empty:
        return frame
    return frame[frame["reference_date"] == frame["reference_date"].max()]


def _load_cells(query: Query, key: str, as_of: str, items: dict[str, Item]) -> None:
    for tpl in sorted({t for t, _, _ in CELLS.values()}):
        d = query("""SELECT reference_date, row_code, column_code, value, quality FROM clean_fact
                     WHERE entity_key = ? AND template_code = ? AND reference_date <= ? AND value IS NOT NULL
                       AND quality <> 'quarantined' AND sheet = '' AND key_descriptor = ''""", (key, tpl, as_of))
        wanted = {(row, col) for t, row, col in CELLS.values() if t == tpl}
        d = d[pd.Series([(r, c) in wanted for r, c in zip(d["row_code"], d["column_code"])], index=d.index, dtype=bool)]
        d = _latest_filing(d)
        for name, (t, row, col) in CELLS.items():
            if t != tpl:
                continue
            hit = _pick(d[(d["row_code"] == row) & (d["column_code"] == col)])
            if hit is not None:
                items[name] = Item(float(hit["value"]), hit["reference_date"], f"{t} row {row} column {col}", hit["quality"])
    d = query("""SELECT reference_date, cell_code, value, quality FROM clean_fact
                 WHERE entity_key = ? AND template_code = 'K_66.02' AND reference_date <= ? AND value IS NOT NULL
                   AND quality <> 'quarantined' AND cell_code IN (?, ?)""", (key, as_of, CC2_ASSETS, CC2_EQUITY))
    d = _latest_filing(d)
    for name, cell in (("cc2_total_assets", CC2_ASSETS), ("cc2_equity", CC2_EQUITY)):
        hit = _pick(d[d["cell_code"] == cell])
        if hit is not None:
            items[name] = Item(float(hit["value"]), hit["reference_date"], f"K_66.02 {cell}", hit["quality"])


def _load_dta(query: Query, key: str, as_of: str, items: dict[str, Item]) -> None:
    """Deferred tax assets of the balance sheet (CC2). The label of the line differs between banks, so the lines are found by their text."""
    d = query("""SELECT reference_date, key_descriptor, value, quality FROM clean_fact
                 WHERE entity_key = ? AND template_code = 'K_66.02' AND reference_date <= ? AND column_code = '0010' AND value IS NOT NULL
                   AND quality <> 'quarantined' AND LOWER(key_descriptor) LIKE '%deferred tax asset%' AND LOWER(key_descriptor) NOT LIKE '%liabilit%'""", (key, as_of))
    d = _latest_filing(d)
    if d.empty:
        return
    kd = d["key_descriptor"].str.lower()
    nonreliant = d[kd.str.contains("not rely") | kd.str.contains("do not r")]
    total = d[~kd.str.contains("of which") & ~kd.str.contains("rely") & ~kd.str.contains("memorandum")]
    if not total.empty:
        r = total.sort_values("value", ascending=False).iloc[0]
        items["dta_total"] = Item(float(r["value"]), r["reference_date"], "K_66.02 " + str(r["key_descriptor"]), r["quality"])
    if not nonreliant.empty:
        r = nonreliant.iloc[0]
        items["dta_nonreliant"] = Item(float(r["value"]), r["reference_date"], "K_66.02 " + str(r["key_descriptor"]), r["quality"])


def _load_assets(query: Query, key: str, as_of: str, items: dict[str, Item]) -> None:
    d = query("""SELECT period_end, total_assets_eur, assets_source, assets_method FROM entity_assets
                 WHERE entity_key = ? AND period_end <= ? AND total_assets_eur IS NOT NULL
                   AND COALESCE(assets_method, '') NOT LIKE 'rejected%' ORDER BY period_end DESC LIMIT 1""", (key, as_of))
    if not d.empty:
        r = d.iloc[0]
        method = str(r["assets_method"])
        verified = method.startswith(("verified", "rescaled", "accepted"))
        items["total_assets"] = Item(float(r["total_assets_eur"]), r["period_end"], f"{r['assets_source']} ({method})",
                                     "ok" if verified else "unverified")


def _load_irrbb(query: Query, key: str, as_of: str, bank: BankData) -> None:
    d = query("""SELECT reference_date, row_code, column_code, value, quality FROM clean_fact
                 WHERE entity_key = ? AND template_code = 'K_68.00' AND reference_date <= ? AND value IS NOT NULL
                   AND quality <> 'quarantined' AND column_code IN ('0010', '0030')""", (key, as_of))
    d = _latest_filing(d)
    for row in IRRBB_ROWS:
        for col, store in (("0010", bank.irrbb_eve), ("0030", bank.irrbb_nii)):
            hit = _pick(d[(d["row_code"] == row) & (d["column_code"] == col)])
            if hit is not None:
                store[row] = Item(float(hit["value"]), hit["reference_date"], f"K_68.00 row {row} column {col}", hit["quality"])


def _ratio_scale(items: dict[str, Item]) -> None:
    """KM2 ratio cells can be fractions or percentage points. The ratio of own funds to TREA decides."""
    ofel, trea, rep = items.get("km2_ofel"), items.get("km2_trea"), items.get("km2_ofel_pct_trea")
    names = ("km2_req_trea", "km2_req_trea_sub", "km2_req_tem", "km2_req_tem_sub")
    scale = None
    if ofel and trea and rep and ofel.value and trea.value and rep.value and trea.value > 0:
        calc = ofel.value / trea.value
        for s in (1.0, 0.01):
            if abs(rep.value * s - calc) <= 0.1 * calc:
                scale = s
                break
    for n in names:
        it = items.get(n)
        if it is None:
            continue
        value = None if scale is None or it.value is None else it.value * scale
        if value is not None and not 0.0 <= value <= 1.0:
            value = None
        quality = "unit_unknown" if scale is None or value is None else "unit_checked"
        items[n] = Item(value, it.period, it.source, quality)


def load_bank(query: Query, key: str, as_of: str) -> BankData:
    meta = _meta(query, key)
    bank = BankData(key=key, as_of=as_of, **meta)
    _load_km1(query, key, as_of, bank.items)
    _load_ov1(query, key, as_of, bank.items)
    _load_cells(query, key, as_of, bank.items)
    _load_dta(query, key, as_of, bank.items)
    _load_assets(query, key, as_of, bank.items)
    _ratio_scale(bank.items)
    _load_irrbb(query, key, as_of, bank)
    return bank


def km2_sub_requirements(query: Query) -> pd.DataFrame:
    """Latest KM2 of each bank: the MREL requirement and the part to be met with own funds or subordinated liabilities, as % of TREA (rows EU-7 and EU-8) and of TEM (EU-9, EU-10).
    The ratio cells are fractions for some banks and percentage points for others, so the unit is tested for each cell: above 1.5 means percentage points, above 100 is an error."""
    d = query("""SELECT entity_key, reference_date, row_code, value FROM clean_fact WHERE template_code = 'K_90.01' AND row_code IN ('0120', '0130', '0140', '0150') AND value IS NOT NULL""")
    if d.empty:
        return pd.DataFrame(columns=["entity_key", "bank", "country", "size_class", "reference_date", "mrel", "sub", "mrel_tem", "sub_tem"])

    def frac(v: float) -> float:
        return float("nan") if v < 0 or v > 100 else (v / 100 if v > 1.5 else v)

    d["v"] = d["value"].map(frac)
    last = d.sort_values("reference_date").groupby(["entity_key", "row_code"]).tail(1)
    wide = last.pivot(index="entity_key", columns="row_code", values="v").rename(columns={"0120": "mrel", "0130": "sub", "0140": "mrel_tem", "0150": "sub_tem"})
    for c in ("mrel", "sub", "mrel_tem", "sub_tem"):
        if c not in wide:
            wide[c] = float("nan")
    wide["reference_date"] = last.groupby("entity_key").reference_date.max()
    cls = query("SELECT entity_key, entity_name AS bank, country, size_class FROM v_entity_class")
    return wide.reset_index().merge(cls, on="entity_key", how="left")
