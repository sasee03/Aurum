"""Deterministic verdict engine.

Rolls per-check statuses into per-layer statuses, then into a final
TRUSTED / WARNING / NOT TRUSTED verdict. No LLM, no randomness, no hardcoded
outcome -- the verdict is a pure function of the check results.
"""

from __future__ import annotations

from typing import Iterable

from .contracts import (
    CheckResult,
    FAIL,
    IMPACTED,
    NOT_TRUSTED,
    PASS,
    SKIPPED,
    TRUSTED,
    WARN,
    WARNING,
)

# Precedence: a single FAIL dominates, then IMPACTED, then WARN, else PASS.
_LAYER_PRECEDENCE = [FAIL, IMPACTED, WARN, PASS]


def _statuses(check_results: Iterable) -> list[str]:
    out = []
    for r in check_results:
        out.append(r.status if isinstance(r, CheckResult) else r["status"])
    return out


def compute_layer_status(check_results: Iterable) -> str:
    # SKIPPED is neither pass nor fail: exclude it from the dominant-status
    # rollup. Honest coverage (whether checks were skipped) is surfaced
    # separately in the report's `coverage` block, not by masking it as PASS.
    statuses = [s for s in _statuses(check_results) if s != SKIPPED]
    if not statuses:
        return PASS
    for status in _LAYER_PRECEDENCE:
        if status in statuses:
            return status
    return PASS


def compute_final_verdict(layer_status: dict) -> dict:
    values = list(layer_status.values())
    if FAIL in values:
        verdict, severity = NOT_TRUSTED, "HIGH"
    elif IMPACTED in values or WARN in values:
        verdict, severity = WARNING, "MEDIUM"
    else:
        verdict, severity = TRUSTED, "LOW"
    return {"final_verdict": verdict, "severity": severity}


if __name__ == "__main__":
    demo = {"bronze": PASS, "silver": FAIL, "gold": IMPACTED}
    print(demo, "->", compute_final_verdict(demo))
