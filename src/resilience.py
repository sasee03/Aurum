"""Resilience layer: three-outcome (PASS / FAIL / SKIPPED) check execution.

This is the single seam that makes the engine never crash and never lie about
coverage. Every check runs through :func:`run_checks`, which converts any
unexpected exception in one check into a first-class ``SKIPPED`` result (with a
sanitized reason) and continues to the next check. One bad check can never abort
the run or prevent other checks from running.

The generic wrapper is the safety net. Predictable edge cases (empty tables,
missing baselines, degenerate statistics, zero denominators) are handled
*deliberately* at their check sites with correct math and precise reasons; this
wrapper only catches the unexpected.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Union

from .contracts import (
    CheckResult,
    FAIL,
    IMPACTED,
    PASS,
    SKIPPED,
    WARN,
)

logger = logging.getLogger("aurum.resilience")
# Library-style logging: emit records but stay silent unless the host app
# configures a handler. Keeps the demo/CLI output identical while the skip
# reasons remain available to anyone who attaches a handler.
logger.addHandler(logging.NullHandler())

# Quartiles (Q1/Q3) need at least four points to be meaningful; below this the
# IQR/MAD anomaly math degenerates (IQR/MAD collapse toward zero and every point
# looks like an outlier), so anomaly checks SKIP instead of fabricating a signal.
MIN_HISTORY_FOR_ANOMALY = 4

# Scrub anything that looks like a credential/DSN out of a reason string so
# connection strings and passwords never leak into the report.
_SECRET_RE = re.compile(r"(password|pwd|secret|token|key)\s*=\s*[^\s]+", re.IGNORECASE)
_URI_RE = re.compile(r"\b[a-z]+://[^\s]+", re.IGNORECASE)

CheckOutput = Union[CheckResult, List[CheckResult], None]


def sanitize_reason(exc: BaseException) -> str:
    """Return a useful, secret-free reason string for a failed check."""
    text = f"{type(exc).__name__}: {exc}"
    text = _SECRET_RE.sub(r"\1=***", text)
    text = _URI_RE.sub("***", text)
    return " ".join(text.split()).strip()


def skipped_result(
    check_id: str,
    check_name: str,
    layer: str,
    reason: str,
    evidence_query: str = "",
) -> CheckResult:
    """Build a first-class SKIPPED CheckResult carrying a specific reason."""
    return CheckResult(
        check_id=check_id,
        check_name=check_name,
        layer=layer,
        status=SKIPPED,
        observed=None,
        expected="check could not be evaluated",
        detail=reason,
        evidence_query=evidence_query,
    )


@dataclass
class Check:
    """A single unit of work for the resilience runner.

    ``fn`` is a zero-argument thunk (usually a lambda closing over the loader)
    returning a ``CheckResult``, a list of them, or ``None``. The id/name/layer
    are only used to build the SKIPPED fallback if ``fn`` raises.
    """

    fn: Callable[[], CheckOutput]
    check_id: str
    check_name: str
    layer: str


def _normalize(output: CheckOutput) -> List[CheckResult]:
    if output is None:
        return []
    if isinstance(output, CheckResult):
        return [output]
    return [r for r in output if isinstance(r, CheckResult)]


def run_checks(checks: Iterable[Check]) -> List[CheckResult]:
    """Run each check in isolation; convert exceptions into SKIPPED results.

    Never catches KeyboardInterrupt/SystemExit. Every check produces output (a
    real result, or SKIPPED with a reason) and execution always continues.
    """
    results: List[CheckResult] = []
    for check in checks:
        try:
            output = check.fn()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:  # noqa: BLE001 - this IS the resilience boundary
            reason = sanitize_reason(exc)
            logger.warning("Check %s SKIPPED: %s", check.check_id, reason)
            results.append(
                skipped_result(check.check_id, check.check_name, check.layer, reason)
            )
            continue
        results.extend(_normalize(output))
    return results


def build_coverage(results: Iterable[CheckResult]) -> dict:
    """Summarize honest coverage over the full set of check results.

    ``failed`` / ``warned`` / ``impacted`` are broken out (rather than lumped)
    so a downstream reader can distinguish an established failure from a caveat.
    ``full_coverage`` is False whenever anything was skipped.
    """
    results = list(results)
    counts = Counter(r.status for r in results)
    skipped_details = [
        {"check_id": r.check_id, "reason": r.detail}
        for r in results
        if r.status == SKIPPED
    ]
    skipped = counts.get(SKIPPED, 0)
    return {
        "total_checks": len(results),
        "passed": counts.get(PASS, 0),
        "warned": counts.get(WARN, 0),
        "failed": counts.get(FAIL, 0),
        "impacted": counts.get(IMPACTED, 0),
        "skipped": skipped,
        "skipped_details": skipped_details,
        "full_coverage": skipped == 0,
    }
