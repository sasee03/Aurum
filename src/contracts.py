"""Shared contracts for the Aurum validation framework.

Every data quality check returns a `CheckResult` with the same shape so that
layer validators, the verdict engine, and the report builder can all consume a
single structure. Nothing here is data-specific; it is the vocabulary the whole
framework speaks.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Allowed per-check statuses.
PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"
IMPACTED = "IMPACTED"

CHECK_STATUSES = (PASS, WARN, FAIL, IMPACTED)

# Layer names.
BRONZE = "Bronze"
SILVER = "Silver"
GOLD = "Gold"
CROSS_LAYER = "Cross-Layer"

# Final verdict labels (never ALLOW/BLOCK -- this framework reports trust).
TRUSTED = "TRUSTED"
WARNING = "WARNING"
NOT_TRUSTED = "NOT TRUSTED"


@dataclass
class CheckResult:
    """The single shape every quality check emits."""

    check_id: str
    check_name: str
    layer: str
    status: str
    observed: Any
    expected: Any
    detail: str
    evidence_query: str = ""
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in CHECK_STATUSES:
            raise ValueError(
                f"Invalid status {self.status!r}; must be one of {CHECK_STATUSES}."
            )

    def to_dict(self) -> dict:
        data = asdict(self)
        if not data["extra"]:
            data.pop("extra")
        return data
