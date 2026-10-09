import plotly.express as px
import streamlit as st

import lib

st.set_page_config(page_title="Encumbrance", layout="wide")
st.title("Asset encumbrance (AE1)")
st.caption("Encumbered assets divided by total assets of the institution (carrying amounts). "
           "AE1 values are medians over the previous 4 quarters.")

cls = lib.classes()
fact = lib.q("""SELECT entity_key, reference_date, row_code, row_label, column_code, value FROM clean_fact
                WHERE template_code = 'K_20.01' AND quality <> 'quarantined' AND column_code IN ('0010', '0060')""")
dates = fact.groupby("reference_date")["entity_key"].nunique()
options = sorted(dates.index, reverse=True)
date = st.sidebar.selectbox("Reference date", options, index=options.index(dates.idxmax()),
                            format_func=lambda d: f"{d} ({dates[d]} banks)")
sel = lib.cohort_filters(cls, "ae")

f = fact[fact["reference_date"] == date]
tot = f[f["row_code"] == "0010"].pivot_table(index="entity_key", columns="column_code", values="value", aggfunc="first")
tot = tot.rename(columns={"0010": "encumbered", "0060": "unencumbered"}).fillna(0)
tot["assets"] = tot["encumbered"] + tot["unencumbered"]
tot = tot[tot["assets"] > 0]
tot["ratio_pct"] = tot["encumbered"] / tot["assets"] * 100
d = tot.reset_index().merge(sel, on="entity_key")
st.write(f"**{len(d)} banks** at {date}.")
if d.empty:
    st.stop()

group = st.selectbox("Group by", ["size_class", "peer_group", "region", "country"])
st.plotly_chart(px.box(d, x=group, y="ratio_pct", points="outliers", hover_name="entity_name",
                       category_orders={"size_class": lib.SIZE_ORDER}, labels={"ratio_pct": "Encumbered assets (% of total)"}),
                width="stretch")
d["assets_bn"] = d["assets"] / 1e9
st.plotly_chart(px.scatter(d, x="assets_bn", y="ratio_pct", color="peer_group", hover_name="entity_name", log_x=True,
                           labels={"assets_bn": "Total assets (EUR bn, log scale)", "ratio_pct": "Encumbered assets (% of total)"}),
                width="stretch")

st.subheader("One bank: assets by type")
names = sorted(d["entity_name"].unique())
bank = st.selectbox("Bank", names, index=names.index("National Bank of Greece, S.A.") if "National Bank of Greece, S.A." in names else 0)
key = d.loc[d["entity_name"] == bank, "entity_key"].iloc[0]
parts = f[(f["entity_key"] == key) & (f["row_code"].isin(["0030", "0040", "0120"]))].copy()
parts["asset type"] = parts["row_label"].str.strip()
parts["kind"] = parts["column_code"].map({"0010": "Encumbered", "0060": "Unencumbered"})
parts["EUR bn"] = parts["value"] / 1e9
st.plotly_chart(px.bar(parts, x="asset type", y="EUR bn", color="kind", barmode="stack"), width="stretch")
st.dataframe(d[["entity_name", "country", "size_class", "assets_bn", "ratio_pct"]].sort_values("ratio_pct", ascending=False),
             hide_index=True, width="stretch")
