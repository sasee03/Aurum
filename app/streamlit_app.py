"""Streamlit dashboard for the current cross-layer Aurum report."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st


REPORT_PATH = Path("reports/report.json")
MANDATORY_KEYS = {
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
    missing = sorted(list(MANDATORY_KEYS - set(report)))
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

# Header styling
st.markdown(
    """
    <div style="font-family: monospace; border-bottom: 2px solid #000000; padding-bottom: 12px; margin-bottom: 24px;">
      <h1 style="margin: 0; font-size: 38px; letter-spacing: 0.1em; font-weight: 900; text-transform: uppercase;">AURUM</h1>
      <p style="margin: 0; font-size: 14px; opacity: 0.7; letter-spacing: 0.05em;">CROSS-LAYER DATA QUALITY VALIDATION CONSOLE</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# Verdict Box styling
if verdict == "TRUSTED":
    verdict_html = """
    <div style="border: 2px solid #000000; padding: 20px; text-align: center; margin-bottom: 30px; border-radius: 4px;">
      <div style="font-size: 12px; letter-spacing: 0.1em; text-transform: uppercase; opacity: 0.6; font-family: monospace;">SYSTEM STATUS</div>
      <div style="font-size: 36px; font-weight: 900; letter-spacing: 0.15em; margin: 10px 0; font-family: monospace;">[ ✓ TRUSTED ]</div>
      <div style="font-size: 12px; opacity: 0.8; font-family: monospace;">ALL VALIDATION CHECKS MET. PIPELINE IS RELIABLE.</div>
    </div>
    """
elif verdict == "WARNING":
    verdict_html = """
    <div style="border: 2px dashed #000000; padding: 20px; text-align: center; margin-bottom: 30px; border-radius: 4px;">
      <div style="font-size: 12px; letter-spacing: 0.1em; text-transform: uppercase; opacity: 0.6; font-family: monospace;">SYSTEM STATUS</div>
      <div style="font-size: 36px; font-weight: 900; letter-spacing: 0.15em; margin: 10px 0; font-family: monospace;">[ ! WARNING ]</div>
      <div style="font-size: 12px; opacity: 0.8; font-family: monospace;">MINOR ISSUES OR VALUE DEVIATIONS DETECTED.</div>
    </div>
    """
else:  # NOT TRUSTED
    verdict_html = """
    <div style="background: #000000; color: #FFFFFF; padding: 20px; text-align: center; margin-bottom: 30px; border: 2px solid #000000; border-radius: 4px;">
      <div style="font-size: 12px; letter-spacing: 0.1em; text-transform: uppercase; opacity: 0.8; font-family: monospace;">SYSTEM STATUS</div>
      <div style="font-size: 36px; font-weight: 900; letter-spacing: 0.15em; margin: 10px 0; font-family: monospace;">[ 🗙 NOT TRUSTED ]</div>
      <div style="font-size: 12px; opacity: 0.9; font-family: monospace;">CRITICAL ANOMALIES DETECTED. PIPELINE GATE BLOCKED.</div>
    </div>
    """

st.markdown(verdict_html, unsafe_allow_html=True)

overview_tab, checks_tab, evidence_tab = st.tabs(["[ 1 ] OVERVIEW", "[ 2 ] CHECKS", "[ 3 ] EVIDENCE"])

