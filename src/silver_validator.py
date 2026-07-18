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

from .contracts import CheckResult, FAIL, PASS, SILVER, WARN, SKIPPED

from .data_loader import DataLoader, _quote_ident, valid_predicate

from .resilience import Check, run_checks

from .config_loader import load_dataset_config, AurumDatasetConfig







# Fallback drop expectations when no historical baseline exists.

EXPECTED_MIN_DROP = 2.0

EXPECTED_MAX_DROP = 10.0



# Olist line items use quantity=1; the planted Silver bug filters on unit_price.

def _business_key_match(

    business_key: tuple[str, ...], bronze_alias: str = "b", silver_alias: str = "s", *, native: bool = False

) -> str:

    # Intended for EXISTS/NOT EXISTS filter predicates only; do not use this

    # helper to produce a standalone boolean value.

    if native:

        return " AND ".join(

            f"{silver_alias}.{column} IS NOT DISTINCT FROM {bronze_alias}.{column}"

            for column in business_key

        )

    return " AND ".join(

        (

            f"({silver_alias}.{column} = {bronze_alias}.{column} "

            f"OR ({silver_alias}.{column} IS NULL AND {bronze_alias}.{column} IS NULL))"

        )

        for column in business_key

    )





def _history(loader: DataLoader) -> Optional[pd.DataFrame]:

    if loader.table_exists("historical_runs"):

        return loader.query("SELECT * FROM historical_runs")

    return None





def _drop_pct(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> tuple[int, int, float]:

    cfg = cfg or load_dataset_config()

    raw_table = _quote_ident(cfg.tables.raw).as_string(loader._pg_conn)

    bronze_table = _quote_ident(cfg.tables.bronze).as_string(loader._pg_conn)

    silver_table = _quote_ident(cfg.tables.silver).as_string(loader._pg_conn)

    gold_metrics = _quote_ident(cfg.tables.gold.metrics).as_string(loader._pg_conn)

    gold_country = _quote_ident(cfg.tables.gold.country_revenue).as_string(loader._pg_conn)

    gold_product = _quote_ident(cfg.tables.gold.product_sales).as_string(loader._pg_conn)



    bronze = loader.count(f"{bronze_table}")

    silver = loader.count(f"{silver_table}")

    drop = (1 - silver / bronze) * 100 if bronze else 0.0

    return bronze, silver, drop





def s1_drop_percentage(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:

    cfg = cfg or load_dataset_config()

    raw_table = _quote_ident(cfg.tables.raw).as_string(loader._pg_conn)

    bronze_table = _quote_ident(cfg.tables.bronze).as_string(loader._pg_conn)

    silver_table = _quote_ident(cfg.tables.silver).as_string(loader._pg_conn)

    gold_metrics = _quote_ident(cfg.tables.gold.metrics).as_string(loader._pg_conn)

    gold_country = _quote_ident(cfg.tables.gold.country_revenue).as_string(loader._pg_conn)

    gold_product = _quote_ident(cfg.tables.gold.product_sales).as_string(loader._pg_conn)



    bronze, silver, drop = _drop_pct(loader, cfg)

    if bronze == 0:

        # bronze_orders is expected to be non-empty; an empty upstream is itself

        # the finding, not an unscorable skip. Guard the division deliberately.

        return CheckResult(

            "S1", "Bronze to Silver Drop Percentage", SILVER, FAIL,

            observed="n/a (bronze empty)", expected=f"non-empty {cfg.tables.bronze}",

            detail=f"{cfg.tables.bronze} is empty -- expected data, cannot compute drop percentage.",

            evidence_query=f"SELECT COUNT(*) FROM {cfg.tables.bronze}",

            extra={"bronze": 0, "silver": silver},

        )

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

            f"SELECT (1 - (SELECT COUNT(*) FROM {cfg.tables.silver})::DOUBLE "

            f"/ (SELECT COUNT(*) FROM {cfg.tables.bronze})) * 100 AS drop_pct"

        ),

        extra={"bronze": bronze, "silver": silver, "drop_pct": round(drop, 2)},

    )





