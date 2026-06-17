"""One-command demo correctness checks for Aurum."""

from __future__ import annotations

import math
import json
from pathlib import Path

from baseline import compute_baseline
from data_loader import DataLoader
from generate_data import generate
from root_cause import find_root_cause
from run_demo import REPORT_PATH, build_report
from verdict_engine import decide_verdict


def check(name: str, condition: bool, detail: str = "") -> None:
    if not condition:
        message = f"FAIL: {name}"
        if detail:
            message = f"{message} -- {detail}"
        raise AssertionError(message)
    print(f"PASS: {name}")


def assert_close(name: str, actual: float, expected: float, tolerance: float = 0.001) -> None:
    check(
        name,
        math.isclose(actual, expected, abs_tol=tolerance),
        f"expected {expected}, got {actual}",
    )


def verify_report_numbers(report: dict) -> None:
    profile = report["profile"]
    baseline = report["baseline"]
    anomaly = report["anomaly"]
    root_cause = report["root_cause"]
    impact = report["impact"]
    verdict = report["verdict"]

    check("Bronze count is 100,000", profile["bronze_count"] == 100_000)
    check("Buggy Silver count is 72,000", profile["silver_count"] == 72_000)
    assert_close("Bronze to Silver drop is 28%", profile["drop_pct"], 28.0)
    assert_close("Learned normal drop is 3.81%", baseline["normal_drop_pct"], 3.81)
    assert_close("Learned std dev is 0.032", baseline["std_dev"], 0.032)
    assert_close("Learned lower bound is 3.71%", baseline["lower_bound"], 3.71)
    assert_close("Learned upper bound is 3.91%", baseline["upper_bound"], 3.91)
    check("Anomaly is detected", anomaly["is_anomaly"] is True)
    assert_close("Sigma is computed from values", anomaly["deviation_sigma"], 755.9, 0.1)
    check("Severity is CRITICAL", anomaly["severity"] == "CRITICAL")
    check("Root cause dropped rows are 24,000", root_cause["dropped_rows"] == 24_000)
    assert_close("Expected revenue is Rs 10.18 Cr", impact["expected_revenue_cr"], 10.18)
    assert_close("Actual revenue is Rs 9.70 Cr", impact["actual_revenue_cr"], 9.70)
    assert_close("Revenue impact is Rs 0.48 Cr", impact["impact_cr"], 0.48)
    check("Risk level is HIGH", impact["risk_level"] == "HIGH")
    check("Verdict blocks publish", verdict["decision"] == "BLOCK PUBLISH")


def verify_contract_schema(report: dict) -> None:
    required = {
        "run_id": str,
        "profile": dict,
        "baseline": dict,
        "anomaly": dict,
        "root_cause": dict,
        "impact": dict,
        "evidence": list,
        "verdict": dict,
    }
    for key, expected_type in required.items():
        check(f"Contract has top-level field {key}", key in report)
        check(f"Contract field {key} has expected type", isinstance(report[key], expected_type))

    expected_keys = {
        "profile": {"bronze_count", "silver_count", "drop_pct"},
        "baseline": {"normal_drop_pct", "std_dev", "lower_bound", "upper_bound", "method"},
        "anomaly": {"is_anomaly", "drop_today", "deviation_sigma", "severity"},
        "root_cause": {"cause", "dropped_rows", "evidence_ref"},
        "impact": {"expected_revenue_cr", "actual_revenue_cr", "impact_cr", "risk_level"},
        "verdict": {"decision", "reasons", "suggested_action"},
    }
    for block, keys in expected_keys.items():
        check(f"{block} matches frozen contract keys", set(report[block].keys()) == keys)


def verify_source_tables(loader: DataLoader) -> None:
    bronze = int(loader.scalar("SELECT COUNT(*) FROM bronze_orders;"))
    correct_silver = int(loader.scalar("SELECT COUNT(*) FROM silver_orders_correct;"))
    buggy_silver = int(loader.scalar("SELECT COUNT(*) FROM silver_orders_buggy;"))
    history = int(loader.scalar("SELECT COUNT(*) FROM historical_runs;"))

    check("Source Bronze table has 100,000 rows", bronze == 100_000)
    check("Source correct Silver table has 96,000 rows", correct_silver == 96_000)
    check("Source buggy Silver table has 72,000 rows", buggy_silver == 72_000)
    check("Historical baseline has 15 runs", history == 15)


def verify_learned_tolerance() -> None:
    low_history = [{"drop_pct": 1.0}, {"drop_pct": 2.0}, {"drop_pct": 3.0}]
    high_history = [{"drop_pct": 10.0}, {"drop_pct": 11.0}, {"drop_pct": 12.0}]
    low = compute_baseline(low_history)
    high = compute_baseline(high_history)

    check("Baseline changes when history changes", low["normal_drop_pct"] != high["normal_drop_pct"])
    assert_close("Baseline computes low-history mean", low["normal_drop_pct"], 2.0)
    assert_close("Baseline computes high-history mean", high["normal_drop_pct"], 11.0)

    source = Path("baseline.py").read_text(encoding="utf-8")
    check("Baseline source uses numpy mean", "np.mean" in source)
    check("Baseline source uses numpy std", "np.std" in source)
    check("Baseline does not assign normal_drop_pct to 3.81", "normal_drop_pct = 3.81" not in source)


