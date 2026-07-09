"""Run the full Aurum cross-layer validation and print a clean summary.

    python src/run_demo.py

Loads (or generates) the Olist Brazilian e-commerce dataset, runs Bronze/Silver/Gold/cross-layer
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
    from src.report_builder import attach_trust_narrative, build_report, write_report
else:
    from .data_loader import DataLoader, RAW_CSV
    from .generate_data import generate
    from .report_builder import attach_trust_narrative, build_report, write_report


def _money(value) -> str:
    try:
        return f"BRL {float(value) / 1_000_000:.2f} M"
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
    
    if "trust_score" in report:
        _print(f"Trust Score:   {report['trust_score']}/100")
        _print()
        _print("Trust Narrative (Ollama LLaMA3):")
        _print(f"  {report.get('trust_narrative', 'N/A')}")

    _print()
    _print("Suggested Action:")
    _print(f"  {report['suggested_action']}")
    _print()


def run_validation(run_id: str = "demo_run_001") -> dict:
    """Run the full pipeline against Postgres and return the report dict.

    Side-effect-free core shared by the demo script and the API layer: it
    generates data if missing, runs the engine, and returns the in-memory
    report. It does NOT write a file or print a summary. The session schema is
    closed on exit so repeated API calls do not leak Postgres schemas.
    """
    if not RAW_CSV.exists():
        generate()
    loader = DataLoader()
    try:
        return build_report(loader, run_id=run_id)
    finally:
        loader.close()


def main() -> dict:
    report = attach_trust_narrative(run_validation())
    path = write_report(report)
    print_summary(report)
    print(f"Report written to {path}")
    
    _print("\n--------------------------------------------------")
    _print("HYBRID METADATA DISCOVERY (silver_orders)")
    _print("--------------------------------------------------")
    try:
        if __package__ in (None, ""):
            from src.metadata_discovery import discover_demo_session_metadata
            from src.engines.metadata_engine import UniversalMetadataEngine
        else:
            from .metadata_discovery import discover_demo_session_metadata
            from .engines.metadata_engine import UniversalMetadataEngine
            
        _print("1. Running Deterministic Profiling (Postgres)...")
        session_meta = discover_demo_session_metadata(sample_limit=3)
        silver_table = next((t for t in session_meta["tables"] if t["table"] == "silver_orders"), None)
        
        if silver_table:
            _print("2. Generating Semantic Explanation via LLM (Ollama)...")
            metadata_engine = UniversalMetadataEngine()
            explanation = metadata_engine.explain_metadata_profile(silver_table)
            
            _print("\nDeterministic Profile Summary (silver_orders):")
            _print(f"  Rows: {silver_table['row_count']}, Columns: {silver_table['column_count']}")
            _print(f"  Candidate Keys: {silver_table['candidate_keys']}")
            _print("\nSemantic Explanation (Ollama LLaMA3):")
            _print(f"  {explanation}")
    except Exception as e:
        _print(f"Metadata discovery failed: {e}")
        
    return report


if __name__ == "__main__":
    main()
