"""Aurum demo UI — reads engine output from reports/report.json only.

Run: streamlit run app/streamlit_app.py

This app NEVER implements detection logic. All values come from the engine's
report.json produced by src/report_builder.py.
"""

from __future__ import annotations

import json
import html
import sys
from pathlib import Path
from typing import Any, Optional

import streamlit as st
import streamlit.components.v1 as components

# ---------------------------------------------------------------------------
# Paths — engine writes here (see src/report_builder.REPORT_PATH)
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "reports" / "report.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Field mappings — edit HERE when report.json shape changes
# ---------------------------------------------------------------------------
FIELDS = {
    "verdict": "final_verdict",
    "severity": "severity",
    "pipeline": "pipeline",
    "dataset": "dataset",
    "run_id": "run_id",
    "layer_bronze": "layer_status.bronze",
    "layer_silver": "layer_status.silver",
    "layer_gold": "layer_status.gold",
    "first_failed_layer": "first_failed_layer",
    "root_cause_summary": "root_cause.summary",
    "root_cause_failed_ids": "root_cause.failed_check_ids",
    "root_cause_suspected_filter": "root_cause.suspected_filter",
    "root_cause_evidence": "root_cause.evidence",
    "impact_expected": "business_impact.expected_revenue",
    "impact_actual": "business_impact.actual_revenue",
    "impact_loss": "business_impact.estimated_loss",
    "impact_loss_pct": "business_impact.loss_percent",
    "impact_detail": "business_impact.detail",
    "suggested_action": "suggested_action",
    "checks_bronze": "checks.bronze",
    "checks_silver": "checks.silver",
    "checks_gold": "checks.gold",
    "checks_cross": "checks.cross_layer",
    "detection_l1": "detection_layers.layer_1_rules",
    "detection_l2": "detection_layers.layer_2_reconciliation",
    "detection_l3": "detection_layers.layer_3_robust_anomaly",
}

# ---------------------------------------------------------------------------
# Visual constants — edit HERE for colors / labels
# ---------------------------------------------------------------------------
COLORS = {
    "black": "#000000",
    "white": "#FFFFFF",
}

STATUS_STYLES = {
    "PASS": ("", COLORS["black"], "PASS"),
    "FAIL": ("", COLORS["black"], "FAIL"),
    "WARN": ("", COLORS["black"], "WARNING"),
    "WARNING": ("", COLORS["black"], "WARNING"),
    "IMPACTED": ("", COLORS["black"], "IMPACTED"),
}

VERDICT_STYLES = {
    "NOT TRUSTED": ("", COLORS["black"], COLORS["white"], "NOT TRUSTED"),
    "WARNING": ("", COLORS["black"], COLORS["white"], "WARNING"),
    "TRUSTED": ("", COLORS["black"], COLORS["white"], "TRUSTED"),
}

DETECTION_LAYER_LABELS = {
    "layer_1_rules": "Rule Library",
    "layer_2_reconciliation": "Reconciliation",
    "layer_3_robust_anomaly": "Robust Anomaly",
}

PIPELINE_STAGES = ["Source", "Bronze", "Silver", "Gold"]

MISSING = "—"


# ---------------------------------------------------------------------------
# Helpers — safe report access (never crash on missing fields)
# ---------------------------------------------------------------------------
def get_field(report: Optional[dict], key: str, default: Any = None) -> Any:
    """Resolve a dot-path from FIELDS against report.json."""
    if not report:
        return default
    path = FIELDS.get(key, key)
    node: Any = report
    for part in path.split("."):
        if not isinstance(node, dict):
            return default
        node = node.get(part)
        if node is None:
            return default
    return node


def money_cr(value: Any) -> str:
    try:
        return f"₹{float(value) / 10_000_000:.2f} Cr"
    except (TypeError, ValueError):
        return MISSING


def display_or_dash(value: Any) -> str:
    if value is None or value == "":
        return MISSING
    return str(value)


def safe_text(value: Any) -> str:
    return html.escape(display_or_dash(value))


def format_int(value: Any) -> str:
    try:
        return f"{int(float(value)):,}"
    except (TypeError, ValueError):
        return MISSING


