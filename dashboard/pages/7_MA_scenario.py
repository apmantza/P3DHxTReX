import math

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import lib
import ma_data
import ma_model as mm

st.set_page_config(page_title="M&A scenario", layout="wide")
st.title("M&A scenario: pro-forma combination of two banks")
st.caption("Every input comes from the P3DH clean layer (KM1, OV1, CC1, CC2, KM2, LR1, IRRBB1, AE1, CR1). "
           "The model shows the position on the day the deal closes. P3DH has no market price and no profit data, "
           "so you enter the price and the costs. The formulas are in docs/ma_model.md.")

NAN = float("nan")


def isnan(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def fmt(x, kind: str) -> str:
    if isnan(x):
        return "n/a"
    return {"pct": f"{x * 100:.2f}%", "pct1": f"{x * 100:.1f}%", "bn": f"{x / 1e9:,.2f}", "bp": f"{x:,.0f} bp",
            "x": f"{x:.2f}x", "int": f"{x:,.0f}", "str": str(x)}[kind]


def delta(pf, base, kind: str) -> str:
    if isnan(pf) or isnan(base):
        return ""
    if kind == "pct1":
        return f"{(pf - base) * 100:+.1f} pp"
    if kind == "pct":
        return f"{(pf - base) * 1e4:+,.0f} bp"
    if kind == "bn":
        return f"{(pf / base - 1) * 100:+.1f}%" if base else ""
    if kind == "bp":
        return f"{pf - base:+,.0f} bp"
    return ""


# ---------- selection ----------
cls = lib.classes()
cand = ma_data.candidates(lib.q)
cand = cand[cand["entity_key"].isin(cls["entity_key"])]
dates_all = sorted(cand["period_end"].unique(), reverse=True)

st.sidebar.header("Banks")
acq_options = cls[cls["entity_key"].isin(cand["entity_key"])].sort_values("entity_name")
nbg_key = next(k for k, n in lib.GREEK.items() if n == "NBG")


def label(r) -> str:
    ta = r["total_assets_eur"]
    size = f"EUR {ta / 1e9:,.0f}bn" if not isnan(ta) else "size n/a"
    return f"{r['entity_name']} ({r['country']}, {r['size_class']}, {size})"


labels = {r["entity_key"]: label(r) for _, r in acq_options.iterrows()}
keys = list(labels)
acq_key = st.sidebar.selectbox("Acquirer", keys, index=keys.index(nbg_key) if nbg_key in keys else 0, format_func=labels.get)
as_of = st.sidebar.selectbox("As-of quarter of the acquirer", [d for d in dates_all if d in set(cand.loc[cand["entity_key"] == acq_key, "period_end"])] or dates_all)

cutoff = pd.Timestamp(as_of) - pd.Timedelta(days=380)
latest = cand[(cand["period_end"] <= as_of) & (pd.to_datetime(cand["period_end"]) >= cutoff)]
latest = latest.sort_values("period_end").groupby("entity_key").tail(1)
pool = acq_options[acq_options["entity_key"].isin(latest["entity_key"]) & (acq_options["entity_key"] != acq_key)]
with st.sidebar.expander("Filter the target list", expanded=False):
    f_country = st.multiselect("Country", sorted(pool["country"].dropna().unique()), key="ma_country")
    f_size = st.multiselect("Size class", [s for s in lib.SIZE_ORDER if s in set(pool["size_class"].astype(str))], key="ma_size")
    f_region = st.multiselect("Region", sorted(pool["region"].dropna().unique()), key="ma_region")
if f_country:
    pool = pool[pool["country"].isin(f_country)]
if f_size:
    pool = pool[pool["size_class"].astype(str).isin(f_size)]
if f_region:
    pool = pool[pool["region"].isin(f_region)]
tkeys = list(pool["entity_key"])
if not tkeys:
    st.warning("No target matches the filter.")
    st.stop()
default_t = next((i for i, k in enumerate(tkeys) if "Bank of Cyprus" in labels[k]), 0)
tgt_key = st.sidebar.selectbox(f"Target ({len(tkeys)} banks with KM1 in the 12 months to the as-of quarter)", tkeys, index=default_t, format_func=labels.get)
tgt_as_of = latest.loc[latest["entity_key"] == tgt_key, "period_end"].iloc[0]

try:
    acq = ma_data.load_bank(lib.q, acq_key, as_of)
    tgt = ma_data.load_bank(lib.q, tgt_key, tgt_as_of)
    base_a = mm.standalone(acq)
except mm.ModelInputError as e:
    st.error(str(e))
    st.stop()

# ---------- deal inputs ----------
st.sidebar.header("Deal")
with st.sidebar.expander("Price", expanded=True):
    basis = st.radio("Price based on", ["tbv", "cet1", "amount"], horizontal=True,
                     format_func={"tbv": "Tangible book", "cet1": "CET1 capital", "amount": "Fixed amount"}.get)
    stake = st.slider("Stake bought (%)", 50, 100, 100, 5) / 100
    if basis == "amount":
        amount = st.number_input("Price for the stake (EUR m)", 0.0, 1e6, 1000.0, 50.0) * 1e6
        multiple = 1.0
    else:
        multiple = st.slider("Price multiple (x)", 0.2, 2.5, 1.0, 0.05)
        amount = 0.0
with st.sidebar.expander("Payment and new funding", expanded=True):
    cash_share = st.slider("Cash share of the price (%)", 0, 100, 50, 5) / 100
    st.caption("New instruments in EUR m. They raise cash and capital or MREL resources.")
    new_cet1 = st.number_input("New CET1 (rights issue)", 0.0, 1e6, 0.0, 100.0) * 1e6
    new_at1 = st.number_input("New AT1", 0.0, 1e6, 0.0, 100.0) * 1e6
    new_t2 = st.number_input("New Tier 2", 0.0, 1e6, 0.0, 100.0) * 1e6
    new_snp = st.number_input("New senior non-preferred", 0.0, 1e6, 0.0, 100.0) * 1e6
    new_snr = st.number_input("New senior preferred (MREL eligible)", 0.0, 1e6, 0.0, 100.0) * 1e6
with st.sidebar.expander("Purchase accounting and costs"):
    tax = st.slider("Tax rate (%)", 0, 40, 25) / 100
    fv = st.slider("Fair value write-down of target net assets (% of tangible book)", 0.0, 20.0, 0.0, 0.5) / 100
    integ = st.slider("Integration cost (% of target tangible book, pre-tax)", 0.0, 30.0, 0.0, 0.5) / 100
    txn = st.slider("Transaction cost (% of price)", 0.0, 5.0, 0.0, 0.1) / 100
with st.sidebar.expander("Combination effects"):
    rwa_a = st.slider("Change of acquirer RWA (%)", -10.0, 10.0, 0.0, 0.5) / 100
    rwa_t = st.slider("Change of target RWA (%)", -20.0, 20.0, 0.0, 0.5) / 100
    elim = st.slider("Exposure removed between the two banks (% of target leverage exposure)", 0.0, 10.0, 0.0, 0.5) / 100
    recog = st.slider("Target AT1 and Tier 2 recognised in the group (%)", 0, 100, 100, 10) / 100
with st.sidebar.expander("Requirements of the combined group"):
    p2r_rule = st.selectbox("Pillar 2 requirement", list(mm.P2R_RULES),
                            format_func={"blend": "Blend by RWA", "acquirer": "Acquirer value", "target": "Target value", "custom": "Own value"}.get)
    p2r_custom = st.number_input("Own P2R (%)", 0.0, 10.0, 2.5, 0.25) / 100 if p2r_rule == "custom" else 0.0
    buffer_rule = st.selectbox("G-SII / O-SII buffer", list(mm.BUFFER_RULES),
                               format_func={"max": "Higher of the two", "acquirer": "Acquirer value", "target": "Target value", "custom": "Own value"}.get)
    buffer_custom = st.number_input("Own buffer (%)", 0.0, 5.0, 1.0, 0.25) / 100 if buffer_rule == "custom" else 0.0
    floor = st.number_input("Lowest acceptable CET1 ratio (%)", 5.0, 30.0, round(max(base_a["cet1_ratio"] * 100 - 1.0, 5.0), 1), 0.25) / 100

deal = mm.Deal(stake=stake, basis=basis, multiple=multiple, amount=amount, cash_share=cash_share, tax_rate=tax, fv_markdown_pct=fv,
               integration_pct=integ, transaction_pct=txn, rwa_acq_change=rwa_a, rwa_tgt_change=rwa_t, exposure_elim_pct=elim,
               instr_recognition=recog, new_cet1=new_cet1, new_at1=new_at1, new_t2=new_t2, new_snp=new_snp, new_snr=new_snr,
               buffer_rule=buffer_rule, buffer_custom=buffer_custom, p2r_rule=p2r_rule, p2r_custom=p2r_custom, floor_cet1=floor)
try:
    res = mm.run(acq, tgt, deal)
except mm.ModelInputError as e:
    st.error(str(e))
    st.stop()
v, a, t = res.values, res.acq, res.tgt
pf_size = mm.size_class(v["total_assets"])

st.subheader(f"{acq.name} + {tgt.name}")
st.write(f"Acquirer data: {acq.as_of}. Target data: {tgt.as_of}. "
         f"{acq.country} ({acq.region}) with {tgt.country} ({tgt.region}). "
         f"Size class: {acq.size_class} + {tgt.size_class} gives **{pf_size}**.")
if acq.as_of != tgt.as_of:
    st.info(f"The two banks use different quarters ({acq.as_of} and {tgt.as_of}). The model adds the two positions as they are.")
for level, text in res.flags:
    (st.warning if level == "warn" else st.caption)(text)

cols = st.columns(6)
cols[0].metric("CET1 ratio", fmt(v["cet1_ratio"], "pct"), delta(v["cet1_ratio"], a["cet1_ratio"], "pct") + " vs acquirer")
cols[1].metric("Distance to MDA", fmt(v["mda_bp"], "bp"), f"binding layer: {v['mda_layer']}", delta_color="off")
cols[2].metric("Leverage ratio", fmt(v["lev_ratio"], "pct"), delta(v["lev_ratio"], a["lev_ratio"], "pct") + " vs acquirer")
cols[3].metric("LCR", fmt(v["lcr"], "pct1"), delta(v["lcr"], a["lcr"], "pct1") + " vs acquirer")
cols[4].metric("NSFR", fmt(v["nsfr"], "pct1"), delta(v["nsfr"], a["nsfr"], "pct1") + " vs acquirer")
cols[5].metric("MREL headroom", fmt(v["mrel_headroom_bp"], "bp"), "incl. combined buffer", delta_color="off")

tabs = st.tabs(["Summary", "Capital bridge", "Requirements", "Liquidity and MREL", "Risk profile", "Sensitivity", "Inputs and quality"])

# ---------- summary ----------
with tabs[0]:
    rows = [("Total assets (EUR bn)", "total_assets", "bn"), ("Risk exposure amount (EUR bn)", "trea", "bn"), ("CET1 capital (EUR bn)", "cet1", "bn"),
            ("CET1 ratio", "cet1_ratio", "pct"), ("Tier 1 ratio", "t1_ratio", "pct"), ("Total capital ratio", "tc_ratio", "pct"),
            ("Leverage ratio", "lev_ratio", "pct"), ("LCR", "lcr", "pct1"), ("NSFR", "nsfr", "pct1"),
            ("MREL resources as % of TREA", "mrel_ratio", "pct"), ("Distance to MDA", "mda_bp", "bp"),
            ("Asset encumbrance (AE1)", "ae_ratio", "pct1"), ("Non-performing loans (CR1)", "npl_ratio", "pct")]
    table = pd.DataFrame([{"Metric": lab, "Acquirer": fmt(a[k], kind), "Target": fmt(t[k], kind), "Pro forma": fmt(v[k], kind),
                           "Change vs acquirer": delta(v[k], a[k], kind)} for lab, k, kind in rows])
    st.dataframe(table, hide_index=True, width="stretch", height=(len(table) + 1) * 35 + 3)
    st.markdown("**Deal terms**")
    terms = pd.DataFrame([
        ("Price for the stake (EUR bn)", fmt(v["price"], "bn")),
        ("Tangible book of the target, 100% (EUR bn)", fmt(v["tbv_target"], "bn")),
        ("Price over tangible book", fmt(v["price"] / (stake * v["tbv_target"]) if v["tbv_target"] and stake else NAN, "x")),
        ("Price over book equity", fmt(v["price"] / (stake * v["equity_target"]) if v["equity_target"] and stake else NAN, "x")),
        ("Cash paid (EUR bn)", fmt(v["cash"], "bn")), ("Shares issued (EUR bn)", fmt(v["shares"], "bn")),
        ("Goodwill created: price above fair value of net assets (EUR bn)", fmt(v["goodwill"], "bn")), ("Gain from a bargain purchase: price below fair value of net assets (EUR bn)", fmt(v["bargain_gain"], "bn")),
        ("Change of cash and liquid assets (EUR bn)", fmt(v["dliq"], "bn"))], columns=["Item", "Value"])
    st.dataframe(terms, hide_index=True, width="stretch", height=(len(terms) + 1) * 35 + 3)
    if not isnan(v.get("cap_max_cash", NAN)):
        st.markdown(f"**Capacity at a CET1 floor of {floor:.2%}**")
        st.write(f"- Largest cash payment: EUR {v['cap_max_cash'] / 1e9:,.2f}bn ({fmt(v['cap_max_cash_share'], 'pct1')} of this price).")
        if not isnan(v.get("cap_max_multiple", NAN)):
            st.write(f"- Largest price multiple at this payment mix: {v['cap_max_multiple']:.2f}x.")

# ---------- capital bridge ----------
with tabs[1]:
    k = deal.stake
    steps = [("Acquirer CET1", a["cet1"], "absolute"), ("Target CET1", t["cet1"], "relative"), ("Cash paid for the stake", -v["cash"], "relative"),
             ("Minority interest", v["nci_eligible"] - v["nci_removed"], "relative"),
             ("Fair value marks, costs and fees", -(k * v["fv_after_tax"] + v["integration_after_tax"] + v["txn_cost"]), "relative"),
             ("New CET1", deal.new_cet1, "relative"), ("Pro-forma CET1", v["cet1"], "total")]
    steps = [x for x in steps if x[2] != "relative" or abs(x[1]) > 1e3]
    fig = go.Figure(go.Waterfall(x=[s[0] for s in steps], y=[s[1] / 1e9 for s in steps], measure=[s[2] for s in steps],
                                 text=[f"{s[1] / 1e9:+.2f}" if s[2] == "relative" else f"{s[1] / 1e9:.2f}" for s in steps], textposition="outside"))
    fig.update_layout(title="CET1 capital (EUR bn)", height=420, showlegend=False)
    st.plotly_chart(fig, width="stretch")
    tr = a["trea"] + t["trea"]
    ratio_steps = [("Acquirer", a["cet1"] / a["trea"], "absolute"),
                   ("Add target at book", (a["cet1"] + t["cet1"]) / tr - a["cet1"] / a["trea"], "relative")]
    run_c = a["cet1"] + t["cet1"]
    for lab, amt in (("Cash paid", -v["cash"]), ("Minority interest", v["nci_eligible"] - v["nci_removed"]),
                     ("Marks, costs and fees", -(k * v["fv_after_tax"] + v["integration_after_tax"] + v["txn_cost"])), ("New CET1", deal.new_cet1)):
        ratio_steps.append((lab, amt / tr, "relative"))
        run_c += amt
    ratio_steps.append(("RWA changes", v["cet1"] / v["trea"] - run_c / tr, "relative"))
    ratio_steps = [x for x in ratio_steps if x[2] != "relative" or abs(x[1]) > 1e-6]
    ratio_steps.append(("Pro forma", v["cet1_ratio"], "total"))
    fig2 = go.Figure(go.Waterfall(x=[s[0] for s in ratio_steps], y=[s[1] * 100 for s in ratio_steps], measure=[s[2] for s in ratio_steps],
                                  text=[f"{s[1] * 100:+.2f}" if s[2] == "relative" else f"{s[1] * 100:.2f}" for s in ratio_steps], textposition="outside"))
    fig2.update_layout(title="CET1 ratio (%)", height=420, showlegend=False)
    st.plotly_chart(fig2, width="stretch")
    st.caption("The cash paid is the only large item when the price equals the book value of the target. "
               "A share deal adds the two CET1 amounts. See docs/ma_model.md for the derivation.")

# ---------- requirements ----------
with tabs[2]:
    def req_rows(m: dict) -> dict:
        return {"Pillar 1": None, "Pillar 2 requirement": m["p2r"], "Capital conservation buffer": m["ccb"],
                "Countercyclical buffer": m["ccyb"], "Systemic risk buffer": m["syrb"], "G-SII / O-SII buffer": m["sii"],
                "Combined buffer requirement": m["cbr"], "CET1 requirement (MDA trigger)": m["req_cet1"], "Tier 1 requirement": m["req_t1"],
                "Total capital requirement": m["req_tc"], "CET1 ratio": m["cet1_ratio"], "Tier 1 ratio": m["t1_ratio"],
                "Total capital ratio": m["tc_ratio"], "CET1 headroom (bp)": m["headroom_cet1_eur"] / m["trea"] * 1e4,
                "Tier 1 headroom (bp)": m["headroom_t1_eur"] / m["trea"] * 1e4, "Total capital headroom (bp)": m["headroom_tc_eur"] / m["trea"] * 1e4,
                "Distance to MDA (EUR bn)": m["mda_eur"] / 1e9, "Leverage ratio": m["lev_ratio"], "Leverage requirement": m["lev_req"]}
    ra, rt_, rp = req_rows(a), req_rows(t), req_rows(v)
    rr = []
    for name in ra:
        if name == "Pillar 1":
            continue
        kind = "bp" if "(bp)" in name else ("bn" if "EUR bn" in name else "pct")
        fn = (lambda x: "n/a" if isnan(x) else f"{x:,.0f}") if kind == "bp" else ((lambda x: "n/a" if isnan(x) else f"{x:,.2f}") if kind == "bn" else (lambda x: fmt(x, "pct")))
        rr.append({"Item": name, "Acquirer": fn(ra[name]), "Target": fn(rt_[name]), "Pro forma": fn(rp[name])})
    st.dataframe(pd.DataFrame(rr), hide_index=True, width="stretch", height=(len(rr) + 1) * 35 + 3)
    fig = go.Figure()
    for lab, m in (("Acquirer", a), ("Target", t), ("Pro forma", v)):
        fig.add_trace(go.Bar(name=lab, x=["CET1", "Tier 1", "Total capital"], y=[m["cet1_ratio"] * 100, m["t1_ratio"] * 100, m["tc_ratio"] * 100]))
    fig.add_trace(go.Scatter(name="Pro-forma requirement", x=["CET1", "Tier 1", "Total capital"],
                             y=[v["req_cet1"] * 100, v["req_t1"] * 100, v["req_tc"] * 100], mode="markers", marker=dict(symbol="line-ew", size=40, color="black", line_width=3)))
    fig.update_layout(barmode="group", yaxis_title="% of RWA", height=420)
    st.plotly_chart(fig, width="stretch")
    st.caption("The buffers of the combined group: the countercyclical and systemic risk buffers follow the RWA of each bank. "
               "The G-SII / O-SII buffer follows the rule in the sidebar. The supervisor sets the real Pillar 2 requirement of the group after the deal.")

# ---------- liquidity and MREL ----------
with tabs[3]:
    c1, c2 = st.columns(2)
    liq = pd.DataFrame([
        ("HQLA (EUR bn)", fmt(a["hqla"], "bn"), fmt(t["hqla"], "bn"), fmt(v["hqla"], "bn")),
        ("Net cash outflows (EUR bn)", fmt(a["net_outflow"], "bn"), fmt(t["net_outflow"], "bn"), fmt(v["net_outflow"], "bn")),
        ("LCR", fmt(a["lcr"], "pct1"), fmt(t["lcr"], "pct1"), fmt(v["lcr"], "pct1")),
        ("Available stable funding (EUR bn)", fmt(a["asf"], "bn"), fmt(t["asf"], "bn"), fmt(v["asf"], "bn")),
        ("Required stable funding (EUR bn)", fmt(a["rsf"], "bn"), fmt(t["rsf"], "bn"), fmt(v["rsf"], "bn")),
        ("NSFR", fmt(a["nsfr"], "pct1"), fmt(t["nsfr"], "pct1"), fmt(v["nsfr"], "pct1"))], columns=["Item", "Acquirer", "Target", "Pro forma"])
    c1.markdown("**Liquidity (KM1)**")
    c1.dataframe(liq, hide_index=True, width="stretch", height=(len(liq) + 1) * 35 + 3)
    c1.caption("The model pools the liquidity of both banks. In practice, liquidity can be trapped in a subsidiary. "
               "Cash paid to the target holders leaves the HQLA. New instruments add cash and stable funding.")
    mr = pd.DataFrame([
        ("Own funds and eligible liabilities (EUR bn)", fmt(a["ofel"], "bn"), fmt(t["ofel"], "bn"), fmt(v["ofel"], "bn")),
        ("  of which subordinated (EUR bn)", fmt(a["ofel_sub"], "bn"), fmt(t["ofel_sub"], "bn"), fmt(v["ofel_sub"], "bn")),
        ("TREA of the resolution group (EUR bn)", fmt(a["trea2"], "bn"), fmt(t["trea2"], "bn"), fmt(v["trea2"], "bn")),
        ("Resources as % of TREA", fmt(a["mrel_ratio"], "pct"), fmt(t["mrel_ratio"], "pct"), fmt(v["mrel_ratio"], "pct")),
        ("MREL requirement as % of TREA", fmt(a["req_trea"], "pct"), fmt(t["req_trea"], "pct"), fmt(v["req_trea"], "pct")),
        ("Requirement with combined buffer", fmt(a["mrel_req_total"], "pct"), fmt(t["mrel_req_total"], "pct"), fmt(v["mrel_req_total"], "pct")),
        ("Headroom (bp of TREA)", fmt((a["mrel_ratio"] - a["mrel_req_total"]) * 1e4, "int"), fmt((t["mrel_ratio"] - t["mrel_req_total"]) * 1e4, "int"),
         fmt(v["mrel_headroom_bp"], "int")),
        ("Headroom (EUR bn)", fmt(a["ofel"] - a["mrel_req_total"] * a["trea2"], "bn"), fmt(t["ofel"] - t["mrel_req_total"] * t["trea2"], "bn"),
         fmt(v["mrel_headroom_eur"], "bn")),
        ("Resources as % of TEM", fmt(a["mrel_tem_ratio"], "pct"), fmt(t["mrel_tem_ratio"], "pct"), fmt(v["mrel_tem_ratio"], "pct")),
        ("MREL requirement as % of TEM", fmt(a["req_tem"], "pct"), fmt(t["req_tem"], "pct"), fmt(v["req_tem"], "pct")),
        ("Headroom on TEM (bp)", fmt((a["mrel_tem_ratio"] - a["req_tem"]) * 1e4, "int"), fmt((t["mrel_tem_ratio"] - t["req_tem"]) * 1e4, "int"),
         fmt(v["mrel_tem_headroom_bp"], "int"))], columns=["Item", "Acquirer", "Target", "Pro forma"])
    c2.markdown("**MREL (KM2)**")
    c2.dataframe(mr, hide_index=True, width="stretch", height=(len(mr) + 1) * 35 + 3)
    c2.caption("The pro-forma requirement is the RWA-weighted mix of both requirements. The resolution authority sets the real requirement. "
               "A bank that files no KM2 enters with its total capital only.")

# ---------- risk profile ----------
with tabs[4]:
    mix_names = {"rwa_credit": "Credit risk", "rwa_ccr": "Counterparty credit risk", "rwa_cva": "CVA", "rwa_securitisation": "Securitisation",
                 "rwa_market": "Market risk", "rwa_operational": "Operational risk"}
    mix = []
    for side, bank, w in (("Acquirer", acq, 1 + deal.rwa_acq_change), ("Target", tgt, 1 + deal.rwa_tgt_change)):
        for key, name in mix_names.items():
            val = bank.get(key)
            if val is not None:
                mix.append({"side": side, "risk type": name, "EUR bn": val * w / 1e9})
    mdf = pd.DataFrame(mix)
    if not mdf.empty:
        pf_mix = mdf.groupby("risk type", as_index=False)["EUR bn"].sum().assign(side="Pro forma")
        mdf = pd.concat([mdf, pf_mix])
        st.plotly_chart(px.bar(mdf, x="side", y="EUR bn", color="risk type", title="Risk exposure amount by risk type (OV1)",
                               category_orders={"side": ["Acquirer", "Target", "Pro forma"]}), width="stretch")
    else:
        st.info("No OV1 breakdown is available.")
    irr = mm.irrbb_table(acq, tgt, v["t1"])
    st.markdown("**Interest rate risk in the banking book (IRRBB1): change of economic value of equity**")
    if irr[["acquirer", "target"]].notna().any().any():
        plot = pd.DataFrame({
            "scenario": list(irr["scenario"]) * 3,
            "side": ["Acquirer"] * 6 + ["Target"] * 6 + ["Pro forma"] * 6,
            "% of Tier 1": list(irr["acquirer"] / acq.get("t1") * 100) + list(irr["target"] / tgt.get("t1") * 100) + list(irr["pro forma % of Tier 1"]),
        })
        fig = px.bar(plot, x="scenario", y="% of Tier 1", color="side", barmode="group")
        fig.add_hline(y=-15, line_dash="dash", line_color="red")
        fig.add_hline(y=15, line_dash="dash", line_color="red")
        st.plotly_chart(fig, width="stretch")
        show = irr.copy()
        for c in ("acquirer", "target", "pro forma", "acquirer ΔNII", "target ΔNII"):
            show[c] = show[c] / 1e6
        st.dataframe(show.rename(columns={"acquirer": "acquirer ΔEVE (EUR m)", "target": "target ΔEVE (EUR m)", "pro forma": "pro-forma ΔEVE (EUR m)",
                                          "acquirer ΔNII": "acquirer ΔNII (EUR m)", "target ΔNII": "target ΔNII (EUR m)"}).round(1),
                     hide_index=True, width="stretch", height=(len(show) + 1) * 35 + 3)
        st.caption("The model adds the changes of the two banks in each scenario. It assumes no offset from new hedges. The supervisory limit is 15% of Tier 1.")
    else:
        st.info("No IRRBB1 filing is available for these banks.")

    st.markdown("**Position among all banks in P3DH**")
    others = cls[~cls["entity_key"].isin([acq_key, tgt_key])]
    ta_pf, ta_a = v["total_assets"], a["total_assets"]
    peers = []
    if not isnan(ta_pf) and not isnan(ta_a):
        rank_a = int((cls["total_assets_eur"] > ta_a).sum()) + 1
        rank_pf = int((others["total_assets_eur"] > ta_pf).sum()) + 1
        st.write(f"By total assets, the acquirer ranks {rank_a} of {int(cls['total_assets_eur'].notna().sum())} banks. "
                 f"The combined bank ranks {rank_pf} of {int(others['total_assets_eur'].notna().sum()) + 1}.")
    km = lib.km1_wide()
    km = km[km["period_end"] == as_of]
    cohort = others[others["size_class"].astype(str) == pf_size][["entity_key"]].merge(km, on="entity_key")
    for name, key in (("CET1 ratio", "cet1_ratio"), ("Leverage ratio", "leverage_ratio"), ("LCR", "lcr"), ("NSFR", "nsfr")):
        pf_val = v["cet1_ratio"] if key == "cet1_ratio" else v["lev_ratio"] if key == "leverage_ratio" else v[key]
        lim = 1.5 if key in ("cet1_ratio", "leverage_ratio") else 20
        pool_v = cohort[key].dropna()
        pool_v = pool_v[pool_v.between(0, lim)]
        if len(pool_v) >= 10 and not isnan(pf_val):
            peers.append({"Metric": name, "Pro forma": fmt(pf_val, "pct1" if key in ("lcr", "nsfr") else "pct"),
                          f"Median of {pf_size} banks": fmt(pool_v.median(), "pct1" if key in ("lcr", "nsfr") else "pct"),
                          "Percentile": f"{(pool_v < pf_val).mean() * 100:.0f}", "Banks": len(pool_v)})
    if peers:
        st.dataframe(pd.DataFrame(peers), hide_index=True, width="stretch")
    else:
        st.caption("Fewer than 10 banks in the size class of the combined bank at this quarter. No peer table.")
    cross = "cross-border" if acq.country != tgt.country else "domestic"
    st.caption(f"Geography: {acq.country} with {tgt.country} ({cross}).")

# ---------- sensitivity ----------
with tabs[5]:
    multiples = [round(x, 2) for x in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.4, 1.6, 2.0)]
    shares = [0.0, 0.25, 0.5, 0.75, 1.0]
    if deal.basis == "amount":
        st.info("The grids vary the price multiple. Choose a price based on tangible book or CET1 to use them.")
    else:
        g1 = mm.grid(acq, tgt, deal, multiples, shares, "cet1_ratio") * 100
        g2 = mm.grid(acq, tgt, deal, multiples, shares, "mda_bp")
        c1, c2 = st.columns(2)
        f1 = px.imshow(g1.round(2), text_auto=".2f", aspect="auto", color_continuous_scale="RdYlGn", labels=dict(x="Cash share", y="Price multiple", color="CET1 %"),
                       title="Pro-forma CET1 ratio (%)")
        f2 = px.imshow(g2.round(0), text_auto=".0f", aspect="auto", color_continuous_scale="RdYlGn", color_continuous_midpoint=0,
                       labels=dict(x="Cash share", y="Price multiple", color="bp"), title="Distance to MDA (bp)")
        c1.plotly_chart(f1, width="stretch")
        c2.plotly_chart(f2, width="stretch")
    g3 = pd.DataFrame({f"{x:+.0%}": [mm.core(acq, tgt, mm.Deal(**{**deal.__dict__, "fv_markdown_pct": y, "rwa_tgt_change": x}))[0]["cet1_ratio"] * 100
                                      for y in (0.0, 0.025, 0.05, 0.075, 0.10)] for x in (-0.10, -0.05, 0.0, 0.05, 0.10)},
                      index=[f"{y:.1%}" for y in (0.0, 0.025, 0.05, 0.075, 0.10)])
    st.plotly_chart(px.imshow(g3.round(2), text_auto=".2f", aspect="auto", color_continuous_scale="RdYlGn",
                              labels=dict(x="Change of target RWA", y="Fair value write-down (% of tangible book)", color="CET1 %"),
                              title="Pro-forma CET1 ratio (%): target RWA and write-down"), width="stretch")

# ---------- inputs ----------
with tabs[6]:
    st.write("Each row is one input from P3DH. Quality values: ok, ok_wide, ok_history, ok_tie, rescaled, rescaled_tie, rescaled_nb, converted "
             "are verified by the clean layer. The values untested, unverified, and suspect have no verification. "
             "The ratio cells of KM2 are converted with the own-funds test of the model.")
    inp = res.inputs.copy()
    inp["verified"] = inp["quality"].isin(ma_data.VERIFIED)
    st.dataframe(inp, hide_index=True, width="stretch")
    st.download_button("Download the inputs (CSV)", inp.to_csv(index=False).encode("utf-8"), "ma_inputs.csv", "text/csv")
    out = pd.DataFrame([{"item": k, "pro_forma": v[k], "acquirer": a.get(k, NAN), "target": t.get(k, NAN)} for k in v])
    st.download_button("Download the results (CSV)", out.to_csv(index=False).encode("utf-8"), "ma_results.csv", "text/csv")