with overview_tab:
    st.markdown("<h3 style='font-family: monospace; font-weight: 700; text-transform: uppercase; margin-bottom: 15px;'>Pipeline Status</h3>", unsafe_allow_html=True)
    
    # 4 columns for status cards
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(
            f"""
            <div style="border: 1px solid #000000; padding: 15px; border-radius: 4px; text-align: center;">
              <div style="font-size: 11px; text-transform: uppercase; opacity: 0.6; font-family: monospace; margin-bottom: 5px;">Bronze Layer</div>
              <div style="font-size: 24px; font-weight: 900; font-family: monospace;">{layer_status["bronze"]}</div>
            </div>
            """,
            unsafe_allow_html=True
        )
    with col2:
        st.markdown(
            f"""
            <div style="border: 1px solid #000000; padding: 15px; border-radius: 4px; text-align: center;">
              <div style="font-size: 11px; text-transform: uppercase; opacity: 0.6; font-family: monospace; margin-bottom: 5px;">Silver Layer</div>
              <div style="font-size: 24px; font-weight: 900; font-family: monospace;">{layer_status["silver"]}</div>
            </div>
            """,
            unsafe_allow_html=True
        )
    with col3:
        st.markdown(
            f"""
            <div style="border: 1px solid #000000; padding: 15px; border-radius: 4px; text-align: center;">
              <div style="font-size: 11px; text-transform: uppercase; opacity: 0.6; font-family: monospace; margin-bottom: 5px;">Gold Layer</div>
              <div style="font-size: 24px; font-weight: 900; font-family: monospace;">{layer_status["gold"]}</div>
            </div>
            """,
            unsafe_allow_html=True
        )
    with col4:
        st.markdown(
            f"""
            <div style="border: 1px solid #000000; padding: 15px; border-radius: 4px; text-align: center;">
              <div style="font-size: 11px; text-transform: uppercase; opacity: 0.6; font-family: monospace; margin-bottom: 5px;">Failed Layer</div>
              <div style="font-size: 20px; font-weight: 900; font-family: monospace;">{report["first_failed_layer"] or "NONE"}</div>
            </div>
            """,
            unsafe_allow_html=True
        )
        
    st.caption(f"Pipeline flow: {report['pipeline']}")
    
    st.markdown("<hr style='border: 0; border-top: 1px solid #000000; margin: 30px 0;'>", unsafe_allow_html=True)

    col_left, col_right = st.columns(2)
    
    with col_left:
        st.markdown("<h3 style='font-family: monospace; font-weight: 700; text-transform: uppercase;'>Diagnosis</h3>", unsafe_allow_html=True)
        st.markdown(
            f"""
            <div style="border: 1px solid #000000; padding: 20px; border-radius: 4px; min-height: 250px; font-family: monospace;">
              <div style="font-weight: 700; text-transform: uppercase; margin-bottom: 10px; font-size: 13px;">Root Cause:</div>
              <div style="font-size: 14px; line-height: 1.5; margin-bottom: 20px; opacity: 0.85;">
                {root_cause["summary"]}
              </div>
            """,
            unsafe_allow_html=True
        )
        if root_cause.get("suspected_filter"):
            st.markdown(
                f"""
                  <div style="font-weight: 700; text-transform: uppercase; margin-bottom: 6px; font-size: 12px; opacity: 0.7;">Suspected Filter:</div>
                  <div style="background: #000000; color: #FFFFFF; padding: 12px; border-radius: 3px; font-size: 13px; border: 1px solid #000000;">
                    {root_cause["suspected_filter"]}
                  </div>
                """,
                unsafe_allow_html=True
            )
        st.markdown("</div>", unsafe_allow_html=True)
        
        st.markdown("<h3 style='font-family: monospace; font-weight: 700; text-transform: uppercase; margin-top: 20px;'>Suggested Action</h3>", unsafe_allow_html=True)
        st.markdown(
            f"""
            <div style="border: 1px solid #000000; padding: 20px; border-radius: 4px; font-family: monospace; font-size: 14px; opacity: 0.85;">
              {report["suggested_action"]}
            </div>
            """,
            unsafe_allow_html=True
        )

    with col_right:
        st.markdown("<h3 style='font-family: monospace; font-weight: 700; text-transform: uppercase;'>Business Impact</h3>", unsafe_allow_html=True)
        if impact.get("status") == "NOT_AVAILABLE":
            st.markdown(
                f"""
                <div style="border: 1px solid #000000; padding: 20px; border-radius: 4px; font-family: monospace; min-height: 250px;">
                  <div style="font-weight: 700; text-transform: uppercase; margin-bottom: 10px; font-size: 13px;">Status:</div>
                  <div style="font-size: 14px; opacity: 0.85;">{impact["detail"]}</div>
                </div>
                """,
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                f"""
                <div style="font-family: monospace; border: 1px solid #000000; padding: 20px; border-radius: 4px; min-height: 250px; display: flex; flex-direction: column; justify-content: space-between;">
                  <div>
                    <div style="font-weight: 700; border-bottom: 1px solid #000000; padding-bottom: 8px; margin-bottom: 15px; text-transform: uppercase; font-size: 13px;">Financial Impact Report</div>
                    <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                      <tr>
                        <td style="padding: 8px 0; opacity: 0.7;">EXPECTED REVENUE</td>
                        <td style="padding: 8px 0; text-align: right; font-weight: 700;">{money_cr(impact["expected_revenue"])}</td>
                      </tr>
                      <tr>
                        <td style="padding: 8px 0; opacity: 0.7;">ACTUAL REVENUE</td>
                        <td style="padding: 8px 0; text-align: right; font-weight: 700;">{money_cr(impact["actual_revenue"])}</td>
                      </tr>
                    </table>
                  </div>
                  <div style="border-top: 1px dashed #000000; padding-top: 15px; margin-top: 15px;">
                    <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                      <tr>
                        <td style="font-weight: 700;">ESTIMATED LOSS</td>
                        <td style="text-align: right; font-weight: 900; font-size: 16px;">{money_cr(impact["estimated_loss"])} ({impact["loss_percent"]:.2f}%)</td>
                      </tr>
                    </table>
                  </div>
                </div>
                """,
                unsafe_allow_html=True
            )