def format_drop(value: Any, signed: bool = True) -> str:
    if value in (None, "", MISSING):
        return MISSING
    try:
        number = float(str(value).replace("%", "").replace("−", "-"))
    except (TypeError, ValueError):
        return display_or_dash(value)
    if abs(number) < 0.005:
        number = 0
    sign = "−" if signed and number > 0 else ""
    return f"{sign}{abs(number):.0f}%"


def get_check_by_id(report: dict, section_key: str, check_id: str) -> Optional[dict]:
    for check in get_field(report, section_key, []) or []:
        if isinstance(check, dict) and check.get("check_id") == check_id:
            return check
    return None


def get_check_observed(report: dict, section_key: str, check_id: str, default: Any = MISSING) -> Any:
    check = get_check_by_id(report, section_key, check_id)
    if not check:
        return default
    return check.get("observed", default)


def layer_metrics(report: dict, layer_name: str) -> tuple[str, str]:
    """Return display-only row count and drop text from report.json fields."""
    layer = layer_name.lower()
    if layer == "bronze":
        rows = get_check_observed(report, "checks_bronze", "B1")
        if rows == MISSING:
            rows = get_check_observed(report, "detection_l1", "L1-BRO-COMP-EMPTY")
        return format_int(rows), "baseline"

    if layer == "silver":
        rows = get_check_observed(report, "detection_l1", "L1-SIL-COMP-EMPTY")
        if rows == MISSING:
            rows = get_check_observed(report, "checks_silver", "L1-SIL-COMP-EMPTY")
        drop = get_check_observed(report, "checks_silver", "S1")
        return format_int(rows), format_drop(drop)

    rows = get_check_observed(report, "checks_gold", "G2")
    if rows == MISSING:
        rec = get_check_observed(report, "detection_l2", "L2-REC-AGG", {})
        if isinstance(rec, dict):
            rows = (rec.get("gold") or {}).get("total_orders", MISSING)
    silver_rows = get_check_observed(report, "detection_l1", "L1-SIL-COMP-EMPTY")
    try:
        gold_rows = float(rows)
        upstream_rows = float(silver_rows)
        drop = 0 if upstream_rows == 0 else (1 - gold_rows / upstream_rows) * 100
    except (TypeError, ValueError):
        return format_int(rows), MISSING
    return format_int(rows), f"{format_drop(drop)} vs Silver"


def load_report_from_disk() -> Optional[dict]:
    if not REPORT_PATH.exists():
        return None
    try:
        return json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def run_engine_validation() -> dict:
    """Trigger the Python engine; returns fresh report dict."""
    from src.data_loader import DataLoader
    from src.report_builder import build_report, write_report

    loader = DataLoader()
    report = build_report(loader)
    write_report(report, REPORT_PATH)
    return report


