import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import lib

st.set_page_config(page_title="Greek banks", layout="wide")
st.title("Greek banks against a peer cohort")
st.caption("Lines: the four Greek banks. Dashed line: median of the cohort (at least 10 banks in a period). "
           "Alpha Bank and Eurobank have not filed 30/06/2026.")

cls, km = lib.classes(), lib.km1_wide()
dim = st.sidebar.selectbox("Cohort dimension", ["All banks", "peer_group", "size_class", "region", "country"])
if dim == "All banks":
    members = cls
    label = "All banks"
else:
    value = st.sidebar.selectbox("Cohort value", [v for v in lib.SIZE_ORDER if dim == "size_class" and v in set(cls[dim].astype(str))]
                                 or sorted(cls[dim].dropna().astype(str).unique()))
    members = cls[cls[dim].astype(str) == value]
    label = f"{dim}: {value}"
metric = st.sidebar.selectbox("Metric", list(lib.RATIO_LABELS), format_func=lib.RATIO_LABELS.get)

d = km.merge(members[["entity_key"]], on="entity_key").dropna(subset=[metric])
d = d[d[metric].between(0, 1.5 if metric != "lcr" and metric != "nsfr" else 20)]
med = d.groupby("period_end")[metric].agg(["median", "count"]).reset_index()
med = med[med["count"] >= 10]

fig = go.Figure()
for key, name in lib.GREEK.items():
    g = km[(km["entity_key"] == key)].dropna(subset=[metric]).sort_values("period_end")
    fig.add_trace(go.Scatter(x=g["period_end"], y=g[metric] * 100, mode="lines+markers", name=name))
fig.add_trace(go.Scatter(x=med["period_end"], y=med["median"] * 100, mode="lines", name=f"Median, {label}",
                         line=dict(dash="dash", color="grey"), customdata=med["count"],
                         hovertemplate="%{y:.1f}% (N=%{customdata})"))
fig.update_layout(yaxis_title=f"{lib.RATIO_LABELS[metric]} (%)", hovermode="x unified", height=520)
st.plotly_chart(fig, width="stretch")

latest = km.dropna(subset=[metric])
latest = latest[latest["entity_key"].isin(lib.GREEK)].sort_values("period_end").groupby("entity_key").tail(1)
last_med = med.iloc[-1] if len(med) else None
rows = []
for r in latest.itertuples():
    pool = d[d["period_end"] == r.period_end][metric]
    rank = (pool < getattr(r, metric)).mean() * 100 if len(pool) else float("nan")
    name = lib.RATIO_LABELS[metric]
    rows.append({"bank": lib.GREEK[r.entity_key], "latest period": r.period_end, f"{name} (%)": round(getattr(r, metric) * 100, 1),
                 "cohort median (%)": round(pool.median() * 100, 1) if len(pool) else float("nan"), "cohort N": len(pool),
                 "percentile in cohort": round(rank)})
st.subheader("Latest value and rank in the cohort")
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
