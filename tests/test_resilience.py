"""Ring 4 resilience layer: three-outcome semantics and degenerate-math guards."""

import numpy as np

from builders import loader_from, make_rows, to_df, to_silver

from src.baseline import classify_robust_anomaly, modified_z_score, robust_iqr_band
from src.contracts import BRONZE, CheckResult, FAIL, PASS, SKIPPED, WARN
from src.resilience import (
    MIN_HISTORY_FOR_ANOMALY,
    Check,
    build_coverage,
    run_checks,
    sanitize_reason,
    skipped_result,
)
from src.robust_anomaly import run_robust_anomaly_layer
from src.rule_library import run_rule_library


def _boom():
    raise ValueError("bad data reached the check")


# --------------------------------------------------------------- degenerate math
def test_classify_skips_when_history_below_min():
    status, ev = classify_robust_anomaly(100.0, np.array([100.0, 100.0, 100.0]))
    assert status == SKIPPED
    assert ev["history_count"] == 3 < MIN_HISTORY_FOR_ANOMALY
    assert "no baseline yet" in ev["detail"]


def test_iqr_zero_on_constant_series():
    band = robust_iqr_band(np.array([3.0, 3.0, 3.0, 3.0]))
    assert band["iqr"] == 0


def test_classify_constant_baseline_value_matches_is_pass():
    # MAD == 0 and IQR == 0; value equals the constant -> PASS, no divide-by-zero.
    status, ev = classify_robust_anomaly(50.0, np.array([50.0, 50.0, 50.0, 50.0]))
    assert status == PASS
    assert ev["mad"] == 0 and ev["iqr"] == 0


def test_classify_constant_baseline_value_differs_is_warn_not_fail():
    status, ev = classify_robust_anomaly(999.0, np.array([50.0, 50.0, 50.0, 50.0]))
    assert status == WARN  # real change, but MAD=0 means it is not scorable
    assert status != FAIL
    assert "constant baseline" in ev["detail"]


def test_modified_z_no_inf_reaches_verdict_on_constant_series():
    hist = np.array([7.0, 7.0, 7.0, 7.0])
    assert modified_z_score(7.0, hist) == 0.0
    assert np.isinf(modified_z_score(8.0, hist))  # raw math degenerates...
    status, ev = classify_robust_anomaly(8.0, hist)  # ...but classify guards it
    assert status == WARN
    assert not any(
        isinstance(v, float) and (np.isinf(v) or np.isnan(v)) for v in ev.values()
    )


# ------------------------------------------------------------- resilience wrapper
def test_one_throwing_check_becomes_skipped_others_still_run():
    good = CheckResult("G", "good", BRONZE, PASS, observed=1, expected=1, detail="ok")
    results = run_checks(
        [
            Check(_boom, "BAD", "bad check", BRONZE),
            Check(lambda: good, "G", "good", BRONZE),
        ]
    )
    by = {r.check_id: r for r in results}
    assert by["BAD"].status == SKIPPED
    assert "bad data reached the check" in by["BAD"].detail
    assert by["G"].status == PASS  # a bad check never blocks the next one


def test_sanitize_reason_scrubs_credentials():
    msg = sanitize_reason(RuntimeError("connect failed password=supersecret dbname=x"))
    assert "supersecret" not in msg
    assert "password=***" in msg


def test_build_coverage_counts_and_full_coverage_flag():
    results = [
        CheckResult("A", "a", BRONZE, PASS, 1, 1, "ok"),
        CheckResult("B", "b", BRONZE, FAIL, 1, 0, "nope"),
        skipped_result("C", "c", BRONZE, "could not run"),
    ]
    cov = build_coverage(results)
    assert cov["total_checks"] == 3
    assert cov["passed"] == 1 and cov["failed"] == 1 and cov["skipped"] == 1
    assert cov["full_coverage"] is False
    assert cov["skipped_details"] == [{"check_id": "C", "reason": "could not run"}]
    assert (
        cov["total_checks"]
        == cov["passed"] + cov["warned"] + cov["failed"] + cov["impacted"] + cov["skipped"]
    )


def test_build_coverage_full_when_no_skips():
    cov = build_coverage([CheckResult("A", "a", BRONZE, PASS, 1, 1, "ok")])
    assert cov["full_coverage"] is True and cov["skipped"] == 0


# ------------------------------------------------------- integration edge cases
def test_no_baseline_anomaly_layer_skips_not_crashes():
    bronze = make_rows(20)
    loader = loader_from(bronze_orders=to_df(bronze), silver_orders=to_silver(bronze))
    try:
        results = run_robust_anomaly_layer(loader)
        assert results and all(r.status == SKIPPED for r in results)
        assert all("no baseline yet" in r.detail for r in results)
    finally:
        loader.close()


def test_missing_customers_table_fk_skips_with_reason():
    loader = loader_from(silver_orders=to_silver(make_rows(10)))
    try:
        fk = [r for r in run_rule_library(loader) if r.check_id == "L1-SIL-CONS-FK-CUST"]
        assert fk and fk[0].status == SKIPPED
        assert "customers" in fk[0].detail and "not applicable" in fk[0].detail
    finally:
        loader.close()


def test_empty_bronze_drop_checks_fail_not_crash():
    from src.silver_validator import s1_drop_percentage, s2_expected_drop

    loader = loader_from(bronze_orders=to_df([]), silver_orders=to_silver(make_rows(5)))
    try:
        s1 = s1_drop_percentage(loader)
        s2 = s2_expected_drop(loader)
        assert s1.status == FAIL and "empty" in s1.detail
        assert s2.status == FAIL and "empty" in s2.detail
    finally:
        loader.close()


def test_build_report_completes_when_a_check_throws(monkeypatch):
    import src.silver_validator as sv
    from src.data_loader import DataLoader
    from src.report_builder import build_report

    monkeypatch.setattr(sv, "s5_quantity_positive", lambda loader: _boom())
    loader = DataLoader()
    try:
        report = build_report(loader)
    finally:
        loader.close()

    silver = {c["check_id"]: c for c in report["checks"]["silver"]}
    assert silver["S5"]["status"] == SKIPPED
    assert "bad data reached the check" in silver["S5"]["detail"]
    assert report["final_verdict"] == "NOT TRUSTED"  # run still completed
    assert report["coverage"]["skipped"] >= 1
    assert report["coverage"]["full_coverage"] is False
