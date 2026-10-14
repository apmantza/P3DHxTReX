import io
import math

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import lib
import ma_data
import ma_market
import ma_sheet
import ma_workbook as W

st.set_page_config(page_title="M&A scenario", layout="wide")
st.title("M&A scenario: NBG with up to three banks")
st.caption("This page runs the formulas of the Excel file 'M&A calc v2' (sheets Calc and Merger). Every number is a cell of that file. "
           "Data: EBA Pillar 3 Data Hub (clean layer) and the Bloomberg tables of the same database. Download the file at the end of the page.")

NAN = float("nan")
DEFAULT_TARGETS = ["9CZ7TVMR36CYD5TZBS50", "635400L14KNHZXPUZM19", "TUKDD90GPC79G1KOE162"]
COL_NAMES = {"D": "NBG", "E": "T1", "F": "T2", "G": "T3", "H": "NBG+T1", "I": "NBG+T2", "J": "NBG+T3", "K": "NBG at target CET1"}


def isnan(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def fmt(v, kind: str) -> str:
    if isinstance(v, ma_sheet.XlError):
        return "n/a"
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isnan(v):
        return "n/a"
    f = {"pct": lambda x: f"{x * 100:.1f}%", "pct2": lambda x: f"{x * 100:.2f}%", "bn": lambda x: f"{x:,.2f}", "x": lambda x: f"{x:.2f}x",
         "bp": lambda x: f"{x + 0.0:,.0f}", "int": lambda x: f"{x:,.0f}", "eps": lambda x: f"{x:.2f}", "0.0000": lambda x: f"{x:.4f}",
         "flag": lambda x: "yes" if x >= 1 else "NO", "text": str}.get(kind, lambda x: f"{x:.2f}")
    return f(v)


# ---------------------------------------------------------------------------------------- data
cls = lib.classes()
cand = ma_data.candidates(lib.q)
cand = cand[cand["entity_key"].isin(cls["entity_key"])]
nbg_periods = sorted(cand.loc[cand["entity_key"] == W.NBG_KEY, "period_end"], reverse=True)
st.sidebar.header("Banks")
as_of = st.sidebar.selectbox("Quarter of NBG", nbg_periods)
cutoff = pd.Timestamp(as_of) - pd.Timedelta(days=380)
latest = cand[(cand["period_end"] <= as_of) & (pd.to_datetime(cand["period_end"]) >= cutoff)].sort_values("period_end").groupby("entity_key").tail(1)
pool = cls[cls["entity_key"].isin(latest["entity_key"]) & (cls["entity_key"] != W.NBG_KEY)].sort_values("entity_name")


def label(r) -> str:
    ta = r["total_assets_eur"]
    return f"{r['entity_name']} ({r['country']}, {r['size_class']}, " + (f"EUR {ta / 1e9:,.0f}bn)" if not isnan(ta) else "size n/a)")


labels = {r["entity_key"]: label(r) for _, r in pool.iterrows()}
keys = list(labels)
with st.sidebar.expander("Filter the target list"):
    f_country = st.multiselect("Country", sorted(pool["country"].dropna().unique()), key="ma_c")
    f_size = st.multiselect("Size class", [s for s in lib.SIZE_ORDER if s in set(pool["size_class"].astype(str))], key="ma_s")
shown = pool
if f_country:
    shown = shown[shown["country"].isin(f_country)]
if f_size:
    shown = shown[shown["size_class"].astype(str).isin(f_size)]
shown_keys = list(shown["entity_key"])
tkeys = []
for i in range(3):
    opts = list(shown_keys)
    for extra in (DEFAULT_TARGETS[i], st.session_state.get(f"ma_t{i}")):
        if extra in labels and extra not in opts:
            opts.append(extra)
    idx = opts.index(DEFAULT_TARGETS[i]) if DEFAULT_TARGETS[i] in opts else 0
    tkeys.append(st.sidebar.selectbox(f"Target {i + 1}", opts, index=idx, format_func=labels.get, key=f"ma_t{i}"))
if len(set(tkeys)) < 3:
    st.warning("Two targets are the same bank. Choose three different banks.")

if not ma_market.tables_exist(lib.q):
    st.error("The database has no Bloomberg tables. Run scripts/pull_bloomberg.py (see README), then reload this page.")
    st.stop()


@st.cache_resource(show_spinner="Building the model ...")
def build_model(tk: tuple, asof: str, stamp: float):
    banks = []
    for k in (W.NBG_KEY,) + tk:
        periods = [p for p in ma_data.km1_periods(lib.q, k) if p <= asof]
        banks.append(ma_data.load_bank(lib.q, k, periods[0]))
    market = W.load_market(lib.q, banks)
    deals = [W.default_deal(b, sl["lei"]) for b, sl in zip(banks[1:], market["slots"][1:])]
    g = W.default_globals()
    wb = W.build_workbook(banks, deals, g, market, with_original=False)
    return banks, deals, g, market, ma_sheet.Model.from_openpyxl(wb)


banks, deals, g, market, model = build_model(tuple(tkeys), as_of, lib.db_stamp())
age = ma_market.age_days(market["pulled"])
if age is not None and age > 7:
    st.info(f"The Bloomberg data is {age} days old. Run scripts/pull_bloomberg.py to refresh it.")
base = model.run()
nbg = banks[0]
ov: dict[tuple[str, str], object] = {}
sig = "|".join(tkeys) + as_of


def number(label_: str, sheet: str, cell: str, scale: float = 1.0, fmt_: str = "%.3f", step: float = 0.1, key: str | None = None, minv=None, maxv=None, help_=None,
           by_year: bool = False):
    d = base_y.number(sheet, cell)
    d = 0.0 if isnan(d) else d * scale
    k = key or f"{sig}{yr_tag if by_year else ''}:{sheet}:{cell}"
    v = st.number_input(label_, value=float(d), step=step, format=fmt_, min_value=minv, max_value=maxv, key=k, help=help_)
    ov[(sheet, cell)] = v / scale
    return v / scale


# ---------------------------------------------------------------------------------------- inputs
st.sidebar.header("Assumptions")
year_label = st.sidebar.selectbox("Year of the analysis", W.YEARS, index=1, key="ma_year",
                                  help="Sets the profit (consensus, else the last 12 months) and the expected deposit rate in the sheet Calc.")
ov[("Calc", "N15")] = W.YEARS.index(year_label) + 1
base_y = model.run({("Calc", "N15"): ov[("Calc", "N15")]})
yr_tag = f"|{year_label}"
with st.sidebar.expander("Targets and ratios", expanded=True):
    number("CET1 target of NBG (%)", "Calc", "D1", 100, "%.2f", 0.25)
    number("MREL target of NBG (% of RWAs)", "Calc", "D2", 100, "%.2f", 0.25)
    number("Expected deposit rate, average of the year (%)", "Calc", "D3", 100, "%.2f", 0.05, by_year=True,
           help_="Average of each calendar year from the OIS curve and the realised path: " + ", ".join(f"{y}E {v * 100:.2f}%" for y, v in market["rates"]["by_year"].items()))
    number("Tax rate of NBG (%)", "Calc", "N2", 100, "%.2f", 0.5, help_="Default: statutory rate in Bloomberg")
    if st.checkbox("Set the P/E myself", key=f"{sig}:pe_on", help="Default: the P/E of NBG without excess CET1, so a deal that changes nothing gives no upside."):
        number("P/E for the market cap method (x)", "Calc", "N3", 1, "%.1f", 0.5, by_year=True)
    number("Value of excess CET1 in market cap (x)", "Calc", "N6", 1, "%.1f", 0.1, help_="1 = at book value. 0 = method of the original sheet (excess CET1 has no value).")
    number("Assumed subordination requirement without a filed one (% of TREA)", "Calc", "N20", 100, "%.1f", 0.5, minv=0.0, maxv=40.0,
           help_="Used for a combination that reaches the asset limit below when no requirement is filed. 13.5% is the most frequent value of banks of EUR 100bn to 250bn in P3DH.")
    number("Assets from which the assumption applies (EUR bn)", "Calc", "N21", 1, "%.0f", 10.0, minv=0.0)
    number("Floor of the subordination requirement (% of the leverage exposure)", "Calc", "N22", 100, "%.1f", 0.5, minv=0.0, maxv=15.0)
    number("Share of the target's AT1, Tier 2, and eligible liabilities that count in the group (%)", "Calc", "N19", 100, "%.0f", 10.0, minv=0.0, maxv=100.0,
           help_="100% = all count. A subsidiary's instruments count at group level in part (CRR Articles 83 to 88), and as external MREL only if it is a resolution entity.")
    number("Nearest listed peers for a bank without a market cap (k)", "Calc", "N17", 1, "%.0f", 1.0, minv=5.0, maxv=50.0, help_="Median multiple of the k listed banks with the closest return (sheet Peers).")
    number("Valuation basis of such a bank (1 tangible equity, 2 CET1, 3 average)", "Calc", "N18", 1, "%.0f", 1.0, minv=1.0, maxv=3.0,
           help_="CET1 is below tangible equity by the other CET1 deductions. 3 takes the average of both values.")
    number("Growth rate for the cost of equity of the peers, g (%)", "Calc", "N23", 100, "%.1f", 0.5, minv=0.0, maxv=5.0,
           help_="Gordon model: P/TBV = (return - g) / (cost of equity - g). The cost of equity of a peer is g + (return - g) / multiple.")
    for slot_i, cell_ in ((1, "N24"), (3, "N25")):
        if len(banks) > slot_i:
            number(f"Cost of equity of {banks[slot_i].name[:30]} (%; 0 = that of its peers)", "Calc", cell_, 100, "%.1f", 0.5, minv=0.0, maxv=25.0,
                   help_="A bank without a market cap is valued at the multiples of its peers. The peers do not show a size premium, so a higher cost of equity for a smaller, unlisted bank is a judgment. "
                         "The peer value is scaled by (cost of equity of the peers - g) / (this - g). 0 = no adjustment (sheet Calc, rows 224 to 231).")
with st.sidebar.expander("NBG"):
    number("Profit of the year (EUR bn)", "Calc", "D9", 1, "%.3f", 0.05, by_year=True, help_="Default: Bloomberg consensus of the year")
    number("Waived dividend (EUR bn)", "Calc", "D29", 1, "%.2f", 0.05)
    number("Total deferred tax assets, CC2 (EUR bn)", "Calc", "D41", 1, "%.2f", 0.1)
    number("of which DTCs: do not rely on future profitability (EUR bn)", "Calc", "D42", 1, "%.2f", 0.1)
    number("Add DTAs relying on future profitability to CET1 (1 = yes)", "Calc", "N16", 1, "%.0f", 1.0, minv=0.0, maxv=1.0,
           help_="Lever of the original sheet (rows 28 and 29). Default 0: P3DH shows these DTAs are in CET1 already.")
    number("Change of NBG RWAs after the deal (%)", "Calc", "D65", 100, "%.1f", 0.5)
    number("Integration cost, % of target opex", "Calc", "N4", 100, "%.1f", 1.0)
    number("Integration cost, years", "Calc", "N5", 1, "%.0f", 1.0)
for i, (c, x) in enumerate(zip(W.TGT, W.COMBOS)):
    t, d, sl = banks[i + 1], deals[i], market["slots"][i + 1]
    with st.sidebar.expander(f"Deal {i + 1}: {t.name[:34]}", expanded=(i == 0)):
        if not sl["found"]:
            st.warning("No Bloomberg match for the LEI of this bank. Profit, opex, tax rate, and valuation are missing. Enter them below.")
        elif sl["basis"] != "self":
            st.caption("No listed shares. The valuation is the median multiple of the nearest listed peers, on tangible equity and CET1 (tab Review and data).")
        ov[("Calc", f"{c}6")] = st.text_input("Short name", value=str(base.get("Calc", f"{c}6")), key=f"{sig}:name{c}")
        number("Cash share of the price (%)", "Calc", f"{x}2", 100, "%.0f", 5.0, minv=0.0, maxv=100.0)
        number("Stake bought (%)", "Calc", f"{x}4", 100, "%.0f", 5.0, minv=1.0, maxv=100.0)
        number("Premium over the valuation (%)", "Calc", f"{c}37", 100, "%.1f", 1.0)
        if sl["basis"] == "self":
            number("Market cap of 100% (Bloomberg, EUR bn)", "Calc", f"{c}32", 1, "%.3f", 0.1)
        else:
            number("Valuation as P/TBV (x) of the tangible equity of P3DH. Default: nearest peers", "Calc", f"{c}60", 1, "%.3f", 0.05, by_year=True)
        number("Profit of the year (EUR bn)", "Calc", f"{c}9", 1, "%.3f", 0.05, by_year=True)
        number("Operating expenses (EUR bn)", "Calc", f"{c}62", 1, "%.3f", 0.01)
        number("Tax rate (%)", "Calc", f"{c}61", 100, "%.2f", 0.5, help_="Default: statutory rate in Bloomberg")
        number("Transaction cost (% of price)", "Calc", f"{c}63", 100, "%.1f", 0.1)
        number("Fair value write-down (% of tangible equity)", "Calc", f"{c}64", 100, "%.1f", 0.5)
        number("Change of target RWAs (%)", "Calc", f"{c}65", 100, "%.1f", 0.5)
        st.caption("New instruments for the deal (EUR bn)")
        for r, text in ((67, "New CET1"), (68, "New AT1"), (69, "New Tier 2"), (70, "New senior non-preferred"), (71, "New senior preferred")):
            number(text, "Calc", f"{x}{r}", 1, "%.2f", 0.25)
        st.caption("Four-year model")
        R = W.merger_start(i)
        mo = lambda key: R + W.MOFF[key]  # noqa: E731
        number("Cost synergies (% of target costs)", "Merger", f"D{mo('syn_cost')}", 100, "%.1f", 1.0)
        number("Restructuring (% of run-rate synergies)", "Merger", f"D{mo('restr')}", 100, "%.0f", 10.0)
        number("Revenue synergies / attrition (% of target revenues)", "Merger", f"D{mo('syn_rev')}", 100, "%.1f", 0.5)
        for k, col in enumerate(W.YC):
            number(f"Phase-in {W.YEARS[k]} (%)", "Merger", f"{col}{mo('phase')}", 100, "%.0f", 10.0)
        number("Dividend payout (%)", "Merger", f"D{mo('payout')}", 100, "%.0f", 5.0)
        number("RWA growth NBG (% a year)", "Merger", f"D{mo('rwa_g_a')}", 100, "%.1f", 0.5)
        number("RWA growth target (% a year)", "Merger", f"D{mo('rwa_g_t')}", 100, "%.1f", 0.5)
        number("Cost growth (% a year)", "Merger", f"D{mo('cost_g')}", 100, "%.1f", 0.5)
        number("Profit growth of the target, no consensus (% a year)", "Merger", f"D{mo('np_g')}", 100, "%.1f", 0.5)
        number("Cost/income ratio of the target, no consensus (%)", "Merger", f"D{mo('cir')}", 100, "%.0f", 1.0)
        opt = number("RWA optimisation (EUR bn, each year)", "Merger", f"D{mo('rwa_opt')}", 1, "%.1f", 0.5)
        for col in W.YC[1:]:
            ov[("Merger", f"{col}{mo('rwa_opt')}")] = opt

run = model.run(ov)


def val(sheet: str, cell: str):
    return run.get(sheet, cell)


def calc_frame(r0: int, r1: int, cols: list[str]) -> pd.DataFrame:
    rows = []
    for r in range(r0, r1 + 1):
        lab = val("Calc", f"C{r}")
        if lab is None or isinstance(lab, ma_sheet.XlError):
            continue
        kind = W.ROW_KIND.get(r, "bn")
        row = {"Item": str(lab).strip()}
        for c in cols:
            row[str(val("Calc", f"{c}6"))] = fmt(val("Calc", f"{c}{r}"), W.CELL_KIND.get((c, r), kind))
        rows.append(row)
    df = pd.DataFrame(rows)
    # the header row repeats the bank names, so the columns could repeat. Make them unique
    names = []
    for n in df.columns:
        names.append(n if n not in names else n + " ")
    df.columns = names
    return df


def show(df: pd.DataFrame) -> None:
    st.dataframe(df, hide_index=True, width="stretch", height=min((len(df) + 1) * 35 + 3, 1200))


header = {c: str(val("Calc", f"{c}6")) for c in W.ALL}
st.caption(f"Year of the analysis: {year_label}. Expected deposit rate of the year: {fmt(val('Calc', 'D3'), 'pct2')}. NBG profit: EUR {val('Calc', 'D9'):.2f}bn.")
# ---------------------------------------------------------------------------------------- header
st.subheader(" | ".join(f"{header[x]}" for x in W.COMBOS))
cols = st.columns(3)
for col, x, c in zip(cols, W.COMBOS, W.TGT):
    with col:
        st.markdown(f"**{header[x]}**")
        st.metric("CET1 ratio", fmt(val("Calc", f"{x}21"), "pct"), f"{(run.number('Calc', f'{x}21') - run.number('Calc', 'D21')) * 1e4:+,.0f} bp vs NBG")
        st.metric("ROCET1 at the CET1 target", fmt(val("Calc", f"{x}13"), "pct"), fmt(val("Calc", f"{x}14"), "pct") + " vs NBG")
        st.metric("Upside for NBG holders (market cap method)", fmt(val("Calc", f"{x}50"), "pct"))
        st.metric("EPS impact 2027E (four-year model)", fmt(val("Merger", f"E{W.merger_start(W.COMBOS.index(x)) + W.MOFF['e_imp']}"), "pct"))
for i, (b, d) in enumerate(zip(banks[1:], deals)):
    if b.as_of != nbg.as_of:
        st.info(f"{b.name}: data of {b.as_of} (NBG: {nbg.as_of}).")
if val("Calc", "D151") != "OK":
    bad = [f"{lab}" for r, lab in ((147, "CC1 does not add up to KM1 CET1"), (149, "A target uses another quarter than NBG"), (146, "Cash and share split"), (150, "Price above 3 times tangible equity"),
                                   (152, "Profit, opex, tax rate, or valuation is missing for a bank"))
           if any(isinstance(val("Calc", f"{c}{r}"), float) and val("Calc", f"{c}{r}") < 1 for c in "DEFGHIJ")]
    st.warning("Checks: " + "; ".join(bad) + ". See the tab Review and data.")

tabs = st.tabs(["M&A analysis", "Four-year model", "Capital, liquidity, MREL", "Issuance needs", "Sensitivity", "Review and data", "Excel file"])

# ---------------------------------------------------------------------------------------- tab 1
with tabs[0]:
    st.markdown("**M&A analysis** (rows 5 to 17 of Calc)")
    show(calc_frame(5, 17, W.ALL))
    st.markdown("**Equity and market cap** (rows 19 to 46)")
    show(calc_frame(19, 46, W.ALL))
    st.markdown("**Share performance and dilution** (rows 47 to 58)")
    show(calc_frame(47, 58, W.ALL))
    c1, c2 = st.columns(2)
    plot = pd.DataFrame({"deal": [header[c] for c in ["D"] + W.COMBOS + ["K"]],
                         "ROCET1": [val("Calc", f"{c}13") * 100 for c in ["D"] + W.COMBOS + ["K"]]})
    c1.plotly_chart(px.bar(plot, x="deal", y="ROCET1", title="ROCET1 at the CET1 target (%)"), width="stretch")
    up = pd.DataFrame({"deal": [header[c] for c in W.COMBOS], "Market cap method": [val("Calc", f"{c}50") * 100 for c in W.COMBOS],
                       "EPS at target CET1": [val("Calc", f"{c}53") * 100 for c in W.COMBOS]})
    c2.plotly_chart(px.bar(up.melt("deal"), x="deal", y="value", color="variable", barmode="group", title="Upside for NBG holders (%)"), width="stretch")

# ---------------------------------------------------------------------------------------- tab 2
with tabs[1]:
    which = st.radio("Deal", list(range(3)), horizontal=True, format_func=lambda i: f"{header[W.COMBOS[i]]}")
    R = W.merger_start(which)
    st.caption("Same layout as Figure 89 of the original sheet. Capital in EUR bn, profit in EUR m. Deal terms come from the Calc sheet. "
               "NBG CET1 in 2026E is the reported CET1 at the quarter of the data. Years without consensus are extended with the growth inputs.")
    rows = []
    for title, items in W.MERGER_SECTIONS:
        rows.append({"Item": title.upper(), **{y: "" for y in W.YEARS}})
        for key, lab, kind in items:
            r = R + W.MOFF[key]
            rows.append({"Item": lab.strip(), **{y: fmt(val("Merger", f"{c}{r}"), kind) for y, c in zip(W.YEARS, W.YC)}})
    show(pd.DataFrame(rows))
    A = lambda key: [val("Merger", f"{c}{R + W.MOFF[key]}") for c in W.YC]  # noqa: E731
    c1, c2, c3 = st.columns(3)
    eps = pd.DataFrame({"year": W.YEARS, "Before the deal": A("e_eps0"), "Pro forma": A("e_eps1")}).melt("year")
    c1.plotly_chart(px.bar(eps, x="year", y="value", color="variable", barmode="group", title="EPS (EUR)"), width="stretch")
    c2.plotly_chart(go.Figure([go.Bar(x=W.YEARS, y=[v * 100 for v in A("c_ratio")], name="CET1 / RWAs"),
                               go.Scatter(x=W.YEARS, y=[v * 100 for v in A("c_req")], name="CET1 requirement", mode="lines+markers")]).update_layout(title="CET1 ratio (%)"), width="stretch")
    imp = pd.DataFrame({"year": W.YEARS, "Earnings impact": [v * 100 for v in A("e_imp")], "TNAV/share impact": [v * 100 for v in A("v_tps_imp")],
                        "Return on investment": [v * 100 for v in A("e_roi")]}).melt("year")
    c3.plotly_chart(px.line(imp, x="year", y="value", color="variable", markers=True, title="Impact and return (%)"), width="stretch")

# ---------------------------------------------------------------------------------------- tab 3
with tabs[2]:
    allc = [c for c in W.ALL if c != "K"]
    st.markdown("**Additional deal inputs and purchase accounting** (rows 60 to 88)")
    show(calc_frame(60, 88, allc))
    st.markdown("**Peer valuation of a bank without a market cap** (rows 160 to 167)")
    show(calc_frame(160, 167, W.TGT))
    st.markdown("**Regulatory view** (rows 90 to 128)")
    show(calc_frame(90, 128, allc))
    st.markdown("**IRRBB1: change of economic value of equity** (rows 130 to 143). The supervisory limit is 15% of Tier 1.")
    show(calc_frame(130, 143, allc))
    irr = pd.DataFrame([{"scenario": str(val("Calc", f"C{138 + k}")).replace(", % of Tier 1", ""), "bank": header[c], "% of Tier 1": val("Calc", f"{c}{138 + k}") * 100}
                        for k in range(6) for c in allc if isinstance(val("Calc", f"{c}{138 + k}"), float)])
    fig = px.bar(irr, x="scenario", y="% of Tier 1", color="bank", barmode="group")
    fig.add_hline(y=-15, line_dash="dash", line_color="red")
    fig.add_hline(y=15, line_dash="dash", line_color="red")
    st.plotly_chart(fig, width="stretch")
    st.markdown("**Checks** (rows 145 to 151)")
    show(calc_frame(145, 151, allc))

# ---------------------------------------------------------------------------------------- issuance needs
with tabs[3]:
    st.markdown("**Issuance needs and requirements weighted by RWAs** (rows 169 to 201 of Calc)")
    st.caption("The requirement of the combination is the average of the requirements of the two banks, weighted by their RWAs (P2R, combined buffer, and MREL requirement). "
               "A need is the amount to issue after the instruments of both banks. CET1, AT1, and Tier 2 that are issued also count for the MREL. "
               "At the requirements: CET1, Tier 1, total capital, and MREL requirement including the combined buffer. At the targets: CET1 target and MREL target of the sidebar.")
    cols_n = ["D"] + W.TGT + W.COMBOS
    show(calc_frame(169, 201, cols_n))
    deals_n = [("NBG alone", "D")] + [(header[x], x) for x in W.COMBOS]
    c1, c2 = st.columns(2)
    req = pd.DataFrame([{"deal": nm, "layer": lay, "EUR bn": (max(val("Calc", f"{c}190"), val("Calc", f"{c}191")) if row == 190 else val("Calc", f"{c}{row}"))}
                        for nm, c in deals_n for lay, row in (("CET1", 187), ("AT1", 188), ("Tier 2", 189), ("Eligible liabilities", 190))])
    c1.plotly_chart(px.bar(req, x="deal", y="EUR bn", color="layer", title="Issuance need at the requirements (EUR bn)"), width="stretch")
    tgt = pd.DataFrame([{"deal": nm, "layer": lay, "EUR bn": val("Calc", f"{c}{row}")} for nm, c in deals_n for lay, row in (("CET1 to the CET1 target", 193), ("Eligible liabilities to the MREL target", 194))])
    c2.plotly_chart(px.bar(tgt, x="deal", y="EUR bn", color="layer", title="Issuance need at the targets (EUR bn)"), width="stretch")
    mit = pd.DataFrame([{"deal": header[x], "case": case, "EUR bn": val("Calc", f"{x}{row}")} for x in W.COMBOS
                        for case, row in (("The instruments of the target count (N19)", 194), ("None of them counts", 197))])
    st.plotly_chart(px.bar(mit, x="deal", y="EUR bn", color="case", barmode="group", title="MREL issuance need at the target: effect of the capital structure of the target (EUR bn)"), width="stretch")
    st.markdown("**Issuance need at the targets for one deal** (the larger of the need at the targets and at the requirements, row 195)")
    which_n = st.radio("Deal  ", list(range(3)), horizontal=True, format_func=lambda i: header[W.COMBOS[i]], key="need_deal")
    cn, xn = W.TGT[which_n], W.COMBOS[which_n]
    prem_n, cash_n = ov.get(("Calc", f"{cn}37"), 0.0), ov.get(("Calc", f"{xn}2"), 0.5)
    prems_n = [round(prem_n + d, 3) for d in (-0.1, 0.0, 0.1, 0.2, 0.3)]
    cashes_n = [0.0, 0.25, 0.5, 0.75, 1.0]
    zn = [[model.run({**ov, ("Calc", f"{cn}37"): p_, ("Calc", f"{xn}2"): cs}).number("Calc", f"{xn}195") for cs in cashes_n] for p_ in prems_n]
    st.plotly_chart(px.imshow(pd.DataFrame(zn, index=[f"{p_ * 100:+.0f}%" for p_ in prems_n], columns=[f"{cs:.0%}" for cs in cashes_n]).round(2), text_auto=".2f", aspect="auto",
                              color_continuous_scale="RdYlGn_r", labels=dict(x="Cash share", y="Premium", color="EUR bn"), title="Total issuance need at the targets (EUR bn): premium and cash share"), width="stretch")
    st.markdown("**Buckets for AT1 and Tier 2 from the P2R weighted by RWAs, and the instruments to issue** (rows 203 to 222)")
    st.caption("The AT1 bucket is Pillar 1 (1.5%) plus 18.75% of the P2R. The Tier 2 bucket is Pillar 1 (2%) plus 25% of the P2R. An AT1 or Tier 2 above its bucket counts for the MREL only. "
               "The mix issues AT1 and Tier 2 within the buckets first, then senior non-preferred for the subordination need, then senior preferred.")
    show(calc_frame(203, 222, cols_n))
    b1, b2 = st.columns(2)
    bk = pd.DataFrame([{"deal": nm, "item": it, "EUR bn": val("Calc", f"{c}{row}")} for nm, c in deals_n for it, row in (("AT1 bucket", 208), ("AT1 outstanding", 210), ("Tier 2 bucket", 209), ("Tier 2 outstanding", 211))])
    b1.plotly_chart(px.bar(bk, x="deal", y="EUR bn", color="item", barmode="group", title="AT1 and Tier 2: bucket and outstanding (EUR bn)"), width="stretch")
    mix = pd.DataFrame([{"deal": nm, "instrument": it, "EUR bn": val("Calc", f"{c}{row}")} for nm, c in deals_n
                        for it, row in (("CET1", 221), ("AT1", 216), ("Tier 2", 217), ("Senior non-preferred", 219), ("Senior preferred", 220))])
    b2.plotly_chart(px.bar(mix, x="deal", y="EUR bn", color="instrument", title="Instruments to issue to meet the targets (EUR bn)"), width="stretch")
    st.markdown("**Subordination requirements that banks file in P3DH** (KM2, rows EU-8 and EU-10)")
    km = ma_data.km2_sub_requirements(lib.q)
    if not km.empty:
        filed = km[km["sub"].notna()]
        summ = filed.assign(**{"above 0": filed["sub"] > 0}).groupby(filed["size_class"].astype(str)).agg(banks=("sub", "count"), filing_above_0=("above 0", "sum"),
                                                                                                          median_when_above_0=("sub", lambda x: x[x > 0].median()), p25=("sub", lambda x: x[x > 0].quantile(0.25)),
                                                                                                          p75=("sub", lambda x: x[x > 0].quantile(0.75))).reset_index()
        summ = summ.rename(columns={"size_class": "Size class", "banks": "Banks with EU-8 filed", "filing_above_0": "Of which above 0", "median_when_above_0": "Median (% of TREA)", "p25": "25th percentile", "p75": "75th percentile"})
        for col in ("Median (% of TREA)", "25th percentile", "75th percentile"):
            summ[col] = summ[col].map(lambda x: "" if pd.isna(x) else f"{x * 100:.1f}%")
        sc1, sc2 = st.columns([1, 2])
        sc1.dataframe(summ, hide_index=True, width="stretch")
        peers_sub = km[km["size_class"].astype(str).isin(["Large", "Very large"]) & (km["sub"] > 0)].sort_values("sub", ascending=False)
        figs = px.strip(peers_sub, x="size_class", y=peers_sub["sub"] * 100, hover_name="bank", hover_data=["country"], labels={"y": "Subordination requirement (% of TREA)", "size_class": "Size class"},
                        title="Banks of more than EUR 100bn: filed subordination requirement")
        figs.add_hline(y=float(val("Calc", "N20")) * 100, line_dash="dash", line_color="red", annotation_text="assumption N20")
        sc2.plotly_chart(figs, width="stretch")
        mine = km[km["entity_key"].isin([b.key for b in banks])]
        st.caption("Banks of this analysis: " + "; ".join(f"{r.bank[:28]}: EU-8 " + ("not filed" if pd.isna(r['sub']) else f"{r['sub'] * 100:.1f}%") for _, r in mine.iterrows()) +
                   f". The assumption applies to a combination of {float(val('Calc', 'N21')):.0f}bn of assets or more when no requirement is filed. "
                   "Many banks of EUR 100bn to 250bn file exactly 13.5% of TREA. I could not check the legal text here, so check the rule with the resolution authority.")

    st.caption("The needs use the CET1 of the combination (row 20). A cash payment reduces it one for one. A share payment leaves it unchanged, because the new goodwill is deducted against the new equity.")

# ---------------------------------------------------------------------------------------- tab 4
with tabs[4]:
    which = st.radio("Deal ", list(range(3)), horizontal=True, format_func=lambda i: header[W.COMBOS[i]], key="sens_deal")
    c, x = W.TGT[which], W.COMBOS[which]
    R = W.merger_start(which)
    metrics = {"CET1 ratio": ("Calc", f"{x}21", "pct"), "Distance to MDA (bp)": ("Calc", f"{x}106", "bp"), "ROCET1 change to NBG": ("Calc", f"{x}14", "pct"),
               "Upside for NBG holders": ("Calc", f"{x}50", "pct"), "EPS impact 2028E (four-year model)": ("Merger", f"F{R + W.MOFF['e_imp']}", "pct"),
               "MREL needed (EUR bn)": ("Calc", f"{x}27", "bn")}
    metric = st.selectbox("Metric", list(metrics))
    sheet, cell, kind = metrics[metric]
    prem0, cash0 = ov.get(("Calc", f"{c}37"), 0.0), ov.get(("Calc", f"{x}2"), 0.5)
    prems = [round(prem0 + d, 3) for d in (-0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.4)]
    cashes = [0.0, 0.25, 0.5, 0.75, 1.0]
    z = [[model.run({**ov, ("Calc", f"{c}37"): p, ("Calc", f"{x}2"): cs}).number(sheet, cell) * (100 if kind == "pct" else 1) for cs in cashes] for p in prems]
    st.plotly_chart(px.imshow(pd.DataFrame(z, index=[f"{p * 100:+.0f}%" for p in prems], columns=[f"{cs:.0%}" for cs in cashes]).round(2), text_auto=".2f", aspect="auto",
                              color_continuous_scale="RdYlGn", labels=dict(x="Cash share", y="Premium", color=metric), title=f"{metric}: premium and cash share"), width="stretch")
    syn = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    prem_mid = [round(prem0 + d, 3) for d in (-0.1, 0.0, 0.1, 0.2)]
    z2 = [[model.run({**ov, ("Calc", f"{c}37"): p, ("Merger", f"D{R + W.MOFF['syn_cost']}"): s}).number("Merger", f"F{R + W.MOFF['e_imp']}") * 100 for s in syn] for p in prem_mid]
    st.plotly_chart(px.imshow(pd.DataFrame(z2, index=[f"{p * 100:+.0f}%" for p in prem_mid], columns=[f"{s:.0%}" for s in syn]).round(2), text_auto=".2f", aspect="auto",
                              color_continuous_scale="RdYlGn", color_continuous_midpoint=0, labels=dict(x="Cost synergies (% of target costs)", y="Premium", color="%"),
                              title="EPS impact 2028E (%): premium and cost synergies"), width="stretch")
    cap_cash = None
    base_cash = model.run({**ov, ("Calc", f"{x}2"): 0.0})
    floor = base.number("Calc", "D1")
    price = run.number("Calc", f"{c}38")
    max_cash = base_cash.number("Calc", f"{x}20") - floor * base_cash.number("Calc", f"{x}8")
    st.info(f"At a CET1 ratio of {floor:.1%}, the largest cash payment for this deal is EUR {max_cash:,.2f}bn "
            f"({max_cash / price:.0%} of the price of EUR {price:,.2f}bn)." if price else "No price.")

# ---------------------------------------------------------------------------------------- tab 5
with tabs[5]:
    st.markdown("**Review of the original sheet.** What the sheet did, and what Calc does.")
    st.table(pd.DataFrame(W.REVIEW, columns=["Where", "Type", "Finding", "Treatment in Calc"]))
    st.markdown("**Data of the banks (sheet P3DH)**")
    rows = []
    for key, lab, kind in W.P3DH_ITEMS:
        row = {"Item": lab}
        for j, b in enumerate(banks):
            v, period, quality = W.item_value(b, key, kind)
            row[b.name[:24]] = "" if v is None else (v if isinstance(v, str) else (f"{v:,.3f}" if kind == "bn" else f"{v:.4f}"))
            row[f"q{j}"] = "" if quality in (None, "ok", "ok_wide", "ok_history", "ok_tie", "rescaled", "rescaled_tie", "rescaled_nb", "converted", "unit_checked") else quality
        rows.append(row)
    pf = pd.DataFrame(rows)
    st.dataframe(pf[[c for c in pf.columns if not c.startswith("q") or pf[c].astype(bool).any()]], hide_index=True, width="stretch")
    st.caption("Amounts in EUR bn. A column q0, q1, ... shows a quality value that is not verified by the clean layer.")
    st.markdown("**Bloomberg data used** (sheet Market). Linked to P3DH by the LEI. Pulls: " + ", ".join(f"{k} {v[:10]}" for k, v in sorted(market["pulled"].items())))
    mrows = []
    for sl, c in zip(market["slots"], W.BANK_COLS):
        mrows.append({"Bank": str(val("Calc", f"{c}6")), "Bloomberg name": sl.get("name") or "not found", "Market basis": sl["basis"], "Ticker": sl.get("ticker") or "",
                      "Valuation basis": str(val("Calc", f"{c}129")), "Valuation (EUR bn)": fmt(val("Calc", f"{c}32"), "bn"), "P/TBV": fmt(val("Calc", f"{c}34"), "x"),
                      "Profit of the year (EUR bn)": fmt(val("Calc", f"{c}9"), "bn"), "Opex (EUR bn)": fmt(val("Calc", f"{c}62"), "bn"), "Tax rate": fmt(val("Calc", f"{c}61"), "pct"),
                      "Rating S&P / Moody's": f"{sl.get('rating_sp') or ''} / {sl.get('rating_moodys') or ''}"})
    st.dataframe(pd.DataFrame(mrows), hide_index=True, width="stretch")
    st.markdown("**Nearest peers for banks without a market cap** (sheet Peers): the median P/TBV (against RoTE) and P/CET1 (against RoCET1) of the k listed European banks of P3DH with the closest return.")
    pe = pd.DataFrame(market["peers"]["rows"])
    st.caption(f"{len(pe)} listed banks. Linear fit of P/TBV on RoTE, for information only: slope {val('Peers', 'V4'):.2f}, intercept {val('Peers', 'V5'):.3f}, R squared {val('Peers', 'V6'):.2f}. "
               "The line is pulled up by a few banks with a high return and a high multiple, so the valuation uses the nearest peers.")
    basis = st.radio("Basis of the chart", ["Tangible equity (P/TBV against RoTE)", "CET1 (P/CET1 against RoCET1)"], horizontal=True, key="peer_basis")
    on_cet1 = basis.startswith("CET1")
    xcol, ycol = ("rocet1", "pcet1") if on_cet1 else ("rote", "ptbv")
    fig = px.scatter(pe, x=xcol, y=ycol, hover_name="name", hover_data=["country", "ticker"], opacity=0.6,
                     labels=dict(rote="Return on tangible equity", ptbv="P/TBV (x)", rocet1="Return on CET1", pcet1="P/CET1 (x)"))
    for t, c in enumerate(W.TGT):
        pc = W.peer_cols(t)
        if str(val("Calc", f"{c}129")) != "Nearest peers":
            continue
        xv = val("Peers", f"{pc['d_cet1' if on_cet1 else 'd_tbv']}5")
        yv = val("Peers", f"{pc['m_cet1' if on_cet1 else 'm_tbv']}7")
        if isinstance(xv, float) and isinstance(yv, float):
            fig.add_trace(go.Scatter(x=[xv], y=[yv], mode="markers+text", text=[str(val("Calc", f"{c}6"))], textposition="top center", marker=dict(size=13, symbol="diamond"), name=str(val("Calc", f"{c}6"))))
    st.plotly_chart(fig, width="stretch")
    st.markdown("**Average deposit rate (DFR) by period** (sheet Market). Realised for periods that are over, then OIS forward rate plus spread.")
    kind = st.radio("Period", ["Y", "H", "Q"], horizontal=True, format_func={"Y": "Year", "H": "Half year", "Q": "Quarter"}.get, key="dfr_kind")
    dfr = pd.DataFrame([{"Period": q_["label"], "Average (%)": round(q_["avg"] * 100, 3), "Basis": q_["status"]} for q_ in market["rates"]["periods"] if q_["type"] == kind])
    cdf1, cdf2 = st.columns([1, 2])
    cdf1.dataframe(dfr, hide_index=True, width="stretch")
    cdf2.plotly_chart(px.bar(dfr, x="Period", y="Average (%)", color="Basis", title="Average deposit rate (%)"), width="stretch")
    st.caption("Deposit rate changes since 2024: " + ", ".join(f"{d_} {v * 100:.2f}%" for d_, v in market["rates"]["history"]) + f". Spread of the deposit rate to ESTR: {(market['rates']['spread'] or 0) * 1e4:.1f} bp.")

# ---------------------------------------------------------------------------------------- tab 6
with tabs[6]:
    st.write("The file has the sheets Guide, Review, Calc, Merger, P3DH, Market, Peers, and Original (user). "
             "It uses your inputs of this page. Every number is a formula. The sheets Market and Peers have Bloomberg data. Do not publish the file.")
    if st.button("Prepare the Excel file"):
        wb = W.build_workbook(banks, deals, g, market, overrides=ov)
        buf = io.BytesIO()
        wb.save(buf)
        st.session_state["ma_xlsx"] = buf.getvalue()
    if "ma_xlsx" in st.session_state:
        st.download_button("Download M&A calc.xlsx", st.session_state["ma_xlsx"], "M&A calc v2.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
