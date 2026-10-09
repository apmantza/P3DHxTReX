import plotly.express as px
import streamlit as st

import lib

st.set_page_config(page_title="Entity browser", layout="wide")
st.title("Entity browser")

cls, km = lib.classes(), lib.km1_wide()
cls = cls.assign(label=cls["entity_name"] + " (" + cls["country"].fillna("?") + ")").sort_values("label")
labels = cls["label"].tolist()
default = labels.index("National Bank of Greece, S.A. (Greece)") if "National Bank of Greece, S.A. (Greece)" in labels else 0
row = cls.iloc[labels.index(st.selectbox("Bank", labels, index=default))]
key = row["entity_key"]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Country", row["country"])
c2.metric("Region / peer group", f"{row['region']} / {row['peer_group']}")
c3.metric("Size class", str(row["size_class"]))
ta = row["size_basis_eur"]
c4.metric(f"Size ({row['size_basis'] or 'none'}, as of {row['assets_as_of']})", f"EUR {ta / 1e9:,.1f}bn" if ta == ta and ta else "n/a")
st.caption(f"LEI key: {key}. Euro area: {'yes' if row['euro_area'] else 'no'}. Size method: {row['assets_method']}.")

d = km[km["entity_key"] == key].sort_values("period_end")
if d.empty:
    st.warning("No clean KM1 values for this bank.")
else:
    ratios = [m for m in lib.RATIO_LABELS if m in d]
    pick = st.multiselect("KM1 ratios", ratios, default=["cet1_ratio", "leverage_ratio"], format_func=lib.RATIO_LABELS.get)
    long = d.melt(id_vars="period_end", value_vars=pick, var_name="metric").dropna()
    long["value"] = long["value"] * 100
    long["metric"] = long["metric"].map(lib.RATIO_LABELS)
    st.plotly_chart(px.line(long, x="period_end", y="value", color="metric", markers=True, labels={"value": "%"}), width="stretch")
    st.dataframe(d.drop(columns="entity_key"), hide_index=True, width="stretch")

hist = lib.q("SELECT period_end, total_assets_eur, leverage_exposure_eur, assets_source, assets_method FROM v_entity_assets_class "
             "WHERE entity_key = ? ORDER BY period_end", (key,))
if hist["total_assets_eur"].notna().any():
    st.subheader("Total assets")
    st.dataframe(hist, hide_index=True, width="stretch")

st.subheader("Data quality flags for this bank")
flags = lib.q("SELECT reference_date, template_code, period_offset, row_code, check_name, action, factor, detail FROM dq_flag "
              "WHERE entity_key = ? ORDER BY reference_date, template_code", (key,))
st.dataframe(flags, hide_index=True, width="stretch") if len(flags) else st.write("No cell was changed or removed.")
