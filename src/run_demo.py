"""Run the full Aurum cross-layer validation and print a clean summary.

    python src/run_demo.py

Loads (or generates) the retail dataset, runs Bronze/Silver/Gold/cross-layer
checks, computes the deterministic verdict, writes reports/report.json, and
prints a business-readable summary.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Windows consoles default to cp1252 and choke on the pipeline arrows; force UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _print(text: str = "") -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.replace("\u2192", "->"))


# Allow running as `python src/run_demo.py` (script) or `python -m src.run_demo`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from src.data_loader import DataLoader, RAW_CSV
    from src.generate_data import generate
    from src.report_builder import build_report, write_report
else:
    from .data_loader import DataLoader, RAW_CSV
    from .generate_data import generate
    from .report_builder import build_report, write_report


def _money(value) -> str:
    try:
        return f"Rs {float(value) / 10_000_000:.2f} Cr"
    except (TypeError, ValueError):
        return str(value)


def _failed_checks(report: dict) -> list[dict]:
    failed = []
    for section in report["checks"].values():
        for check in section:
            if check["status"] in ("FAIL", "IMPACTED"):
                failed.append(check)
    return failed


def print_summary(report: dict) -> None:
    ls = report["layer_status"]
    _print()
    _print("AURUM DATA QUALITY REPORT")
    _print()
    _print(f"Pipeline: {report['pipeline']}")
    _print()
    _print(f"Bronze Quality: {ls['bronze']}")
    _print(f"Silver Quality: {ls['silver']}")
    _print(f"Gold Quality:   {ls['gold']}")
    _print()
    _print(f"First Failed Layer: {report['first_failed_layer'] or 'None'}")
    _print()
    _print("Root Cause:")
    _print(f"  {report['root_cause']['summary']}")
    if report["root_cause"].get("failed_check_ids"):
        _print(f"  Failed checks: {report['root_cause']['failed_check_ids']}")
    _print()

    impact = report["business_impact"]
    _print("Business Impact:")
    if impact.get("status") == "NOT_AVAILABLE":
        _print(f"  {impact['detail']}")
    else:
        _print(f"  Expected Revenue: {_money(impact['expected_revenue'])}")
        _print(f"  Actual Revenue:   {_money(impact['actual_revenue'])}")
        _print(f"  Estimated Loss:   {_money(impact['estimated_loss'])} "
               f"({impact['loss_percent']}%)")
    _print()

    failed = _failed_checks(report)
    if failed:
        _print("Failed / Impacted Checks:")
        for check in failed:
            _print(f"  [{check['status']}] {check['check_id']} {check['check_name']}: "
                   f"{check['detail']}")
        _print()

    _print(f"Final Verdict: {report['final_verdict']} (severity: {report['severity']})")
    _print()
    _print("Suggested Action:")
    _print(f"  {report['suggested_action']}")
    _print()


def main() -> dict:
    if not RAW_CSV.exists():
        generate()
    loader = DataLoader()
    report = build_report(loader)
    path = write_report(report)
    print_summary(report)
    print(f"Report written to {path}")
    return report


if __name__ == "__main__":
    main()
