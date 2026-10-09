import plotly.express as px
import streamlit as st

import lib

st.set_page_config(page_title="Data quality", layout="wide")
st.title("Data quality")
st.caption("What the clean layer changed or removed, and which templates are clean.")

flags = lib.q("SELECT template_code, check_name, action, COUNT(*) AS n, COUNT(DISTINCT entity_key) AS banks FROM dq_flag "
              "GROUP BY template_code, check_name, action ORDER BY n DESC")
st.subheader("Tests that fired")
flags["test"] = flags["template_code"] + "  " + flags["check_name"]
st.plotly_chart(px.bar(flags.sort_values("n"), x="n", y="test", color="action", orientation="h", height=max(400, 22 * len(flags)),
                       labels={"n": "cells or filings", "test": ""}), width="stretch")
st.dataframe(flags, hide_index=True, width="stretch")

st.subheader("Removed values by template")
if lib.table_exists("clean_fact"):
    qual = lib.q("SELECT template_code, quality, COUNT(*) AS n FROM clean_fact GROUP BY template_code, quality")
    st.plotly_chart(px.bar(qual, x="template_code", y="n", color="quality", barmode="stack"), width="stretch")

st.subheader("Coverage by reference date")
cov = lib.q("SELECT reference_date, status, COUNT(*) AS templates FROM v_coverage GROUP BY reference_date, status")
st.plotly_chart(px.bar(cov, x="reference_date", y="templates", color="status", barmode="stack"), width="stretch")

st.subheader("Template status note")
if lib.STATUS_DOC.exists():
    st.markdown(lib.STATUS_DOC.read_text(encoding="utf-8"))
