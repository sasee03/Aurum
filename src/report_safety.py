"""Defensive validation for stored Aurum report payloads.

The validation engine owns the full 17-key report contract. This module only
protects API read paths from corrupt or wrong-shaped persisted data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


class ReportLoadError(Exception):
    """Raised when a stored report exists but cannot be trusted."""

    def __init__(self, source: str, reason: str) -> None:
        super().__init__(reason)
        self.source = source
        self.reason = reason


_DICT_FIELDS = ("layer_status", "root_cause", "business_impact", "coverage", "checks")
_CHECK_LAYERS = ("bronze", "silver", "gold", "cross_layer")


def validate_report_shape(payload: Any, *, source: str = "report") -> dict:
    """Return a report dict or raise an honest load error for invalid shape."""
    if not isinstance(payload, dict):
        raise ReportLoadError(source, "expected a JSON object")

    for field in _DICT_FIELDS:
        if field in payload and not isinstance(payload[field], dict):
            raise ReportLoadError(source, f"field '{field}' must be an object")

    checks = payload.get("checks")
    if isinstance(checks, dict):
        for layer in _CHECK_LAYERS:
            if layer in checks and not isinstance(checks[layer], list):
                raise ReportLoadError(
                    source,
                    f"checks.{layer} must be a list",
                )

    detection_layers = payload.get("detection_layers")
    if detection_layers is not None and not isinstance(detection_layers, dict):
        raise ReportLoadError(source, "field 'detection_layers' must be an object")
    if isinstance(detection_layers, dict):
        for layer, checks_for_layer in detection_layers.items():
            if not isinstance(checks_for_layer, list):
                raise ReportLoadError(
                    source,
                    f"detection_layers.{layer} must be a list",
                )

    return payload


def load_report_text(raw: Optional[str], *, source: str = "report") -> Optional[dict]:
    """Parse a stored report JSON blob, returning None only when absent."""
    if raw is None or raw == "":
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ReportLoadError(source, "invalid JSON syntax") from exc
    return validate_report_shape(parsed, source=source)


def load_report_file(path: Path, *, source: str = "report file") -> Optional[dict]:
    """Load and validate a report file, returning None only when missing."""
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReportLoadError(source, "could not read report file") from exc
    return load_report_text(raw, source=source)
