"""Candidate Table Hygiene and Cleanup Utilities for Aurum."""

from __future__ import annotations

import datetime
import re
from typing import Dict, List, Any, Optional

import psycopg
from src.app_state.db import get_connection
from src.db_config import load_layer_schemas, postgres_promotion_conninfo, get_generated_sql_pool
from src.promotion import discard_candidate_table, PromotionError


_RUN_ID_REGEX = re.compile(r"_candidate_(run_[A-Za-z0-9_]+)$", re.IGNORECASE)


def _parse_iso_datetime(dt_str: str) -> Optional[datetime.datetime]:
    try:
        # Handle ISO strings with optional Z or fractional seconds
        clean_str = dt_str.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(clean_str)
    except Exception:
        return None


def cleanup_orphaned_candidate_tables(age_threshold_seconds: int = 3600) -> Dict[str, Any]:
    """
    Scans candidate schemas (silver_candidates, gold_candidates) for leftover tables.
    
    Categorizes tables into:
    1. removed_candidates: Tables older than age_threshold_seconds with non-promoted status in SQLite.
    2. in_flight_candidates: Tables created within age_threshold_seconds (preserved).
    3. untracked_candidates: Tables with no matching SQLite metadata record (preserved for human review).
    """
    schemas = load_layer_schemas()
    candidate_schemas = [schemas.silver_candidates, schemas.gold_candidates]
    
    # 1. Fetch metadata records from SQLite
    sqlite_records: Dict[str, dict] = {}
    with get_connection() as conn_db:
        rows = conn_db.execute(
            "SELECT run_id, table_name, created_at, status FROM generated_sql_review"
        ).fetchall()
        for row in rows:
            sqlite_records[row["run_id"]] = {
                "run_id": row["run_id"],
                "table_name": row["table_name"],
                "created_at": row["created_at"],
                "status": row["status"]
            }
            
    # 2. Fetch active candidate tables from Postgres information_schema using promotion connection
    postgres_candidates: List[dict] = []
    with psycopg.connect(postgres_promotion_conninfo()) as p_conn:
        with p_conn.cursor() as cur:
            for schema_name in candidate_schemas:
                cur.execute(
                    """
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = %s AND table_type = 'BASE TABLE'
                    """,
                    (schema_name,)
                )
                for (tbl_name,) in cur.fetchall():
                    postgres_candidates.append({
                        "schema": schema_name,
                        "table": tbl_name
                    })

    removed_candidates: List[dict] = []
    in_flight_candidates: List[dict] = []
    untracked_candidates: List[dict] = []
    
    now = datetime.datetime.utcnow()

    # 3. Classify and process each candidate table
    for candidate in postgres_candidates:
        schema = candidate["schema"]
        table = candidate["table"]
        
        match = _RUN_ID_REGEX.search(table)
        run_id = match.group(1) if match else None
        
        if not run_id or run_id not in sqlite_records:
            untracked_candidates.append({
                "schema": schema,
                "table": table,
                "reason": "No matching metadata record in generated_sql_review table."
            })
            continue

        rec = sqlite_records[run_id]
        created_dt = _parse_iso_datetime(rec["created_at"])
        
        if created_dt is None:
            # Unparseable timestamp, treat as untracked for safety
            untracked_candidates.append({
                "schema": schema,
                "table": table,
                "reason": f"Unparseable timestamp '{rec['created_at']}' in SQLite record."
            })
            continue

        age_seconds = (now - created_dt).total_seconds()
        is_promoted = (rec.get("status") == "PROMOTED")

        if is_promoted:
            # Table is marked promoted but still present in candidate schema (unexpected edge case)
            if age_seconds > age_threshold_seconds:
                try:
                    discard_candidate_table(table, schema, postgres_promotion_conninfo())
                    removed_candidates.append({
                        "schema": schema,
                        "table": table,
                        "run_id": run_id,
                        "age_seconds": int(age_seconds),
                        "reason": "Stale leftover table from previously promoted run."
                    })
                except PromotionError as e:
                    untracked_candidates.append({
                        "schema": schema,
                        "table": table,
                        "reason": f"Failed to discard promoted leftover: {e}"
                    })
            else:
                in_flight_candidates.append({
                    "schema": schema,
                    "table": table,
                    "run_id": run_id,
                    "reason": "Marked promoted recently."
                })
        elif age_seconds <= age_threshold_seconds:
            in_flight_candidates.append({
                "schema": schema,
                "table": table,
                "run_id": run_id,
                "age_seconds": int(age_seconds),
                "reason": f"Created recently ({int(age_seconds)}s <= threshold {age_threshold_seconds}s)."
            })
        else:
            # Safe to auto-remove: older than threshold and non-promoted
            try:
                discard_candidate_table(table, schema, postgres_promotion_conninfo())
                removed_candidates.append({
                    "schema": schema,
                    "table": table,
                    "run_id": run_id,
                    "age_seconds": int(age_seconds),
                    "reason": "Orphaned stale candidate table from failed or abandoned run."
                })
            except PromotionError as e:
                untracked_candidates.append({
                    "schema": schema,
                    "table": table,
                    "reason": f"Failed to discard orphaned candidate: {e}"
                })

    return {
        "status": "success",
        "threshold_seconds": age_threshold_seconds,
        "removed_candidates": removed_candidates,
        "in_flight_candidates": in_flight_candidates,
        "untracked_candidates": untracked_candidates
    }
