import plotly.express as px
import streamlit as st

import lib

st.set_page_config(page_title="IRRBB", layout="wide")
st.title("Interest rate risk in the banking book (IRRBB1)")
st.caption("Change of the economic value of equity (EVE) as a share of Tier 1 capital, from the clean layer. "
           "The supervisory outlier limit is 15% of Tier 1.")

cls, km = lib.classes(), lib.km1_wide()
fact = lib.q("""SELECT entity_key, reference_date, row_code, row_label, column_code, value, quality, unit_inferred
                FROM clean_fact WHERE template_code = 'K_68.00' AND quality <> 'quarantined'""")
counts = fact.groupby("reference_date")["entity_key"].nunique()
dates = sorted(counts.index, reverse=True)
date = st.sidebar.selectbox("Reference date", dates, index=dates.index(counts.idxmax()),
                            format_func=lambda d: f"{d} ({counts[d]} banks)")
sel = lib.cohort_filters(cls, "irr")

t1 = km[["entity_key", "period_end", "t1_capital"]].rename(columns={"period_end": "reference_date"})
eve = fact[(fact["reference_date"] == date) & (fact["column_code"] == "0010")].merge(t1, on=["entity_key", "reference_date"])
eve = eve.merge(sel, on="entity_key")
eve["scenario"] = eve["row_label"].str.replace(r"^\d+\.\s*", "", regex=True)
eve = eve[eve["t1_capital"] > 0].copy()
eve["pct_t1"] = eve["value"] / eve["t1_capital"] * 100
st.write(f"**{eve['entity_key'].nunique()} banks** at {date}.")
if eve.empty:
    st.stop()

group = st.selectbox("Group by", ["size_class", "peer_group", "region", "country"])
scenario = st.selectbox("Scenario", sorted(eve["scenario"].unique()))
one = eve[eve["scenario"] == scenario]
fig = px.box(one, x=group, y="pct_t1", points="outliers", hover_name="entity_name", category_orders={"size_class": lib.SIZE_ORDER},
             labels={"pct_t1": "Change of EVE (% of Tier 1)"})
fig.add_hline(y=-15, line_dash="dash", line_color="red")
fig.add_hline(y=15, line_dash="dash", line_color="red")
st.plotly_chart(fig, width="stretch")

st.subheader("Banks above the 15% limit in any scenario")
worst = eve.loc[eve.groupby("entity_key")["pct_t1"].apply(lambda s: s.abs().idxmax())]
over = worst[worst["pct_t1"].abs() > 15][["entity_name", "country", "size_class", "scenario", "pct_t1", "unit_inferred", "quality"]]
st.dataframe(over.sort_values("pct_t1"), hide_index=True, width="stretch")

st.subheader("One bank, all scenarios")
names = sorted(eve["entity_name"].unique())
bank = st.selectbox("Bank", names, index=names.index("National Bank of Greece, S.A.") if "National Bank of Greece, S.A." in names else 0)
b = eve[eve["entity_name"] == bank]
st.plotly_chart(px.bar(b, x="scenario", y="pct_t1", labels={"pct_t1": "Change of EVE (% of Tier 1)"}), width="stretch")