def s2_expected_drop(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:

    cfg = cfg or load_dataset_config()

    raw_table = _quote_ident(cfg.tables.raw).as_string(loader._pg_conn)

    bronze_table = _quote_ident(cfg.tables.bronze).as_string(loader._pg_conn)

    silver_table = _quote_ident(cfg.tables.silver).as_string(loader._pg_conn)

    gold_metrics = _quote_ident(cfg.tables.gold.metrics).as_string(loader._pg_conn)

    gold_country = _quote_ident(cfg.tables.gold.country_revenue).as_string(loader._pg_conn)

    gold_product = _quote_ident(cfg.tables.gold.product_sales).as_string(loader._pg_conn)



    bronze, _, drop = _drop_pct(loader)

    if bronze == 0:

        return CheckResult(

            "S2", "Expected Drop Check", SILVER, FAIL,

            observed="n/a (bronze empty)",

            expected=f"{EXPECTED_MIN_DROP:.1f}%-{EXPECTED_MAX_DROP:.1f}%",

            detail=f"{cfg.tables.bronze} is empty -- expected data, cannot compute expected drop.",

            evidence_query=f"SELECT COUNT(*) FROM {cfg.tables.bronze}",

        )

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

            f"SELECT (1 - (SELECT COUNT(*) FROM {cfg.tables.silver})::DOUBLE "

            f"/ (SELECT COUNT(*) FROM {cfg.tables.bronze})) * 100 AS drop_pct"

        ),

    )





