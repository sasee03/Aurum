"""Silver layer quality checks (S1-S10).

Silver is the cleaned/transformed layer and the most important one to validate:
this is where a bad transformation can silently drop valid business records.
S8-S10 are the "hero" checks that detect wrongly-removed valid records, locate
the affected segment, and infer the bad filter -- all computed from data.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from .baseline import column_stats, tolerance_band
from .contracts import CheckResult, FAIL, PASS, SILVER, WARN
from .data_loader import DataLoader

MANDATORY_NOT_NULL = [
    "invoice_no", "stock_code", "quantity", "unit_price", "invoice_date", "country",
]

# A Bronze row represents a valid business record when it has a positive quantity
# and price and identifying keys. Such rows MUST survive into Silver.
VALID_PREDICATE = (
    "quantity > 0 AND unit_price > 0 "
    "AND invoice_no IS NOT NULL AND stock_code IS NOT NULL"
)

# Fallback drop expectations when no historical baseline exists.
EXPECTED_MIN_DROP = 2.0
EXPECTED_MAX_DROP = 10.0

# A high-quantity wholesale order is still a valid order.
HIGH_QTY_THRESHOLD = 20
BUSINESS_KEY = ("invoice_no", "stock_code", "customer_id", "invoice_date")


def _business_key_match(bronze_alias: str = "b", silver_alias: str = "s") -> str:
    return " AND ".join(
        f"{silver_alias}.{column} IS NOT DISTINCT FROM {bronze_alias}.{column}"
        for column in BUSINESS_KEY
    )


def _history(loader: DataLoader) -> Optional[pd.DataFrame]:
    if loader.table_exists("historical_runs"):
        return loader.query("SELECT * FROM historical_runs")
    return None


def _drop_pct(loader: DataLoader) -> tuple[int, int, float]:
    bronze = loader.count("bronze_orders")
    silver = loader.count("silver_orders")
    drop = (1 - silver / bronze) * 100 if bronze else 0.0
    return bronze, silver, drop


def s1_drop_percentage(loader: DataLoader) -> CheckResult:
    bronze, silver, drop = _drop_pct(loader)
    stats = column_stats(_history(loader), "drop_pct")
    if stats and stats["std"] > 0:
        band = tolerance_band(stats, k=3.0)
        wide = tolerance_band(stats, k=5.0)
        if band["lower"] <= drop <= band["upper"]:
            status, detail = PASS, "Drop is within the learned normal range."
        elif wide["lower"] <= drop <= wide["upper"]:
            status, detail = WARN, "Drop is slightly outside the learned normal range."
        else:
            status, detail = FAIL, "Drop is far outside the learned normal range."
        expected = f"{band['lower']:.2f}%-{band['upper']:.2f}% (mean +/- 3 std)"
    else:
        if EXPECTED_MIN_DROP <= drop <= EXPECTED_MAX_DROP:
            status, detail = PASS, "Drop within configured tolerance."
        elif drop <= EXPECTED_MAX_DROP * 1.5:
            status, detail = WARN, "Drop slightly outside configured tolerance."
        else:
            status, detail = FAIL, "Drop far outside configured tolerance."
        expected = f"{EXPECTED_MIN_DROP:.1f}%-{EXPECTED_MAX_DROP:.1f}% (configured)"
    return CheckResult(
        "S1", "Bronze to Silver Drop Percentage", SILVER, status,
        observed=f"{drop:.2f}%", expected=expected, detail=detail,
        evidence_query=(
            "SELECT (1 - (SELECT COUNT(*) FROM silver_orders)::DOUBLE "
            "/ (SELECT COUNT(*) FROM bronze_orders)) * 100 AS drop_pct"
        ),
        extra={"bronze": bronze, "silver": silver, "drop_pct": round(drop, 2)},
    )


def s2_expected_drop(loader: DataLoader) -> CheckResult:
    _, _, drop = _drop_pct(loader)
    within = EXPECTED_MIN_DROP <= drop <= EXPECTED_MAX_DROP
    if within:
        status, detail = PASS, "Actual drop matches the expected drop window."
    elif drop <= EXPECTED_MAX_DROP * 1.5:
        status, detail = WARN, "Actual drop is slightly above the expected window."
    else:
        status = FAIL
        detail = (
            f"Actual drop {drop:.2f}% far exceeds expected "
            f"{EXPECTED_MIN_DROP:.1f}%-{EXPECTED_MAX_DROP:.1f}%."
        )
    return CheckResult(
        "S2", "Expected Drop Check", SILVER, status,
        observed=f"{drop:.2f}%",
        expected=f"{EXPECTED_MIN_DROP:.1f}%-{EXPECTED_MAX_DROP:.1f}%",
        detail=detail,
        evidence_query=(
            "SELECT (1 - (SELECT COUNT(*) FROM silver_orders)::DOUBLE "
            "/ (SELECT COUNT(*) FROM bronze_orders)) * 100 AS drop_pct"
        ),
    )


def s3_dedup_count(loader: DataLoader) -> CheckResult:
    key = "invoice_no, stock_code, customer_id, invoice_date"
    bronze_dups = int(
        loader.scalar(
            f"""
            SELECT COALESCE(SUM(cnt - 1), 0) FROM (
                SELECT COUNT(*) AS cnt FROM bronze_orders
                GROUP BY {key} HAVING COUNT(*) > 1
            )
            """
        )
    )
    silver_dups = int(
        loader.scalar(
            f"""
            SELECT COALESCE(SUM(cnt - 1), 0) FROM (
                SELECT COUNT(*) AS cnt FROM silver_orders
                GROUP BY {key} HAVING COUNT(*) > 1
            )
            """
        )
    )
    if silver_dups == 0:
        status = PASS
        detail = f"Bronze had {bronze_dups:,} duplicate keys; Silver has none."
    else:
        status = WARN
        detail = f"Silver still has {silver_dups:,} duplicate keys after dedup."
    return CheckResult(
        "S3", "Deduplication Count Check", SILVER, status,
        observed={"bronze_duplicates": bronze_dups, "silver_duplicates": silver_dups},
        expected={"silver_duplicates": 0}, detail=detail,
        evidence_query=(
            f"SELECT {key}, COUNT(*) FROM silver_orders "
            f"GROUP BY {key} HAVING COUNT(*) > 1"
        ),
    )


def s4_mandatory_nulls(loader: DataLoader) -> CheckResult:
    cols = loader.columns("silver_orders")
    null_counts = {}
    for col in MANDATORY_NOT_NULL:
        if col in cols:
            null_counts[col] = int(
                loader.scalar(f"SELECT COUNT(*) FROM silver_orders WHERE {col} IS NULL")
            )
    total = sum(null_counts.values())
    status = PASS if total == 0 else FAIL
    detail = (
        "No nulls in Silver mandatory columns."
        if total == 0
        else f"Silver mandatory columns contain nulls: {null_counts}."
    )
    return CheckResult(
        "S4", "Mandatory Columns Not Null", SILVER, status,
        observed=null_counts, expected={c: 0 for c in null_counts}, detail=detail,
        evidence_query="SELECT COUNT(*) FROM silver_orders WHERE invoice_no IS NULL",
    )


def s5_quantity_positive(loader: DataLoader) -> CheckResult:
    bad = int(loader.scalar("SELECT COUNT(*) FROM silver_orders WHERE quantity <= 0"))
    status = PASS if bad == 0 else FAIL
    detail = (
        "All Silver rows have quantity > 0."
        if bad == 0
        else f"{bad:,} Silver rows have quantity <= 0."
    )
    return CheckResult(
        "S5", "Quantity > 0", SILVER, status,
        observed=bad, expected=0, detail=detail,
        evidence_query="SELECT COUNT(*) FROM silver_orders WHERE quantity <= 0",
    )


def s6_unit_price_positive(loader: DataLoader) -> CheckResult:
    bad = int(loader.scalar("SELECT COUNT(*) FROM silver_orders WHERE unit_price <= 0"))
    status = PASS if bad == 0 else FAIL
    detail = (
        "All Silver rows have unit_price > 0."
        if bad == 0
        else f"{bad:,} Silver rows have unit_price <= 0."
    )
    return CheckResult(
        "S6", "Unit Price > 0", SILVER, status,
        observed=bad, expected=0, detail=detail,
        evidence_query="SELECT COUNT(*) FROM silver_orders WHERE unit_price <= 0",
    )


def s7_revenue_not_negative(loader: DataLoader) -> CheckResult:
    bad = int(loader.scalar("SELECT COUNT(*) FROM silver_orders WHERE net_revenue < 0"))
    status = PASS if bad == 0 else FAIL
    detail = (
        "All Silver rows have non-negative net_revenue."
        if bad == 0
        else f"{bad:,} Silver rows have negative net_revenue."
    )
    return CheckResult(
        "S7", "Revenue Not Negative", SILVER, status,
        observed=bad, expected=0, detail=detail,
        evidence_query="SELECT COUNT(*) FROM silver_orders WHERE net_revenue < 0",
    )


def s8_valid_records_removed(loader: DataLoader) -> CheckResult:
    """HERO CHECK: valid Bronze records that never made it into Silver."""
    valid_total = int(
        loader.scalar(f"SELECT COUNT(*) FROM bronze_orders WHERE {VALID_PREDICATE}")
    )
    key_match = _business_key_match()
    missing = int(
        loader.scalar(
            f"""
            SELECT COUNT(*) FROM bronze_orders b
            WHERE {VALID_PREDICATE}
              AND NOT EXISTS (
                SELECT 1 FROM silver_orders s WHERE {key_match}
              )
            """
        )
    )
    loss_pct = (missing / valid_total * 100) if valid_total else 0.0
    if missing == 0:
        status, detail = PASS, "All valid Bronze records are present in Silver."
    elif loss_pct < 1:
        status = WARN
        detail = f"{missing:,} valid records missing from Silver ({loss_pct:.2f}%)."
    else:
        status = FAIL
        detail = (
            f"{missing:,} valid business records were wrongly removed during the "
            f"Silver transformation ({loss_pct:.2f}% of valid Bronze records)."
        )
    return CheckResult(
        "S8", "Valid Record Wrongly Removed", SILVER, status,
        observed=missing, expected=0, detail=detail,
        evidence_query=(
            "SELECT COUNT(*) FROM bronze_orders b WHERE "
            f"{VALID_PREDICATE} AND NOT EXISTS "
            f"(SELECT 1 FROM silver_orders s WHERE {key_match})"
        ),
        extra={"valid_bronze": valid_total, "missing": missing,
               "loss_pct": round(loss_pct, 2)},
    )


def s9_record_loss_by_segment(loader: DataLoader) -> CheckResult:
    segment_sql = f"""
    WITH valid_bronze AS (
        SELECT * FROM bronze_orders WHERE {VALID_PREDICATE}
    ),
    seg AS (
        SELECT
            CASE WHEN quantity > {HIGH_QTY_THRESHOLD}
                 THEN 'quantity > {HIGH_QTY_THRESHOLD}'
                 ELSE 'quantity <= {HIGH_QTY_THRESHOLD}' END AS segment,
            COUNT(*) AS bronze_valid
        FROM valid_bronze GROUP BY 1
    ),
    sil AS (
        SELECT
            CASE WHEN quantity > {HIGH_QTY_THRESHOLD}
                 THEN 'quantity > {HIGH_QTY_THRESHOLD}'
                 ELSE 'quantity <= {HIGH_QTY_THRESHOLD}' END AS segment,
            COUNT(*) AS silver_count
        FROM silver_orders GROUP BY 1
    )
    SELECT seg.segment, seg.bronze_valid,
           COALESCE(sil.silver_count, 0) AS silver_count,
           ROUND((1 - COALESCE(sil.silver_count, 0)::DOUBLE / seg.bronze_valid) * 100, 2)
               AS loss_pct
    FROM seg LEFT JOIN sil ON seg.segment = sil.segment
    ORDER BY loss_pct DESC
    """
    df = loader.query(segment_sql)
    segments = df.to_dict("records")
    worst = segments[0] if segments else {"segment": "n/a", "loss_pct": 0}
    worst_loss = float(worst.get("loss_pct", 0) or 0)
    if worst_loss < 5:
        status, detail = PASS, "No segment shows significant record loss."
    elif worst_loss < 50:
        status = WARN
        detail = f"Segment '{worst['segment']}' lost {worst_loss:.2f}% of records."
    else:
        status = FAIL
        detail = (
            f"Segment '{worst['segment']}' lost {worst_loss:.2f}% of valid records "
            "-- a structural loss, not random."
        )
    return CheckResult(
        "S9", "Record-Loss by Segment", SILVER, status,
        observed=segments, expected="< 5% loss per segment", detail=detail,
        evidence_query=segment_sql.strip(),
        extra={"segments": segments},
    )


def s10_wrong_filter_detection(loader: DataLoader) -> CheckResult:
    key_match = _business_key_match()
    stats = loader.query(
        f"""
        SELECT MIN(quantity) AS min_qty, MAX(quantity) AS max_qty, COUNT(*) AS n
        FROM bronze_orders b
        WHERE {VALID_PREDICATE}
          AND NOT EXISTS (
            SELECT 1 FROM silver_orders s WHERE {key_match}
          )
        """
    ).to_dict("records")[0]
    missing_n = int(stats["n"] or 0)
    if missing_n == 0:
        return CheckResult(
            "S10", "Wrong Filter Detection", SILVER, PASS,
            observed="no missing valid records", expected="no suspect filter",
            detail="No wrongly-removed records, so no bad filter inferred.",
            evidence_query="",
        )
    min_qty = float(stats["min_qty"])
    if min_qty > HIGH_QTY_THRESHOLD:
        suspected = f"quantity > {HIGH_QTY_THRESHOLD} records are being filtered out"
        detail = (
            f"All {missing_n:,} missing valid records have quantity >= {min_qty:.0f}; "
            f"suspected bad filter: {suspected}."
        )
    else:
        suspected = "unclear filter (missing records span multiple quantity ranges)"
        detail = f"{missing_n:,} valid records missing; {suspected}."
    return CheckResult(
        "S10", "Wrong Filter Detection", SILVER, FAIL,
        observed=suspected, expected="no suspect filter", detail=detail,
        evidence_query=(
            "SELECT MIN(quantity), MAX(quantity), COUNT(*) FROM bronze_orders b WHERE "
            f"{VALID_PREDICATE} AND NOT EXISTS "
            f"(SELECT 1 FROM silver_orders s WHERE {key_match})"
        ),
        extra={"suspected_filter": suspected, "missing": missing_n},
    )


def validate_silver(loader: DataLoader) -> list[CheckResult]:
    return [
        s1_drop_percentage(loader),
        s2_expected_drop(loader),
        s3_dedup_count(loader),
        s4_mandatory_nulls(loader),
        s5_quantity_positive(loader),
        s6_unit_price_positive(loader),
        s7_revenue_not_negative(loader),
        s8_valid_records_removed(loader),
        s9_record_loss_by_segment(loader),
        s10_wrong_filter_detection(loader),
    ]


if __name__ == "__main__":
    for result in validate_silver(DataLoader()):
        print(result.status, result.check_id, result.detail)