def inject_global_css() -> None:
    st.markdown(
        f"""
        <style>
        :root {{
            --black: {COLORS['black']};
            --white: {COLORS['white']};
            --bg: var(--white);
            --surface: var(--white);
            --surface-soft: var(--white);
            --text: var(--black);
            --text-muted: var(--black);
            --border: var(--black);
            --shadow: none;
        }}

        * {{
            border-color: var(--border);
            caret-color: var(--text);
            scrollbar-color: var(--black) var(--white);
        }}

        ::selection {{
            background: var(--black);
            color: var(--white);
        }}

        html, body, [class*="css"], .stApp {{
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text",
                "Helvetica Neue", "Segoe UI", Roboto, Arial, sans-serif;
            color: var(--text) !important;
        }}

        .stApp {{
            background: var(--bg) !important;
        }}

        [data-testid="stAppViewContainer"],
        [data-testid="stSidebar"],
        section.main {{
            background: var(--bg) !important;
        }}

        [data-testid="stHeader"],
        [data-testid="stToolbar"],
        [data-testid="stDecoration"],
        [data-testid="stStatusWidget"],
        #MainMenu,
        footer {{
            display: none;
        }}

        .stApp a,
        .stApp a:visited,
        .stApp a:hover {{
            color: var(--text) !important;
            text-decoration-color: var(--text) !important;
        }}

        .block-container {{
            padding-top: 56px;
            padding-bottom: 56px;
            max-width: 1120px;
        }}

        h1, h2, h3, h4, h5, h6, p, li, label, span {{
            color: var(--text) !important;
        }}

        h3 {{
            font-size: 1rem;
            font-weight: 650;
            letter-spacing: 0;
            margin-top: 28px;
            margin-bottom: 12px;
        }}

        [data-testid="stCaptionContainer"], .stCaption {{
            color: var(--text-muted) !important;
        }}

        .aurum-header {{
            background: var(--surface);
            color: var(--text);
            padding: 0 0 28px;
            border-radius: 16px;
            margin-bottom: 28px;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-direction: column;
            gap: 10px;
            box-shadow: none;
            border-bottom: 1px solid var(--border);
        }}
        .aurum-wordmark {{
            font-size: 1.8rem;
            font-weight: 700;
            letter-spacing: 0.22em;
            line-height: 1;
            color: var(--text);
            text-align: center;
        }}
        .aurum-subtitle {{
            font-size: 0.95rem;
            font-weight: 400;
            color: var(--text-muted);
            margin: 0;
            text-align: center;
        }}
        .aurum-step-nav {{
            display: flex;
            justify-content: center;
            gap: 10px;
            margin: 18px auto 0;
            flex-wrap: wrap;
        }}
        .aurum-step {{
            border: 1px solid var(--border);
            border-radius: 999px;
            padding: 6px 14px;
            font-size: 0.78rem;
            font-weight: 600;
            line-height: 1;
        }}
        .aurum-step-active {{
            text-decoration: underline;
            text-underline-offset: 4px;
        }}
        .aurum-card {{
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 20px;
            background: var(--surface);
            box-shadow: var(--shadow);
        }}
        .aurum-card-title {{
            font-size: 0.76rem;
            color: var(--text);
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-weight: 600;
            margin-bottom: 12px;
        }}
        .aurum-layer-card {{
            min-height: 144px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            gap: 16px;
            text-align: left;
        }}
        .aurum-layer-status {{
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 1.15rem;
            font-weight: 750;
            letter-spacing: 0;
        }}
        .aurum-status-line {{
            width: 26px;
            height: 2px;
            border-radius: 999px;
            display: inline-block;
        }}
        .aurum-layer-metrics {{
            color: var(--text);
            font-size: 0.95rem;
            font-weight: 550;
        }}
        .aurum-layer-metrics span {{
            color: var(--text);
            font-weight: 450;
        }}
        .aurum-pipeline-arrow {{
            display: none;
        }}
        .aurum-intro {{
            color: var(--text);
            font-size: 1.04rem;
            line-height: 1.55;
            margin: 0 0 24px;
            max-width: 920px;
        }}
        .aurum-pipeline-grid {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 16px;
            margin: 24px 0 32px;
        }}
        .aurum-stage-card {{
            min-height: 124px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }}
        .aurum-stage-action {{
            color: var(--text);
            font-size: 1.2rem;
            font-weight: 650;
            line-height: 1.2;
        }}
        .aurum-impact-box {{
            border: 1px solid var(--border);
            background: var(--surface);
            padding: 24px;
            border-radius: 16px;
            margin: 16px 0 24px;
            box-shadow: var(--shadow);
        }}
        .aurum-impact-grid {{
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 16px;
            margin-top: 16px;
        }}
        .aurum-impact-metric {{
            background: var(--surface-soft);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 16px;
        }}
        .aurum-impact-label {{
            color: var(--text);
            font-size: 0.74rem;
            font-weight: 600;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }}
        .aurum-impact-value {{
            color: var(--text);
            font-size: 1.28rem;
            font-weight: 720;
            margin-top: 6px;
        }}
        .aurum-root-cause {{
            color: var(--text);
            font-size: 1.05rem;
            line-height: 1.55;
            padding: 8px 0 16px;
        }}
        .aurum-status-pill {{
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 5px 10px;
            color: var(--text);
            background: var(--surface);
            border: 1px solid var(--border);
            font-size: 0.76rem;
            font-weight: 750;
            letter-spacing: 0.06em;
        }}
        .aurum-check-card {{
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 24px;
            background: var(--surface);
            box-shadow: var(--shadow);
            margin-bottom: 24px;
        }}
        .aurum-check-head {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            margin-bottom: 8px;
        }}
        .aurum-check-title {{
            color: var(--text);
            font-size: 1rem;
            font-weight: 700;
        }}
        .aurum-caught-tag {{
            display: inline-flex;
            color: var(--text);
            background: var(--surface-soft);
            border: 1px solid var(--border);
            border-radius: 999px;
            padding: 4px 10px;
            font-size: 0.78rem;
            font-weight: 600;
            margin: 8px 0 12px;
        }}
        .aurum-check-detail {{
            color: var(--text);
            line-height: 1.55;
            margin: 0 0 16px;
        }}
        .aurum-code {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            color: var(--text);
            display: block;
            font-size: 0.82rem;
            line-height: 1.5;
            max-height: 220px;
            overflow: auto;
            overflow-wrap: anywhere;
            padding: 16px;
            white-space: pre-wrap;
            word-break: break-word;
        }}
        div.stButton > button {{
            border-radius: 14px;
            font-weight: 700;
            border-color: var(--border) !important;
            background: var(--surface) !important;
            color: var(--text) !important;
        }}
        div.stButton > button p,
        div.stButton > button span {{
            color: inherit;
        }}
        div.stButton > button[kind="primary"] {{
            background: var(--surface) !important;
            border-color: var(--border) !important;
            color: var(--text) !important;
        }}
        div.stButton > button:hover,
        div.stButton > button:focus {{
            background: var(--surface) !important;
            color: var(--text) !important;
            border-color: var(--border) !important;
            outline: 2px solid var(--border);
            outline-offset: 2px;
        }}
        div.stButton > button[kind="primary"]:hover,
        div.stButton > button[kind="primary"]:focus {{
            background: var(--surface) !important;
            color: var(--text) !important;
            border-color: var(--border) !important;
            outline: 2px solid var(--border);
            outline-offset: 2px;
        }}
        .stAlert,
        div[data-testid="stAlert"] {{
            background: var(--surface);
            color: var(--text);
            border: 1px solid var(--border);
        }}
        div[data-testid="stAlert"] * {{
            color: var(--text);
        }}
        code,
        pre {{
            background: var(--surface) !important;
            color: var(--text) !important;
            border-color: var(--border) !important;
        }}
        input,
        textarea,
        select,
        [role="textbox"],
        [data-baseweb],
        [data-testid="stMarkdownContainer"],
        [data-testid="stMetric"],
        [data-testid="stNotification"] {{
            background: var(--surface) !important;
            color: var(--text) !important;
            border-color: var(--border) !important;
        }}
        svg {{
            color: var(--text) !important;
            fill: var(--text) !important;
            stroke: var(--text) !important;
        }}
        svg * {{
            fill: var(--text) !important;
            stroke: var(--text) !important;
        }}
        @media (max-width: 760px) {{
            .aurum-header {{
                align-items: center;
                gap: 8px;
            }}
            .aurum-subtitle {{
                text-align: center;
            }}
            .aurum-impact-grid {{
                grid-template-columns: 1fr;
            }}
            .aurum-pipeline-grid {{
                grid-template-columns: 1fr;
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def scroll_to_top() -> None:
    components.html(
        """
        <script>
        const root = window.parent;
        root.scrollTo(0, 0);
        root.document.querySelectorAll('section.main, [data-testid="stAppViewContainer"]').forEach((el) => {
            el.scrollTop = 0;
        });
        </script>
        """,
        height=0,
    )


def mark_screen(screen: str) -> None:
    st.session_state["screen"] = screen
    st.session_state["scroll_to_top"] = True


def render_header_bar(
    subtitle: str = "Data Quality Engine for Medallion Architecture",
    active_step: str = "Validate",
) -> None:
    steps = ["Connect", "Select", "Validate", "Report", "Remediate"]
    nav = "".join(
        f'<span class="aurum-step{" aurum-step-active" if step == active_step else ""}">'
        f'{safe_text(step)}</span>'
        for step in steps
    )
    st.markdown(
        f"""
        <div class="aurum-header">
            <div class="aurum-wordmark">AURUM</div>
            <div class="aurum-subtitle">{safe_text(subtitle)}</div>
            <div class="aurum-step-nav">{nav}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_verdict_banner(verdict: str) -> None:
    _, color, _dark_color, label = VERDICT_STYLES.get(
        verdict, ("", COLORS["black"], COLORS["white"], display_or_dash(verdict))
    )
    st.markdown(
        f"""
        <div style="background:{COLORS['white']};
             color:{COLORS['black']};padding:32px;border-radius:16px;text-align:left;margin-bottom:24px;
             border:1px solid {COLORS['black']};
             box-shadow:none;
             display:flex;align-items:flex-end;justify-content:space-between;gap:24px;">
            <div>
            <div style="font-size:0.82rem;letter-spacing:0.12em;font-weight:700;
                 text-transform:uppercase;">Trust Verdict</div>
            <div style="font-size:2.75rem;font-weight:800;margin-top:4px;line-height:1;">
                {safe_text(label)}</div>
            </div>
            <div style="width:72px;height:3px;background:{color};border-radius:999px;"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_layer_card(report: dict, layer_name: str, status: str) -> None:
    _, color, label = STATUS_STYLES.get(status, ("", COLORS["black"], MISSING))
    rows, drop = layer_metrics(report, layer_name)
    st.markdown(
        f"""
        <div class="aurum-card aurum-layer-card">
            <div>
                <div class="aurum-card-title">{safe_text(layer_name)} layer</div>
                <div class="aurum-layer-status" style="color:{color};">
                    <span class="aurum-status-line" style="background:{color};"></span>
                    <span>{safe_text(label)}</span>
                </div>
            </div>
            <div class="aurum-layer-metrics">
                {safe_text(rows)} rows <span>· {safe_text(drop)}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def collect_failed_checks(report: dict) -> list[dict]:
    """Merge failed/impacted checks from all report sections (read-only)."""
    failed = []
    for section_key in ("checks_bronze", "checks_silver", "checks_gold", "checks_cross",
                        "detection_l1", "detection_l2", "detection_l3"):
        for check in get_field(report, section_key, []) or []:
            if not isinstance(check, dict):
                continue
            if check.get("status") in ("FAIL", "WARN", "IMPACTED"):
                failed.append(check)
    # de-dupe by check_id
    seen = set()
    unique = []
    for c in failed:
        cid = c.get("check_id", id(c))
        if cid in seen:
            continue
        seen.add(cid)
        unique.append(c)
    return unique


def detection_layer_for_check(check: dict, report: Optional[dict] = None) -> str:
    layer_key = (check.get("extra") or {}).get("detection_layer", "")
    if layer_key in DETECTION_LAYER_LABELS:
        return DETECTION_LAYER_LABELS[layer_key]
    if report:
        check_id = check.get("check_id", "")
        for section_key in ("detection_l1", "detection_l2", "detection_l3"):
            matched = get_check_by_id(report, section_key, check_id)
            if not matched:
                continue
            layer_key = (matched.get("extra") or {}).get("detection_layer", "")
            if layer_key in DETECTION_LAYER_LABELS:
                return DETECTION_LAYER_LABELS[layer_key]
    cid = check.get("check_id", "")
    if cid.startswith("L1-"):
        return DETECTION_LAYER_LABELS["layer_1_rules"]
    if cid.startswith("L2-"):
        return DETECTION_LAYER_LABELS["layer_2_reconciliation"]
    if cid.startswith("L3-"):
        return DETECTION_LAYER_LABELS["layer_3_robust_anomaly"]
    if cid.startswith("X"):
        return DETECTION_LAYER_LABELS["layer_2_reconciliation"]
    if cid.startswith(("B", "S", "G")):
        return DETECTION_LAYER_LABELS["layer_1_rules"]
    return MISSING


def find_check_by_id(report: dict, check_id: str) -> Optional[dict]:
    for section_key in ("checks_bronze", "checks_silver", "checks_gold", "checks_cross",
                        "detection_l1", "detection_l2", "detection_l3"):
        for check in get_field(report, section_key, []) or []:
            if isinstance(check, dict) and check.get("check_id") == check_id:
                return check
    return None


def evidence_for_check(report: dict, check: dict) -> tuple[str, str]:
    detail = check.get("detail", MISSING)
    sql = check.get("evidence_query", "")
    if sql:
        return detail, sql
    check_id = check.get("check_id")
    for evidence in get_field(report, "root_cause_evidence", []) or []:
        if isinstance(evidence, dict) and evidence.get("check_id") == check_id:
            return evidence.get("detail", detail), evidence.get("evidence_query", "")
    return detail, sql


# ---------------------------------------------------------------------------
# SCREEN 2 — Verdict (demo hero screen)
# ---------------------------------------------------------------------------
def render_verdict(report: dict) -> None:
    dataset = get_field(report, "dataset", "Dataset")
    render_header_bar(f"{display_or_dash(dataset)} · Trust verdict", active_step="Report")
    verdict = get_field(report, "verdict", MISSING)
    render_verdict_banner(verdict if verdict != MISSING else "WARNING")

    c1, c2, c3 = st.columns(3)
    with c1:
        render_layer_card(report, "Bronze", get_field(report, "layer_bronze", MISSING))
    with c2:
        render_layer_card(report, "Silver", get_field(report, "layer_silver", MISSING))
    with c3:
        render_layer_card(report, "Gold", get_field(report, "layer_gold", MISSING))

    st.markdown("### Business impact")
    loss = get_field(report, "impact_loss")
    loss_cr = money_cr(loss) if loss is not MISSING else MISSING
    st.markdown(
        f"""
        <div class="aurum-impact-box">
            <div style="color:{COLORS['black']};font-weight:800;font-size:1.05rem;">
                Revenue impact summary
            </div>
            <div style="color:{COLORS['black']};margin-top:4px;line-height:1.5;">
                {safe_text(get_field(report, "impact_detail"))}
            </div>
            <div class="aurum-impact-grid">
                <div class="aurum-impact-metric">
                    <div class="aurum-impact-label">Expected</div>
                    <div class="aurum-impact-value">{safe_text(money_cr(get_field(report, "impact_expected")))}</div>
                </div>
                <div class="aurum-impact-metric">
                    <div class="aurum-impact-label">Actual</div>
                    <div class="aurum-impact-value">{safe_text(money_cr(get_field(report, "impact_actual")))}</div>
                </div>
                <div class="aurum-impact-metric">
                    <div class="aurum-impact-label">Under-reported</div>
                    <div class="aurum-impact-value">{safe_text(loss_cr)}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("### Root cause")
    st.markdown(
        f'<p class="aurum-root-cause">{safe_text(get_field(report, "root_cause_summary"))}</p>',
        unsafe_allow_html=True,
    )
    first_failed = get_field(report, "first_failed_layer")
    if first_failed != MISSING:
        st.caption(f"First failed layer: {first_failed}")

    st.markdown("")
    nav1, nav2, nav3 = st.columns([1, 1, 2])
    with nav1:
        if st.button("Back to Run", use_container_width=True):
            mark_screen("landing")
            st.rerun()
    with nav2:
        if st.button("View Details", type="primary", use_container_width=True):
            mark_screen("detail")
            st.rerun()


# ---------------------------------------------------------------------------
# SCREEN 3 — Detail / Why
# ---------------------------------------------------------------------------
def render_detail(report: dict) -> None:
    dataset = get_field(report, "dataset", "Dataset")
    render_header_bar(f"{display_or_dash(dataset)} · Detection evidence", active_step="Report")
    first_failed = display_or_dash(get_field(report, "first_failed_layer"))
    st.markdown(f"**First failed layer:** {first_failed}")

    failed = collect_failed_checks(report)
    st.markdown("### Failed checks")
    if not failed:
        st.info("No failed checks in report — showing suggested action if available.")
        st.write(display_or_dash(get_field(report, "suggested_action")))
    else:
        for check in failed[:12]:
            status = check.get("status", MISSING)
            _, color, label = STATUS_STYLES.get(status, ("", COLORS["black"], status))
            caught_by = detection_layer_for_check(check, report)
            detail, sql = evidence_for_check(report, check)
            sql_block = (
                f'<pre class="aurum-code"><code>{safe_text(sql)}</code></pre>'
                if sql else
                f'<div class="aurum-code">{MISSING}</div>'
            )
            st.markdown(
                f"""
                <div class="aurum-check-card">
                    <div class="aurum-check-head">
                        <div class="aurum-check-title">
                            {safe_text(check.get('check_name', check.get('check_id', MISSING)))}
                        </div>
                        <span class="aurum-status-pill">
                            {safe_text(label)}
                        </span>
                    </div>
                    <div class="aurum-caught-tag">Caught by: {safe_text(caught_by)}</div>
                    <p class="aurum-check-detail">{safe_text(detail)}</p>
                    {sql_block}
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown("### Reconciliation math")
    # Read from business_impact — engine-computed, UI displays only
    expected = money_cr(get_field(report, "impact_expected"))
    actual = money_cr(get_field(report, "impact_actual"))
    diff = money_cr(get_field(report, "impact_loss"))
    st.markdown(
        f"- **Expected revenue** (valid Bronze / Silver basis): {expected}\n"
        f"- **Actual revenue** (Gold output): {actual}\n"
        f"- **Difference:** {diff} — layers do not fully reconcile with business expectation"
    )
    rec_check = find_check_by_id(report, "L2-REC-REV")
    if rec_check:
        obs = rec_check.get("observed") or {}
        tol = obs.get("revenue_rounding_tolerance", MISSING)
        st.caption(
            f"Silver↔Gold revenue check: difference {obs.get('difference', MISSING)} "
            f"(rounding tolerance {tol} currency units)"
        )

    st.markdown("### Detection method")
    l3_sample = (get_field(report, "detection_l3") or [{}])[0]
    method = (l3_sample.get("extra") or {}).get("method", MISSING)
    if method == MISSING:
        method = "robust anomaly detection (median / IQR + MAD)"
    st.info(f"Method: {method}")

    st.markdown("### Suggested action")
    st.write(display_or_dash(get_field(report, "suggested_action")))

    st.markdown("")
    if st.button("Back to Verdict", use_container_width=False):
        mark_screen("verdict")
        st.rerun()


# ---------------------------------------------------------------------------
# SCREEN 1 — Landing / Run
# ---------------------------------------------------------------------------
def render_landing(report: Optional[dict] = None) -> None:
    dataset = get_field(report, "dataset", "Commerce dataset")
    render_header_bar(f"{display_or_dash(dataset)} · Data quality workflow", active_step="Validate")
    st.markdown(
        "<p class='aurum-intro'>"
        "Validate orders, customers, payments, delivery, and revenue quality across your medallion pipeline. "
        "The engine runs deterministic checks; this interface only displays the report."
        "</p>",
        unsafe_allow_html=True,
    )

    stage_cards = []
    for stage in PIPELINE_STAGES:
        action = "Ingest" if stage == "Source" else "Validate"
        stage_cards.append(
            f'<div class="aurum-card aurum-stage-card">'
            f'<div class="aurum-card-title">{safe_text(stage)}</div>'
            f'<div class="aurum-stage-action">{safe_text(action)}</div>'
            f'</div>'
        )
    st.markdown(
        f"<div class='aurum-pipeline-grid'>{''.join(stage_cards)}</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

    if st.button("Run Validation", type="primary", use_container_width=True):
        with st.spinner("Running Aurum validation engine…"):
            try:
                report = run_engine_validation()
                st.session_state["report"] = report
                mark_screen("verdict")
            except Exception as exc:
                st.error(f"Validation failed: {exc}")
                existing = load_report_from_disk()
                if existing:
                    st.session_state["report"] = existing
                    mark_screen("verdict")
                    st.warning("Showing last saved report.json instead.")
        st.rerun()

    if REPORT_PATH.exists():
        st.caption(f"Last report: `{REPORT_PATH}`")
        if st.button("View last report (skip re-run)", use_container_width=True):
            st.session_state["report"] = load_report_from_disk()
            mark_screen("verdict")
            st.rerun()


# ---------------------------------------------------------------------------
# App entry
# ---------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(
        page_title="Aurum · Data Quality",
        page_icon="A",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    inject_global_css()
    if st.session_state.pop("scroll_to_top", False):
        scroll_to_top()

    if "screen" not in st.session_state:
        st.session_state["screen"] = "landing"
    if "report" not in st.session_state:
        st.session_state["report"] = load_report_from_disk()

    screen = st.session_state["screen"]
    report = st.session_state.get("report")

    if screen == "landing":
        render_landing(report)
    elif screen == "verdict":
        if not report:
            st.warning("No report found. Run validation first.")
            if st.button("Go to Run screen"):
                mark_screen("landing")
                st.rerun()
        else:
            render_verdict(report)
    elif screen == "detail":
        if not report:
            st.warning("No report found.")
        else:
            render_detail(report)
    else:
        st.session_state["screen"] = "landing"
        st.rerun()


if __name__ == "__main__":
    main()
