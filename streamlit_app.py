"""Aurum Streamlit dashboard."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from run_demo import REPORT_PATH, build_report


def load_report() -> dict:
    if REPORT_PATH.exists():
        return json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    report = build_report()
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


report = load_report()
decision = report["verdict"]["decision"]

st.set_page_config(page_title="Aurum Release Control", layout="wide")
st.title("Aurum")
st.caption("Business Release Control for Gold Outputs")

banner_color = {
    "ALLOW PUBLISH": "#16794c",
    "WARN": "#a16207",
    "BLOCK PUBLISH": "#b42318",
}.get(decision, "#444444")

st.markdown(
    f"""
    <div style="background:{banner_color};color:white;padding:22px 26px;border-radius:8px;">
      <div style="font-size:14px;text-transform:uppercase;letter-spacing:0.08em;">Verdict</div>
      <div style="font-size:34px;font-weight:700;">{decision}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

profile = report["profile"]
impact = report["impact"]
baseline = report["baseline"]
anomaly = report["anomaly"]
root_cause = report["root_cause"]

st.subheader("Pipeline Health")
col1, col2, col3, col4 = st.columns(4)
col1.metric("Bronze", f"{profile['bronze_count']:,}")
col2.metric("Silver", f"{profile['silver_count']:,}")
col3.metric("Gold revenue", f"Rs {impact['actual_revenue_cr']:.2f} Cr")
col4.metric("Drop", f"{profile['drop_pct']:.2f}%")

st.subheader("Normal vs Today")
col1, col2, col3, col4 = st.columns(4)
col1.metric("Normal drop", f"{baseline['normal_drop_pct']:.2f}%")
col2.metric("Tolerance", f"{baseline['lower_bound']:.2f}% - {baseline['upper_bound']:.2f}%")
col3.metric("Today", f"{anomaly['drop_today']:.2f}%")
col4.metric("Severity", anomaly["severity"])

st.subheader("Root Cause")
st.write(root_cause["cause"])
st.metric("Dropped valid rows", f"{root_cause['dropped_rows']:,}")

st.subheader("Business Impact")
col1, col2, col3, col4 = st.columns(4)
col1.metric("Expected revenue", f"Rs {impact['expected_revenue_cr']:.2f} Cr")
col2.metric("Actual revenue", f"Rs {impact['actual_revenue_cr']:.2f} Cr")
col3.metric("Impact", f"Rs {impact['impact_cr']:.2f} Cr")
col4.metric("Risk", impact["risk_level"])

st.subheader("Evidence")
st.dataframe(pd.DataFrame(report["evidence"]), use_container_width=True, hide_index=True)

st.subheader("Reasons")
for reason in report["verdict"]["reasons"]:
    st.write(f"- {reason}")
