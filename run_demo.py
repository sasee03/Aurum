"""Run the Aurum MVP end to end and print the contract JSON."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from anomaly import detect_anomaly
from baseline import compute_baseline
from contract import RUN_ID
from data_loader import DataLoader
from evidence import build_evidence
from generate_data import generate
from impact import calculate_impact_from_loader
from profiler import build_profile
from root_cause import find_root_cause
from verdict_engine import decide_verdict


REPORT_PATH = Path("reports/legacy_report.json")


def build_report() -> dict:
    if not Path("data/bronze_orders.csv").exists():
        generate()

    loader = DataLoader()
    profile = build_profile(loader)
    historical = loader.query("SELECT * FROM historical_runs ORDER BY run_id;")
    baseline = compute_baseline(historical)
    anomaly = detect_anomaly(profile, baseline)
    root_cause = find_root_cause(loader)
    impact = calculate_impact_from_loader(loader)
    evidence = build_evidence(loader, impact)
    verdict = decide_verdict(profile, baseline, anomaly, root_cause, impact)

    return {
        "run_id": RUN_ID,
        "profile": profile,
        "baseline": baseline,
        "anomaly": anomaly,
        "root_cause": root_cause,
        "impact": impact,
        "evidence": evidence,
        "verdict": verdict,
    }


def main() -> None:
    report = build_report()
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nSaved {REPORT_PATH}")


if __name__ == "__main__":
    main()
