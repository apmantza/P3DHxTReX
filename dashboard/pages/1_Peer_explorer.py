import plotly.express as px
import streamlit as st

import lib

st.set_page_config(page_title="Peer explorer", layout="wide")
st.title("Peer explorer")
st.caption("KM1 key metrics from the clean layer. One row for each bank. Filter by size, geography, and period.")

cls, km = lib.classes(), lib.km1_wide()
counts = km.groupby("period_end")["cet1_ratio"].count()
periods = sorted(counts.index)
full = [p for p in periods if counts[p] >= 100]
period = st.sidebar.selectbox("Period end", periods[::-1], index=periods[::-1].index(full[-1]) if full else 0)
sel = lib.cohort_filters(cls, "peer")
d = km[km["period_end"] == period].merge(sel, on="entity_key")
d = d[d["cet1_ratio"].between(0, 1.5) & d["trea"].gt(0)].copy()
d["greek"] = d["entity_key"].isin(lib.GREEK)
d["trea_bn"] = d["trea"] / 1e9

st.write(f"**{len(d)} banks** at {period}. Banks with no clean value for the period are not shown.")
if d.empty:
    st.stop()

c1, c2 = st.columns(2)
metric = c1.selectbox("Metric", list(lib.RATIO_LABELS), format_func=lib.RATIO_LABELS.get)
group = c2.selectbox("Group by", ["size_class", "peer_group", "region", "country"])
pct = d.dropna(subset=[metric]).copy()
pct["value_pct"] = pct[metric] * 100
fig = px.box(pct, x=group, y="value_pct", points="outliers", hover_name="entity_name",
             category_orders={"size_class": lib.SIZE_ORDER}, labels={"value_pct": f"{lib.RATIO_LABELS[metric]} (%)"})
st.plotly_chart(fig, width="stretch")

st.subheader("CET1 ratio and leverage ratio")
sc = d.dropna(subset=["leverage_ratio"]).copy()
sc = sc[sc["leverage_ratio"].between(0, 0.6)]
sc["cet1_pct"], sc["lev_pct"] = sc["cet1_ratio"] * 100, sc["leverage_ratio"] * 100
fig2 = px.scatter(sc, x="cet1_pct", y="lev_pct", size="trea_bn", color="peer_group", symbol="greek",
                  hover_name="entity_name", hover_data=["country", "size_class"], size_max=40,
                  labels={"cet1_pct": "CET1 ratio (%)", "lev_pct": "Leverage ratio (%)"})
st.plotly_chart(fig2, width="stretch")

show = d[["entity_name", "country", "region", "peer_group", "size_class", "size_basis_eur", "trea", "cet1_ratio",
          "t1_ratio", "total_capital_ratio", "leverage_ratio", "lcr", "nsfr"]].sort_values("trea", ascending=False).copy()
show["size_basis_eur"] = (show["size_basis_eur"] / 1e9).round(1)
show["trea"] = (show["trea"] / 1e9).round(2)
for col in ["cet1_ratio", "t1_ratio", "total_capital_ratio", "leverage_ratio", "lcr", "nsfr"]:
    show[col] = (show[col] * 100).round(1)
show = show.rename(columns={"size_basis_eur": "assets (EUR bn)", "trea": "TREA (EUR bn)", "cet1_ratio": "CET1 (%)", "t1_ratio": "Tier 1 (%)",
                            "total_capital_ratio": "Total capital (%)", "leverage_ratio": "Leverage (%)", "lcr": "LCR (%)", "nsfr": "NSFR (%)"})
st.dataframe(show, hide_index=True, width="stretch")
st.download_button("Download CSV", show.to_csv(index=False).encode("utf-8"), f"peers_{period}.csv", "text/csv")