def verify_verdict_rules() -> None:
    baseline = {
        "normal_drop_pct": 3.81,
        "std_dev": 0.032,
        "lower_bound": 3.71,
        "upper_bound": 3.91,
    }

    allow = decide_verdict(
        {"drop_pct": 3.81},
        baseline,
        {"is_anomaly": False, "severity": "LOW"},
        {"dropped_rows": 0},
        {"impact_cr": 0.0, "risk_level": "LOW"},
    )
    warn = decide_verdict(
        {"drop_pct": 4.5},
        baseline,
        {"is_anomaly": True, "severity": "HIGH"},
        {"dropped_rows": 0},
        {"impact_cr": 0.02, "risk_level": "LOW"},
    )
    block = decide_verdict(
        {"drop_pct": 28.0},
        baseline,
        {"is_anomaly": True, "severity": "CRITICAL"},
        {"dropped_rows": 24_000},
        {"impact_cr": 0.48, "risk_level": "HIGH"},
    )

    check("Verdict allows clean run", allow["decision"] == "ALLOW PUBLISH")
    check("Verdict warns on non-critical anomaly", warn["decision"] == "WARN")
    check("Verdict blocks critical/high-risk run", block["decision"] == "BLOCK PUBLISH")
    check("Verdict explains block with reasons", len(block["reasons"]) == 3)


def verify_root_cause_trace(loader: DataLoader, report: dict) -> None:
    independent_count = int(
        loader.scalar(
            """
            SELECT COUNT(*)
            FROM silver_orders_correct correct
            WHERE correct.has_discount = TRUE
              AND NOT EXISTS (
                  SELECT 1
                  FROM silver_orders_buggy buggy
                  WHERE buggy.order_id = correct.order_id
              );
            """
        )
    )
    root_cause = find_root_cause(loader)

    check("Root cause derives missing discounted orders", independent_count == 24_000)
    check("Root cause module matches independent diff", root_cause["dropped_rows"] == independent_count)
    check("Report root cause matches traced diff", report["root_cause"]["dropped_rows"] == independent_count)

    source = Path("root_cause.py").read_text(encoding="utf-8")
    check("Root cause source compares correct and buggy Silver", "silver_orders_correct" in source and "silver_orders_buggy" in source)
    check("Root cause source filters discounted rows", "has_discount" in source)


def verify_evidence_queries(loader: DataLoader, report: dict) -> None:
    check("Evidence has exactly three rows", len(report["evidence"]) == 3)
    for index, row in enumerate(report["evidence"], start=1):
        check(f"Evidence row {index} has frozen keys", set(row.keys()) == {"name", "sql", "result", "meaning"})
        for key in ["name", "sql", "result", "meaning"]:
            check(f"Evidence row {index} has non-empty {key}", bool(row[key]))

    evidence_by_name = {row["name"]: row for row in report["evidence"]}

    bronze = int(loader.scalar(evidence_by_name["Bronze order count"]["sql"]))
    silver = int(loader.scalar(evidence_by_name["Silver valid count (today)"]["sql"]))
    revenue = float(loader.scalar(evidence_by_name["Gold revenue delta"]["sql"]))

    check("Evidence SQL returns 100,000 Bronze rows", bronze == 100_000)
    check("Evidence SQL returns 72,000 Silver rows", silver == 72_000)
    assert_close("Evidence SQL returns Rs 9.70 Cr revenue", revenue / 10_000_000, 9.70)
    check("Evidence result text matches Bronze SQL", evidence_by_name["Bronze order count"]["result"] == "100,000 rows")
    check("Evidence result text matches Silver SQL", evidence_by_name["Silver valid count (today)"]["result"] == "72,000 rows")
    check("Evidence result text matches revenue SQL", evidence_by_name["Gold revenue delta"]["result"] == "Rs 9.70 Cr")


def verify_dashboard_reads_contract() -> None:
    source = Path("streamlit_app.py").read_text(encoding="utf-8")
    check("Dashboard imports shared report path", "REPORT_PATH" in source)
    check("Dashboard can build the shared report", "build_report" in source)
    check("Dashboard reads report JSON", "json.loads" in source)
    for forbidden_literal in ["100000", "96000", "72000", "28.00", "10.18", "9.70", "0.48"]:
        check(
            f"Dashboard does not hardcode {forbidden_literal}",
            forbidden_literal not in source,
        )


def main() -> None:
    if not Path("data/bronze_orders.csv").exists():
        generate()

    report = build_report()
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    loader = DataLoader()

    print("\nAurum demo verification\n")
    verify_contract_schema(report)
    verify_source_tables(loader)
    verify_report_numbers(report)
    verify_learned_tolerance()
    verify_verdict_rules()
    verify_root_cause_trace(loader, report)
    verify_evidence_queries(loader, report)
    verify_dashboard_reads_contract()

    print(f"\nAll checks passed. Report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
