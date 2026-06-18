"""Verdict engine tests."""

from src.contracts import (
    BRONZE,
    CheckResult,
    FAIL,
    GOLD,
    IMPACTED,
    NOT_TRUSTED,
    PASS,
    SILVER,
    TRUSTED,
    WARN,
    WARNING,
)
from src.verdict_engine import compute_final_verdict, compute_layer_status


def _check(status: str) -> CheckResult:
    return CheckResult("T1", "test", BRONZE, status, observed=None,
                       expected=None, detail="")


def test_layer_status_fail_dominates():
    results = [_check(PASS), _check(WARN), _check(FAIL), _check(IMPACTED)]
    assert compute_layer_status(results) == FAIL


def test_layer_status_impacted_over_warn():
    results = [_check(PASS), _check(WARN), _check(IMPACTED)]
    assert compute_layer_status(results) == IMPACTED


def test_layer_status_all_pass():
    assert compute_layer_status([_check(PASS), _check(PASS)]) == PASS


def test_verdict_all_pass_trusted():
    status = {"bronze": PASS, "silver": PASS, "gold": PASS}
    assert compute_final_verdict(status)["final_verdict"] == TRUSTED


def test_verdict_any_fail_not_trusted():
    status = {"bronze": PASS, "silver": FAIL, "gold": PASS}
    assert compute_final_verdict(status)["final_verdict"] == NOT_TRUSTED


def test_verdict_warn_only_is_warning():
    status = {"bronze": WARN, "silver": PASS, "gold": PASS}
    assert compute_final_verdict(status)["final_verdict"] == WARNING


def test_verdict_impacted_only_is_warning():
    status = {"bronze": PASS, "silver": PASS, "gold": IMPACTED}
    assert compute_final_verdict(status)["final_verdict"] == WARNING


def test_verdict_silver_fail_gold_impacted_not_trusted():
    status = {"bronze": PASS, "silver": FAIL, "gold": IMPACTED}
    out = compute_final_verdict(status)
    assert out["final_verdict"] == NOT_TRUSTED
    assert out["severity"] == "HIGH"
