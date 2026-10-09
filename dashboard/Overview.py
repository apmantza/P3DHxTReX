"""P3DH dashboard: home page. Run: dashboard/.venv/Scripts/streamlit run dashboard/app.py"""

import plotly.express as px
import streamlit as st

import lib

st.set_page_config(page_title="P3DH dashboard", layout="wide")
st.title("EBA Pillar 3 Data Hub")
st.caption("Source: P3DH (EBA EDAP). All figures come from the clean layer unless a page says otherwise. "
           "Amounts are in EUR. Non-euro banks are converted at the ECB rate of the filing date.")

filings = lib.q("SELECT reference_date, COUNT(*) AS templates, SUM(n_facts) AS facts, MAX(n_entities) AS max_entities "
                "FROM filing WHERE sha256 IS NOT NULL GROUP BY reference_date ORDER BY reference_date")
cls = lib.classes()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Reference dates", len(filings))
c2.metric("Facts", f"{int(filings['facts'].sum()):,}")
c3.metric("Entities", f"{len(cls):,}")
c4.metric("Entities with a size class", f"{int((cls['size_class'].astype(str) != 'Unclassified').sum()):,}")

left, right = st.columns(2)
with left:
    st.subheader("Filings loaded")
    st.dataframe(filings, hide_index=True, use_container_width=True)
with right:
    st.subheader("Entities by size and peer group")
    cross = cls.groupby(["size_class", "peer_group"], observed=True).size().reset_index(name="entities")
    fig = px.bar(cross, x="size_class", y="entities", color="peer_group", category_orders={"size_class": lib.SIZE_ORDER},
                 labels={"size_class": "Size class (total assets)", "peer_group": "Peer group"})
    st.plotly_chart(fig, use_container_width=True)

st.subheader("Entities by region and country")
geo = cls.groupby(["region", "country"], observed=True).size().reset_index(name="entities")
st.plotly_chart(px.treemap(geo, path=["region", "country"], values="entities"), use_container_width=True)

st.info("Pages: Peer explorer, Greek banks, IRRBB, Encumbrance, Entity browser, Data quality. "
        "The template status note shows which templates have a clean layer.")
