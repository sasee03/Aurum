"""Streamlit dashboard for the current cross-layer Aurum report."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st


REPORT_PATH = Path("reports/report.json")
REQUIRED_FIELDS = {
    "project",
    "pipeline",
    "layer_status",
    "final_verdict",
    "first_failed_layer",
    "root_cause",
    "business_impact",
    "suggested_action",
    "checks",
}


def load_report(path: Path = REPORT_PATH) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Run `python src/run_demo.py` before starting Streamlit."
        )
    report = json.loads(path.read_text(encoding="utf-8"))
    missing = sorted(REQUIRED_FIELDS - set(report))
    if missing:
        raise ValueError(
            "Report does not match the current src/ contract. "
            f"Missing fields: {missing}. Run `python src/run_demo.py`."
        )
    return report


def money_cr(value) -> str:
    return f"Rs {float(value) / 10_000_000:.2f} Cr"


def flattened_checks(report: dict) -> pd.DataFrame:
    rows = []
    for section, checks in report["checks"].items():
        for check in checks:
            rows.append({"section": section, **check})
    return pd.DataFrame(rows)


st.set_page_config(page_title="Aurum Data Quality", layout="wide")

try:
    report = load_report()
except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
    st.error(str(exc))
    st.stop()

verdict = report["final_verdict"]
layer_status = report["layer_status"]
impact = report["business_impact"]
root_cause = report["root_cause"]

st.title(report["project"])
st.caption("Cross-layer data quality validation framework")

banner_color = {
    "TRUSTED": "#16794c",
    "WARNING": "#a16207",
    "NOT TRUSTED": "#b42318",
}.get(verdict, "#444444")

st.markdown(
    f"""
    <div style="background:{banner_color};color:white;padding:18px 22px;border-radius:6px;">
      <div style="font-size:13px;text-transform:uppercase;">Final verdict</div>
      <div style="font-size:30px;font-weight:700;">{verdict}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

overview_tab, checks_tab, evidence_tab = st.tabs(["Overview", "Checks", "Evidence"])

with overview_tab:
    st.subheader("Pipeline Status")
    bronze_col, silver_col, gold_col, failed_col = st.columns(4)
    bronze_col.metric("Bronze", layer_status["bronze"])
    silver_col.metric("Silver", layer_status["silver"])
    gold_col.metric("Gold", layer_status["gold"])
    failed_col.metric("First failed layer", report["first_failed_layer"] or "None")

    st.caption(report["pipeline"])

    st.subheader("Business Impact")
    if impact.get("status") == "NOT_AVAILABLE":
        st.warning(impact["detail"])
    else:
        expected_col, actual_col, loss_col, loss_pct_col = st.columns(4)
        expected_col.metric("Expected revenue", money_cr(impact["expected_revenue"]))
        actual_col.metric("Actual revenue", money_cr(impact["actual_revenue"]))
        loss_col.metric("Estimated loss", money_cr(impact["estimated_loss"]))
        loss_pct_col.metric("Loss", f"{impact['loss_percent']:.2f}%")

    st.subheader("Root Cause")
    st.write(root_cause["summary"])
    if root_cause.get("suspected_filter"):
        st.code(root_cause["suspected_filter"], language=None)

    st.subheader("Suggested Action")
    st.write(report["suggested_action"])

with checks_tab:
    checks = flattened_checks(report)
    status_filter = st.multiselect(
        "Status",
        options=["FAIL", "IMPACTED", "WARN", "PASS"],
        default=["FAIL", "IMPACTED", "WARN", "PASS"],
    )
    visible = checks[checks["status"].isin(status_filter)]
    st.dataframe(
        visible[["check_id", "check_name", "layer", "status", "detail"]],
        use_container_width=True,
        hide_index=True,
    )

with evidence_tab:
    checks = flattened_checks(report)
    evidence = checks[checks["evidence_query"].fillna("") != ""]
    st.dataframe(
        evidence[["check_id", "check_name", "status", "evidence_query", "detail"]],
        use_container_width=True,
        hide_index=True,
    )
