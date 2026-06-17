"""Frozen Aurum report contract helpers."""

from __future__ import annotations

RUN_ID = "today"


def empty_report() -> dict:
    return {
        "run_id": RUN_ID,
        "profile": {},
        "baseline": {},
        "anomaly": {},
        "root_cause": {},
        "impact": {},
        "evidence": [],
        "verdict": {},
    }