def s3_dedup_count(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:

    cfg = cfg or load_dataset_config()

    raw_table = _quote_ident(cfg.tables.raw).as_string(loader._pg_conn)

    bronze_table = _quote_ident(cfg.tables.bronze).as_string(loader._pg_conn)

    silver_table = _quote_ident(cfg.tables.silver).as_string(loader._pg_conn)

    gold_metrics = _quote_ident(cfg.tables.gold.metrics).as_string(loader._pg_conn)

    gold_country = _quote_ident(cfg.tables.gold.country_revenue).as_string(loader._pg_conn)

    gold_product = _quote_ident(cfg.tables.gold.product_sales).as_string(loader._pg_conn)



    business_key = (

        cfg.columns.primary_key,

        cfg.columns.product_id,

        cfg.columns.customer_id,

        cfg.columns.timestamp,

    )

    key = ", ".join(business_key)

    bronze_dups = int(

        loader.scalar(

            f"""
            SELECT COALESCE(SUM(cnt - 1), 0) FROM (
                SELECT COUNT(*) AS cnt FROM {bronze_table}
                GROUP BY {key} HAVING COUNT(*) > 1
            )
            """

        )

    )

    silver_dups = int(

        loader.scalar(

            f"""
            SELECT COALESCE(SUM(cnt - 1), 0) FROM (
                SELECT COUNT(*) AS cnt FROM {silver_table}
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

            f"SELECT {key}, COUNT(*) FROM {cfg.tables.silver} "

            f"GROUP BY {key} HAVING COUNT(*) > 1"

        ),

    )





def s4_mandatory_nulls(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:

    cfg = cfg or load_dataset_config()

    raw_table = _quote_ident(cfg.tables.raw).as_string(loader._pg_conn)

    bronze_table = _quote_ident(cfg.tables.bronze).as_string(loader._pg_conn)

    silver_table = _quote_ident(cfg.tables.silver).as_string(loader._pg_conn)

    gold_metrics = _quote_ident(cfg.tables.gold.metrics).as_string(loader._pg_conn)

    gold_country = _quote_ident(cfg.tables.gold.country_revenue).as_string(loader._pg_conn)

    gold_product = _quote_ident(cfg.tables.gold.product_sales).as_string(loader._pg_conn)



    cols = loader.columns(f"{silver_table}")

    mandatory_not_null = [

        cfg.columns.primary_key,

        cfg.columns.product_id,

        cfg.columns.quantity,

        cfg.columns.unit_price,

        cfg.columns.timestamp,

        cfg.columns.geography,

    ]

    null_counts = {}

    for col in mandatory_not_null:

        if col in cols:

            null_counts[col] = int(

                loader.scalar(f"SELECT COUNT(*) FROM {silver_table} WHERE {col} IS NULL")

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

        evidence_query=f"SELECT COUNT(*) FROM {cfg.tables.silver} WHERE {cfg.columns.primary_key} IS NULL",

    )





def s5_quantity_positive(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:

    cfg = cfg or load_dataset_config()

    raw_table = _quote_ident(cfg.tables.raw).as_string(loader._pg_conn)

    bronze_table = _quote_ident(cfg.tables.bronze).as_string(loader._pg_conn)

    silver_table = _quote_ident(cfg.tables.silver).as_string(loader._pg_conn)

    gold_metrics = _quote_ident(cfg.tables.gold.metrics).as_string(loader._pg_conn)

    gold_country = _quote_ident(cfg.tables.gold.country_revenue).as_string(loader._pg_conn)

    gold_product = _quote_ident(cfg.tables.gold.product_sales).as_string(loader._pg_conn)



    qty_col = cfg.columns.quantity

    bad = int(loader.scalar(f"SELECT COUNT(*) FROM {silver_table} WHERE {qty_col} <= 0"))

    status = PASS if bad == 0 else FAIL

    detail = (

        f"All Silver rows have {qty_col} > 0."

        if bad == 0

        else f"{bad:,} Silver rows have {qty_col} <= 0."

    )

    return CheckResult(

        "S5", "Quantity > 0", SILVER, status,

        observed=bad, expected=0, detail=detail,

        evidence_query=f"SELECT COUNT(*) FROM {cfg.tables.silver} WHERE {qty_col} <= 0",

    )





def s6_unit_price_positive(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:

    cfg = cfg or load_dataset_config()

    raw_table = _quote_ident(cfg.tables.raw).as_string(loader._pg_conn)

    bronze_table = _quote_ident(cfg.tables.bronze).as_string(loader._pg_conn)

    silver_table = _quote_ident(cfg.tables.silver).as_string(loader._pg_conn)

    gold_metrics = _quote_ident(cfg.tables.gold.metrics).as_string(loader._pg_conn)

    gold_country = _quote_ident(cfg.tables.gold.country_revenue).as_string(loader._pg_conn)

    gold_product = _quote_ident(cfg.tables.gold.product_sales).as_string(loader._pg_conn)



    price_col = cfg.columns.unit_price

    bad = int(loader.scalar(f"SELECT COUNT(*) FROM {silver_table} WHERE {price_col} <= 0"))

    status = PASS if bad == 0 else FAIL

    detail = (

        f"All Silver rows have {price_col} > 0."

        if bad == 0

        else f"{bad:,} Silver rows have {price_col} <= 0."

    )

    return CheckResult(

        "S6", "Unit Price > 0", SILVER, status,

        observed=bad, expected=0, detail=detail,

        evidence_query=f"SELECT COUNT(*) FROM {cfg.tables.silver} WHERE {price_col} <= 0",

    )





def s7_revenue_not_negative(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:

    cfg = cfg or load_dataset_config()

    raw_table = _quote_ident(cfg.tables.raw).as_string(loader._pg_conn)

    bronze_table = _quote_ident(cfg.tables.bronze).as_string(loader._pg_conn)

    silver_table = _quote_ident(cfg.tables.silver).as_string(loader._pg_conn)

    gold_metrics = _quote_ident(cfg.tables.gold.metrics).as_string(loader._pg_conn)

    gold_country = _quote_ident(cfg.tables.gold.country_revenue).as_string(loader._pg_conn)

    gold_product = _quote_ident(cfg.tables.gold.product_sales).as_string(loader._pg_conn)



    rev_col = cfg.columns.revenue

    bad = int(loader.scalar(f"SELECT COUNT(*) FROM {silver_table} WHERE {rev_col} < 0"))

    status = PASS if bad == 0 else FAIL

    detail = (

        f"All Silver rows have non-negative {rev_col}."

        if bad == 0

        else f"{bad:,} Silver rows have negative {rev_col}."

    )

    return CheckResult(

        "S7", "Revenue Not Negative", SILVER, status,

        observed=bad, expected=0, detail=detail,

        evidence_query=f"SELECT COUNT(*) FROM {cfg.tables.silver} WHERE {rev_col} < 0",

    )





def s8_valid_records_removed(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:

    """HERO CHECK: valid Bronze records that never made it into Silver."""

    cfg = cfg or load_dataset_config()

    raw_table = _quote_ident(cfg.tables.raw).as_string(loader._pg_conn)

    bronze_table = _quote_ident(cfg.tables.bronze).as_string(loader._pg_conn)

    silver_table = _quote_ident(cfg.tables.silver).as_string(loader._pg_conn)

    gold_metrics = _quote_ident(cfg.tables.gold.metrics).as_string(loader._pg_conn)

    gold_country = _quote_ident(cfg.tables.gold.country_revenue).as_string(loader._pg_conn)

    gold_product = _quote_ident(cfg.tables.gold.product_sales).as_string(loader._pg_conn)



    valid_predicate_str = valid_predicate(cfg)

    business_key = (

        cfg.columns.primary_key,

        cfg.columns.product_id,

        cfg.columns.customer_id,

        cfg.columns.timestamp,

    )

    valid_total = int(

        loader.scalar(f"SELECT COUNT(*) FROM {bronze_table} WHERE {valid_predicate_str}")

    )

    key_match = _business_key_match(business_key)

    evidence_key_match = _business_key_match(business_key, native=True)

    missing = int(

        loader.scalar(

            f"""
            SELECT COUNT(*) FROM {bronze_table} b
            WHERE {valid_predicate_str}
              AND NOT EXISTS (
                SELECT 1 FROM {silver_table} s WHERE {key_match}
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

            f"SELECT COUNT(*) FROM {cfg.tables.bronze} b WHERE "

            f"{valid_predicate_str} AND NOT EXISTS "

            f"(SELECT 1 FROM {cfg.tables.silver} s WHERE {evidence_key_match})"

        ),

        extra={"valid_bronze": valid_total, "missing": missing,

               "loss_pct": round(loss_pct, 2)},

    )





def s9_record_loss_by_segment(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:

    cfg = cfg or load_dataset_config()

    threshold = cfg.columns.price_ceiling
    if threshold is None:
        return CheckResult(
            "S9", "Record-Loss by Segment", SILVER, SKIPPED,
            observed="n/a", expected="No price ceiling configured",
            detail="price_ceiling not configured for this dataset.",
            evidence_query="",
        )

    raw_table = _quote_ident(cfg.tables.raw).as_string(loader._pg_conn)

    bronze_table = _quote_ident(cfg.tables.bronze).as_string(loader._pg_conn)

    silver_table = _quote_ident(cfg.tables.silver).as_string(loader._pg_conn)

    gold_metrics = _quote_ident(cfg.tables.gold.metrics).as_string(loader._pg_conn)

    gold_country = _quote_ident(cfg.tables.gold.country_revenue).as_string(loader._pg_conn)

    gold_product = _quote_ident(cfg.tables.gold.product_sales).as_string(loader._pg_conn)



    valid_predicate_str = valid_predicate(cfg)

    price_col = cfg.columns.unit_price

    segment_sql = f"""
    WITH valid_bronze AS (
        SELECT * FROM {bronze_table} WHERE {valid_predicate_str}
    ),
    seg AS (
        SELECT
            CASE WHEN {price_col} > {threshold}
                 THEN '{price_col} > {threshold}'
                 ELSE '{price_col} <= {threshold}' END AS segment,
            COUNT(*) AS bronze_valid
        FROM valid_bronze GROUP BY 1
    ),
    sil AS (
        SELECT
            CASE WHEN {price_col} > {threshold}
                 THEN '{price_col} > {threshold}'
                 ELSE '{price_col} <= {threshold}' END AS segment,
            COUNT(*) AS silver_count
        FROM {silver_table} GROUP BY 1
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

        evidence_query=segment_sql.replace(bronze_table, cfg.tables.bronze).replace(silver_table, cfg.tables.silver).strip(),

        extra={"segments": segments},

    )





def s10_wrong_filter_detection(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:

    cfg = cfg or load_dataset_config()

    threshold = cfg.columns.price_ceiling
    if threshold is None:
        return CheckResult(
            "S10", "Wrong Filter Detection", SILVER, SKIPPED,
            observed="n/a", expected="No price ceiling configured",
            detail="price_ceiling not configured for this dataset.",
            evidence_query="",
        )

    raw_table = _quote_ident(cfg.tables.raw).as_string(loader._pg_conn)

    bronze_table = _quote_ident(cfg.tables.bronze).as_string(loader._pg_conn)

    silver_table = _quote_ident(cfg.tables.silver).as_string(loader._pg_conn)

    gold_metrics = _quote_ident(cfg.tables.gold.metrics).as_string(loader._pg_conn)

    gold_country = _quote_ident(cfg.tables.gold.country_revenue).as_string(loader._pg_conn)

    gold_product = _quote_ident(cfg.tables.gold.product_sales).as_string(loader._pg_conn)



    business_key = (

        cfg.columns.primary_key,

        cfg.columns.product_id,

        cfg.columns.customer_id,

        cfg.columns.timestamp,

    )

    valid_predicate_str = valid_predicate(cfg)

    key_match = _business_key_match(business_key)

    evidence_key_match = _business_key_match(business_key, native=True)

    stats = loader.query(

        f"""
        SELECT MIN({cfg.columns.unit_price}) AS min_price, MAX({cfg.columns.unit_price}) AS max_price, COUNT(*) AS n
        FROM {bronze_table} b
        WHERE {valid_predicate_str}
          AND NOT EXISTS (
            SELECT 1 FROM {silver_table} s WHERE {key_match}
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

    min_price = float(stats["min_price"])

    if min_price > threshold:

        suspected = f"{cfg.columns.unit_price} > {threshold} records are being filtered out"

        detail = (

            f"All {missing_n:,} missing valid records have {cfg.columns.unit_price} >= {min_price:.2f}; "

            f"suspected bad filter: {suspected}."

        )

    else:

        suspected = "unclear filter (missing records span multiple price ranges)"

        detail = f"{missing_n:,} valid records missing; {suspected}."

    return CheckResult(

        "S10", "Wrong Filter Detection", SILVER, FAIL,

        observed=suspected, expected="no suspect filter", detail=detail,

        evidence_query=(

            f"SELECT MIN({cfg.columns.unit_price}), MAX({cfg.columns.unit_price}), COUNT(*) FROM {cfg.tables.bronze} b WHERE "

            f"{valid_predicate_str} AND NOT EXISTS "

            f"(SELECT 1 FROM {cfg.tables.silver} s WHERE {evidence_key_match})"

        ),

        extra={"suspected_filter": suspected, "missing": missing_n},

    )





def s11_silver_orphan_keys(loader: DataLoader, cfg: Optional[AurumDatasetConfig] = None) -> CheckResult:

    cfg = cfg or load_dataset_config()

    raw_table = _quote_ident(cfg.tables.raw).as_string(loader._pg_conn)

    bronze_table = _quote_ident(cfg.tables.bronze).as_string(loader._pg_conn)

    silver_table = _quote_ident(cfg.tables.silver).as_string(loader._pg_conn)

    gold_metrics = _quote_ident(cfg.tables.gold.metrics).as_string(loader._pg_conn)

    gold_country = _quote_ident(cfg.tables.gold.country_revenue).as_string(loader._pg_conn)

    gold_product = _quote_ident(cfg.tables.gold.product_sales).as_string(loader._pg_conn)



    primary_key = cfg.columns.primary_key

    orphan_keys = int(

        loader.scalar(

            f"""
            SELECT COUNT(*) FROM {silver_table} s
            WHERE NOT EXISTS (
                SELECT 1 FROM {bronze_table} b WHERE b.{primary_key} = s.{primary_key}
            )
            """

        )

    )

    status = PASS if orphan_keys == 0 else FAIL

    detail = (

        "Every Silver primary key exists in Bronze."

        if status == PASS

        else f"{orphan_keys:,} Silver rows have primary keys not present in Bronze."

    )

    return CheckResult(

        "S11", "Silver Orphan Primary Keys", SILVER, status,

        observed=orphan_keys, expected=0, detail=detail,

        evidence_query=(

            f"SELECT COUNT(*) FROM {cfg.tables.silver} s WHERE NOT EXISTS "

            f"(SELECT 1 FROM {cfg.tables.bronze} b WHERE b.{primary_key} = s.{primary_key})"

        ),

    )





def validate_silver(

    loader: DataLoader,

    cfg: Optional[AurumDatasetConfig] = None,

) -> list[CheckResult]:

    cfg = cfg or load_dataset_config()

    return run_checks(

        [

            Check(lambda: s1_drop_percentage(loader, cfg), "S1", "Bronze to Silver Drop Percentage", SILVER),

            Check(lambda: s2_expected_drop(loader, cfg), "S2", "Expected Drop Check", SILVER),

            Check(lambda: s3_dedup_count(loader, cfg), "S3", "Deduplication Count Check", SILVER),

            Check(lambda: s4_mandatory_nulls(loader, cfg), "S4", "Mandatory Columns Not Null", SILVER),

            Check(lambda: s5_quantity_positive(loader, cfg), "S5", "Quantity > 0", SILVER),

            Check(lambda: s6_unit_price_positive(loader, cfg), "S6", "Unit Price > 0", SILVER),

            Check(lambda: s7_revenue_not_negative(loader, cfg), "S7", "Revenue Not Negative", SILVER),

            Check(lambda: s8_valid_records_removed(loader, cfg), "S8", "Valid Record Wrongly Removed", SILVER),

            Check(lambda: s9_record_loss_by_segment(loader, cfg), "S9", "Record-Loss by Segment", SILVER),

            Check(lambda: s10_wrong_filter_detection(loader, cfg), "S10", "Wrong Filter Detection", SILVER),

            Check(lambda: s11_silver_orphan_keys(loader, cfg), "S11", "Silver Orphan Primary Keys", SILVER),

        ]

    )





if __name__ == "__main__":

    for result in validate_silver(DataLoader()):

        print(result.status, result.check_id, result.detail)

