"""Shared revenue rounding tolerance for Silver-vs-Gold reconciliation.

Counts and key-set reconciliation use exact integer equality. Revenue uses
SUM(quantity * unit_price) in floating-point arithmetic; tiny summation drift
across many rows is normal. We reconcile within a named, documented tolerance
(currency units) and surface it in check output — never claim exact revenue match.
"""

# Fixed tolerance in currency units (e.g. INR/Rs). Chosen to absorb float drift on
# large aggregates while remaining strict enough to catch real mismatches.
REVENUE_ROUNDING_TOLERANCE = 1.0


def revenue_tolerance_detail(tolerance: float = REVENUE_ROUNDING_TOLERANCE) -> str:
    return (
        f"reconciles within rounding tolerance of {tolerance} currency unit(s) "
        "(float SUM drift; counts remain exact)"
    )