with checks_tab:
    all_checks = flattened_checks(report)
    
    status_selection = st.multiselect(
        "SELECT STATUS",
        options=["FAIL", "IMPACTED", "WARN", "PASS"],
        default=["FAIL", "IMPACTED", "WARN", "PASS"]
    )
    
    visible_checks = all_checks[all_checks["status"].isin(status_selection)]
    
    st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
    
    for _, check_row in visible_checks.iterrows():
        check_id = check_row["check_id"]
        check_name = check_row["check_name"]
        status = check_row["status"]
        detail = check_row["detail"]
        layer = check_row["layer"]
        
        icon = "[ PASS ]" if status == "PASS" else f"[ {status} ]"
        
        if status in ["FAIL", "IMPACTED"]:
            card_style = """
            background: #000000;
            color: #FFFFFF;
            border: 1px solid #000000;
            """
            accent_opacity = "0.7"
        else:
            card_style = """
            background: #FFFFFF;
            color: #000000;
            border: 1px solid #000000;
            """
            accent_opacity = "0.5"
            
        st.markdown(
            f"""
            <div style="{card_style} padding: 15px; margin-bottom: 12px; border-radius: 4px; font-family: monospace;">
              <div style="display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 6px;">
                <span style="font-weight: 700;">{check_id} / {check_name}</span>
                <span style="font-weight: 900;">{icon}</span>
              </div>
              <div style="font-size: 13px; opacity: 0.9;">
                {detail}
              </div>
              <div style="font-size: 10px; opacity: {accent_opacity}; margin-top: 6px; text-transform: uppercase;">
                LAYER: {layer}
              </div>
            </div>
            """,
            unsafe_allow_html=True
        )

with evidence_tab:
    all_checks = flattened_checks(report)
    evidence_checks = all_checks[all_checks["evidence_query"].fillna("") != ""]
    
    st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
    
    for _, ev_row in evidence_checks.iterrows():
        check_id = ev_row["check_id"]
        check_name = ev_row["check_name"]
        status = ev_row["status"]
        query = ev_row["evidence_query"]
        detail = ev_row["detail"]
        
        st.markdown(
            f"""
            <div style="border: 1px solid #000000; padding: 15px; margin-bottom: 15px; border-radius: 4px; font-family: monospace;">
              <div style="font-size: 13px; font-weight: 700; margin-bottom: 6px;">
                {check_id} - {check_name} ({status})
              </div>
              <div style="font-size: 12px; opacity: 0.8; margin-bottom: 10px;">
                {detail}
              </div>
            </div>
            """,
            unsafe_allow_html=True
        )
        st.code(query, language="sql")
