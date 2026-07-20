"""Real execution for user-defined custom checks (non-SQL types only).

Custom checks are additive findings. They must never modify trust_score,
final_verdict, or layer_status from the deterministic engine.

Execution modes:
  - Demo session (default): loads the Olist demo data via a short-lived DataLoader.
  - Upload run (run_id supplied, mode="upload"): caller must provide a re-uploaded
    CSV frame; this module evaluates on that frame and labels the data source clearly.
  - Connector run (run_id supplied, mode="connector"): requires a live session_connection
    (password held in the existing short-TTL in-memory session store). If the session has
    expired or no connection_id is available, returns honest SKIPPED — never falls back to
    demo silently.

No user SQL is executed in any path.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from src.app_state.store import get_data_connection
from src.data_loader import DataLoader

from src.config_loader import AurumDatasetConfig, load_dataset_config

DEMO_DATA_SOURCE = "Olist demo validation session"
DEMO_SCOPE_NOTE = (
    "Test Check currently runs against the Olist demo validation session, "
    "not an uploaded or connector run."
)

SUPPORTED_RULE_TYPES = frozenset(
    {
        "not_null",
        "unique",
        "accepted_values",
        "numeric_range",
        "row_count_condition",
    }
)

SQL_RULE_TYPES = frozenset({"custom_sql_demo"})


def _result(
    check_id: str,
    status: str,
    message: str,
    observed_value: Any,
    expected_condition: str,
    *,
    data_source: str | None = DEMO_DATA_SOURCE,
    scope_note: str | None = DEMO_SCOPE_NOTE,
) -> dict[str, Any]:
    result = {
        "check_id": check_id,
        "status": status,
        "message": message,
        "observed_value": observed_value,
        "expected_condition": expected_condition,
    }
    if data_source is not None:
        result["data_source"] = data_source
    if scope_note is not None:
        result["scope_note"] = scope_note
    return result


def _is_blank(series: pd.Series) -> pd.Series:
    """True for nulls and blank/whitespace-only strings."""
    as_str = series.astype("string")
    return series.isna() | as_str.str.strip().eq("") | as_str.isna()


def _parse_number(raw: Any) -> Optional[float]:
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _parse_accepted_values(raw: Any) -> list[str]:
    text = str(raw).strip()
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def _compare(left: float, operator: str, right: float) -> bool:
    ops = {
        ">": left > right,
        ">=": left >= right,
        "<": left < right,
        "<=": left <= right,
        "==": left == right,
        "=": left == right,
        "!=": left != right,
    }
    if operator not in ops:
        raise ValueError(f"unsupported operator '{operator}'")
    return ops[operator]


def resolve_layer_table(layer: str, cfg: Optional[AurumDatasetConfig] = None) -> Optional[str]:
    cfg = cfg or load_dataset_config()
    layer = str(layer).strip().lower()
    if layer == "bronze":
        return cfg.tables.bronze
    if layer == "silver":
        return cfg.tables.silver
    if layer == "gold":
        return cfg.tables.gold.metrics
    return None


def load_layer_dataframe(layer: str, cfg: Optional[AurumDatasetConfig] = None) -> pd.DataFrame:
    """Build a short-lived demo validation session and return the layer table.

    Closes the DataLoader before returning so session schemas do not leak.
    """
    table = resolve_layer_table(layer, cfg)
    if table is None:
        raise ValueError(f"unknown layer '{layer}'")

    loader = DataLoader()
    try:
        if not loader.table_exists(table):
            raise ValueError(f"table '{table}' not found in validation session")
        return loader.query(f"SELECT * FROM {table}")
    finally:
        loader.close()


def evaluate_check_on_frame(check: dict, df: pd.DataFrame) -> dict[str, Any]:
    """Evaluate a saved check definition against an in-memory DataFrame."""
    check_id = str(check.get("check_id", ""))
    rule_type = str(check.get("rule_type", "")).strip()
    column = str(check.get("column", "")).strip()
    operator = str(check.get("operator", "")).strip()
    value = check.get("value", "")

    if rule_type in SQL_RULE_TYPES:
        return _result(
            check_id,
            "SKIPPED",
            "SQL-based custom checks are not yet supported (no arbitrary SQL execution).",
            None,
            f"{rule_type} (not yet supported)",
            scope_note=(
                "SQL checks are deferred for safety; no arbitrary SQL is executed "
                "and this result is still demo-session scoped."
            ),
        )

    if rule_type not in SUPPORTED_RULE_TYPES:
        return _result(
            check_id,
            "SKIPPED",
            f"Unsupported rule type '{rule_type}'.",
            None,
            rule_type or "",
        )

    if rule_type == "row_count_condition":
        threshold = _parse_number(value)
        if threshold is None:
            return _result(
                check_id,
                "SKIPPED",
                f"row_count_condition value '{value}' is not numeric.",
                None,
                f"row count {operator} {value}",
            )
        observed = int(len(df))
        try:
            passed = _compare(float(observed), operator, threshold)
        except ValueError as exc:
            return _result(
                check_id,
                "SKIPPED",
                str(exc),
                observed,
                f"row count {operator} {value}",
            )
        return _result(
            check_id,
            "PASS" if passed else "FAIL",
            (
                f"Row count is {observed}, which {'meets' if passed else 'does not meet'} "
                f"{operator} {threshold:g}."
            ),
            observed,
            f"row count {operator} {value}",
        )

    if not column:
        return _result(
            check_id,
            "SKIPPED",
            "No target column configured for this check.",
            None,
            f"{rule_type}",
        )

    if column not in df.columns:
        return _result(
            check_id,
            "SKIPPED",
            f"Target column '{column}' not found in loaded data "
            f"(available: {', '.join(map(str, df.columns))}).",
            None,
            f"{rule_type} on {column}",
        )

    series = df[column]
    n_rows = int(len(df))

    if rule_type == "not_null":
        null_mask = _is_blank(series)
        null_count = int(null_mask.sum())
        passed = null_count == 0
        return _result(
            check_id,
            "PASS" if passed else "FAIL",
            (
                f"No null/blank values in {column}."
                if passed
                else f"{null_count} of {n_rows} rows have null/blank {column}."
            ),
            null_count,
            f"{column} is not null",
        )

    if rule_type == "unique":
        non_null = series[~_is_blank(series)]
        dup_count = int(non_null.duplicated().sum())
        passed = dup_count == 0
        return _result(
            check_id,
            "PASS" if passed else "FAIL",
            (
                f"All non-null values in {column} are unique."
                if passed
                else f"{dup_count} duplicate value(s) found in {column}."
            ),
            dup_count,
            f"{column} is unique",
        )

    if rule_type == "accepted_values":
        allowed = _parse_accepted_values(value)
        if not allowed:
            return _result(
                check_id,
                "SKIPPED",
                "accepted_values requires a non-empty comma-separated allow-list in value.",
                None,
                f"{column} in []",
            )
        allowed_set = {a.lower() for a in allowed}
        non_null = series[~_is_blank(series)].astype(str).str.strip()
        bad_mask = ~non_null.str.lower().isin(allowed_set)
        bad_count = int(bad_mask.sum())
        passed = bad_count == 0
        return _result(
            check_id,
            "PASS" if passed else "FAIL",
            (
                f"All values in {column} are within the allow-list."
                if passed
                else f"{bad_count} of {len(non_null)} non-null values in {column} "
                f"are outside the allow-list."
            ),
            bad_count,
            f"{column} in [{', '.join(allowed)}]",
        )

    if rule_type == "numeric_range":
        # Support either a single threshold (operator + value) or "min,max" in value.
        value_text = str(value).strip()
        numeric = pd.to_numeric(series, errors="coerce")
        non_null_mask = ~_is_blank(series)
        invalid_numeric = int((non_null_mask & numeric.isna()).sum())
        comparable = numeric[non_null_mask & numeric.notna()]

        if "," in value_text and operator in ("", "between", "in_range", "range"):
            parts = [p.strip() for p in value_text.split(",", 1)]
            lo = _parse_number(parts[0]) if parts else None
            hi = _parse_number(parts[1]) if len(parts) > 1 else None
            if lo is None or hi is None:
                return _result(
                    check_id,
                    "SKIPPED",
                    f"numeric_range value '{value}' must be 'min,max' or a single number.",
                    None,
                    f"{column} between {value}",
                )
            out_of_range = int(((comparable < lo) | (comparable > hi)).sum())
            observed = out_of_range + invalid_numeric
            passed = observed == 0
            return _result(
                check_id,
                "PASS" if passed else "FAIL",
                (
                    f"All numeric values in {column} are within [{lo:g}, {hi:g}]."
                    if passed
                    else f"{observed} of {n_rows} rows have {column} outside "
                    f"[{lo:g}, {hi:g}] (or non-numeric)."
                ),
                observed,
                f"{column} between {lo:g} and {hi:g}",
            )

        threshold = _parse_number(value)
        if threshold is None:
            return _result(
                check_id,
                "SKIPPED",
                f"numeric_range value '{value}' is not numeric.",
                None,
                f"{column} {operator} {value}",
            )
        try:
            fail_mask = ~comparable.map(lambda x: _compare(float(x), operator, threshold))
        except ValueError as exc:
            return _result(
                check_id,
                "SKIPPED",
                str(exc),
                None,
                f"{column} {operator} {value}",
            )
        out_of_range = int(fail_mask.sum())
        observed = out_of_range + invalid_numeric
        passed = observed == 0
        return _result(
            check_id,
            "PASS" if passed else "FAIL",
            (
                f"All numeric values in {column} satisfy {operator} {threshold:g}."
                if passed
                else f"{observed} of {n_rows} rows have {column} failing "
                f"{operator} {threshold:g} (or non-numeric)."
            ),
            observed,
            f"{column} {operator} {value}",
        )

    return _result(
        check_id,
        "SKIPPED",
        f"Unsupported rule type '{rule_type}'.",
        None,
        rule_type,
    )


def execute_custom_check(check: dict) -> dict[str, Any]:
    """Execute against the Olist demo session (fallback / explicit demo path).

    Results are additive only — never modifies trust_score, final_verdict, or
    layer_status. Caller should prefer execute_custom_check_against_frame() when
    a specific run's data is available.
    """
    check_id = str(check.get("check_id", ""))
    rule_type = str(check.get("rule_type", "")).strip()

    if rule_type in SQL_RULE_TYPES:
        return evaluate_check_on_frame(check, pd.DataFrame())

    layer = str(check.get("layer", "")).strip().lower()
    if resolve_layer_table(layer) is None:
        return _result(
            check_id,
            "SKIPPED",
            f"Unknown layer '{layer}'. Expected bronze, silver, or gold.",
            None,
            rule_type,
        )

    try:
        df = load_layer_dataframe(layer)
    except Exception as exc:  # noqa: BLE001 — surface honest skip, never crash API
        return _result(
            check_id,
            "SKIPPED",
            f"Could not load validation data for layer '{layer}': {exc}",
            None,
            f"{rule_type} on {check.get('column', '')}",
        )

    return evaluate_check_on_frame(check, df)


def execute_custom_check_against_frame(
    check: dict,
    df: pd.DataFrame,
    data_source: str,
) -> dict[str, Any]:
    """Evaluate a check against a caller-supplied frame with an explicit data_source label.

    Used for upload-scoped and connector-scoped runs. The caller is responsible
    for loading the correct layer frame from the run's data. data_source must
    unambiguously describe where the data came from (e.g. run_id + mode).
    """
    check_id = str(check.get("check_id", ""))
    rule_type = str(check.get("rule_type", "")).strip()

    if rule_type in SQL_RULE_TYPES:
        return _result(
            check_id,
            "SKIPPED",
            "SQL-based custom checks are not yet supported (no arbitrary SQL execution).",
            None,
            f"{rule_type} (not yet supported)",
            data_source=data_source,
            scope_note="SQL checks are deferred for safety; no arbitrary SQL is executed.",
        )

    if not df.empty and len(df.columns) > 0:
        pass  # frame is usable as-is

    result = evaluate_check_on_frame(check, df)
    result["data_source"] = data_source
    result["scope_note"] = (
        f"Check ran against the actual data for this run ({data_source})."
    )
    return result


def run_info_for_check(run_id: str) -> Optional[dict[str, Any]]:
    """Return mode + connection_id (+ source coords) for a stored run, or None."""
    from src.app_state.store import get_validation_run

    return get_validation_run(run_id)


def build_layer_frame_from_raw(raw_frame, layer: str, cfg: Optional[AurumDatasetConfig] = None):
    """Build bronze/silver/gold from a raw_orders frame for check execution.

    Uses DataLoader.from_frames() so the pipeline runs in-memory without touching
    the app DB search path. Always closes the loader before returning.
    """
    from src.csv_ingest import materialize_upload_pipeline

    cfg = cfg or load_dataset_config()
    table_name = resolve_layer_table(layer, cfg) or cfg.tables.silver
    loader = DataLoader.from_frames({cfg.tables.raw: raw_frame})
    try:
        materialize_upload_pipeline(loader, cfg)
        return loader.query(f"SELECT * FROM {table_name}")
    finally:
        loader.close()


def build_run_scoped_data_source(run: dict[str, Any]) -> str:
    """Human-readable label describing what data source a run used."""
    mode = run.get("mode", "unknown")
    run_id = run.get("run_id", "")
    if mode == "upload":
        return f"Uploaded file (run {run_id})"
    if mode == "connector":
        conn_id = run.get("connection_id") or ""
        if conn_id:
            conn_meta = get_data_connection(conn_id)
            if conn_meta:
                host = conn_meta.get("host", "")
                db = conn_meta.get("database_name", "")
                user = conn_meta.get("username", "")
                return f"Connector: {user}@{host}/{db} (run {run_id})"
        return f"Connector run {run_id}"
    if mode == "demo":
        return DEMO_DATA_SOURCE
    return f"Run {run_id} (mode: {mode})"
