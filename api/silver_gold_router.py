"""API Router for P3 Silver-to-Gold aggregations via LLM."""

from __future__ import annotations

import json
import re
import uuid
import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
import sqlglot
from sqlglot import exp

from src.app_state.db import get_connection
from src.db_config import (
    get_generated_sql_pool, 
    postgres_promotion_conninfo,
    load_layer_schemas
)
from src.sql_safety import validate_generated_sql, execute_candidate_sql
from src.promotion import promote_candidate_table

router = APIRouter(prefix="/api/v1/gold", tags=["gold"])

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3"
OLLAMA_TIMEOUT = 15

class GenerateGoldPayload(BaseModel):
    target_table_name: str
    silver_table_names: List[str]
    business_requirement: str

class ExecuteGoldPayload(BaseModel):
    overwrite: bool = False

def check_table_exists(schema_name: str, table_name: str) -> bool:
    """Check if a table exists in the given schema."""
    with get_generated_sql_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT to_regclass(%s)",
                (f'"{schema_name}"."{table_name}"',)
            )
            return cur.fetchone()[0] is not None

@router.get("/check-name")
def check_name(name: str = Query(..., description="The proposed name for the gold table")):
    """P3.1A: Synchronous check for gold table name collision."""
    schemas = load_layer_schemas()
    
    # Pre-flight identifier validation
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        return {
            "name": name,
            "is_valid_identifier": False,
            "is_available": False,
            "status": "invalid",
            "resolution_options": [],
            "message": f"'{name}' is not a valid PostgreSQL identifier."
        }
        
    try:
        exists = check_table_exists(schemas.gold, name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to check table existence: {e}")

    if exists:
        return {
            "name": name,
            "is_valid_identifier": True,
            "is_available": False,
            "status": "taken",
            "resolution_options": [
                {
                    "action": "overwrite",
                    "description": f"Replace the existing '{name}' table in the gold schema."
                },
                {
                    "action": "rename",
                    "description": "Choose a different name."
                }
            ],
            "message": f"The table '{name}' already exists in the Gold layer."
        }
    else:
        return {
            "name": name,
            "is_valid_identifier": True,
            "is_available": True,
            "status": "available",
            "resolution_options": [],
            "message": "Name is available."
        }

def get_multiple_table_schemas(schema_name: str, table_names: List[str]) -> str:
    """Fetch schema details for multiple tables."""
    if not table_names:
        raise ValueError("At least one source table must be provided.")
        
    schemas_out = []
    with get_generated_sql_pool().connection() as conn:
        with conn.cursor() as cur:
            for table_name in table_names:
                cur.execute(
                    """
                    SELECT column_name, data_type 
                    FROM information_schema.columns 
                    WHERE table_schema = %s AND table_name = %s
                    ORDER BY ordinal_position
                    """,
                    (schema_name, table_name)
                )
                rows = cur.fetchall()
                if not rows:
                    raise ValueError(f"Table {schema_name}.{table_name} not found.")
                
                cols_str = "\n".join([f"  - {r[0]} ({r[1]})" for r in rows])
                schemas_out.append(f"Table: {table_name}\nColumns:\n{cols_str}")
                
    return "\n\n".join(schemas_out)

def call_llm_stubbed(prompt: str) -> str:
    """
    TODO(sassee): Replace this stub with the real LLM integration.
    This function currently returns a hardcoded mock aggregation response 
    for end-to-end pipeline testing without a live LLM daemon.
    """
    import time
    if "TIMEOUT_TEST" in prompt:
        time.sleep(OLLAMA_TIMEOUT + 1)
        
    if not hasattr(call_llm_stubbed, "retry_count"):
        call_llm_stubbed.retry_count = 0
    call_llm_stubbed.retry_count += 1
        
    if "RETRY_TEST" in prompt and call_llm_stubbed.retry_count % 2 == 1:
        return "MALFORMED SQL"

    run_id_match = re.search(r"_candidate_(run_[a-f0-9]+)", prompt)
    run_id = run_id_match.group(1) if run_id_match else "run_mock"
    
    table_match = re.search(r"Candidate Table Name: ([a-zA-Z0-9_]+)_candidate_", prompt)
    table_name = table_match.group(1) if table_match else "daily_sales"
    
    schemas = load_layer_schemas()
    
    if "MULTI_TABLE_TEST" in prompt:
        return f"""
```sql
CREATE TABLE {schemas.gold_candidates}.{table_name}_candidate_{run_id} AS
SELECT 
    orders.status,
    customers.region,
    COUNT(orders.id) AS total_orders,
    SUM(orders.amount) AS revenue
FROM {schemas.silver}.orders
JOIN {schemas.silver}.customers ON orders.customer_id = customers.id
GROUP BY orders.status, customers.region;
```
"""
    
    return f"""
```sql
CREATE TABLE {schemas.gold_candidates}.{table_name}_candidate_{run_id} AS
SELECT 
    DATE(order_date) AS order_day, 
    COUNT(*) AS total_orders
FROM {schemas.silver}.orders
GROUP BY DATE(order_date);
```
"""

def strip_markdown(raw_text: str) -> str:
    """Strip markdown code blocks from LLM response."""
    stripped_sql = raw_text.strip()
    matches = re.findall(r'```(?:sql|postgresql)?\n(.*?)```', stripped_sql, re.DOTALL | re.IGNORECASE)
    if matches:
        return matches[0].strip()
    stripped_sql = re.sub(r'^```(?:sql|postgresql)?\n', '', stripped_sql, flags=re.IGNORECASE)
    stripped_sql = re.sub(r'\n```$', '', stripped_sql)
    return stripped_sql.strip()

def summarize_sql_structure(sql_text: str) -> dict:
    """Derive planned output summary from AST."""
    try:
        stmt = sqlglot.parse_one(sql_text, read="postgres")
        select_stmt = stmt.args.get("expression") if isinstance(stmt, exp.Create) else stmt
        
        group_by = select_stmt.args.get("group") if select_stmt else None
        groups = [e.sql(dialect="postgres") for e in group_by.expressions] if group_by else []
        
        aggregates = []
        if select_stmt:
            for select_expr in select_stmt.expressions:
                if any(isinstance(node, exp.AggFunc) for node in select_expr.find_all(exp.AggFunc)):
                    aggregates.append(select_expr.alias_or_name)
                    
        has_filters = bool(select_stmt.args.get("where") or select_stmt.args.get("having")) if select_stmt else False
        
        sources = []
        if select_stmt:
            from_clause = select_stmt.args.get("from")
            if from_clause:
                for table in from_clause.find_all(exp.Table):
                    sources.append(table.name)
            
            for join in select_stmt.args.get("joins") or []:
                for table in join.find_all(exp.Table):
                    sources.append(table.name)
                    
        sources_str = ", ".join(set(sources)) if sources else "unknown sources"
        summary_text = f"This query computes aggregations from {sources_str}."
        
        return {
            "summary": summary_text,
            "dimensions": groups,
            "metrics": aggregates,
            "filters_applied": has_filters
        }
    except Exception:
        # Graceful degradation if parsing fails for summary extraction
        return {
            "summary": "Could not automatically summarize the query structure.",
            "dimensions": [],
            "metrics": [],
            "filters_applied": False
        }


@router.post("/generate")
def generate_gold_sql(payload: GenerateGoldPayload):
    """P3.2 & P3.3: Generate SQL via LLM for the requested Gold aggregation."""
    schemas = load_layer_schemas()
    
    try:
        silver_schema_metadata = get_multiple_table_schemas(schemas.silver, payload.silver_table_names)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
        
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    
    prompt = f"""You are an expert PostgreSQL Data Engineer.

Source tables (Silver):
{silver_schema_metadata}

Target schema: {schemas.gold_candidates}
Candidate Table Name: {payload.target_table_name}_candidate_{run_id}

Business Requirement:
{payload.business_requirement}

Generate a single valid PostgreSQL statement to satisfy this requirement.
You MUST output ONLY raw SQL code. No markdown code blocks (```sql), no explanations, no conversational text.

Requirement:
The output must be a valid CREATE TABLE AS SELECT statement targeting the candidate schema.
Example:
CREATE TABLE {schemas.gold_candidates}.{payload.target_table_name}_candidate_{run_id} AS
SELECT 
    DATE(order_date) AS order_day, 
    COUNT(*) AS total_orders
FROM {schemas.silver}.orders
GROUP BY DATE(order_date);
"""

    import concurrent.futures
    max_attempts = 2
    last_error = None
    
    for attempt in range(max_attempts):
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(call_llm_stubbed, prompt)
                raw_response = future.result(timeout=OLLAMA_TIMEOUT)

            stripped_sql = strip_markdown(raw_response)
            
            # P0 AST safety gate, explicitly NO step count enforcement for Gold
            validate_generated_sql(stripped_sql, expected_schema=schemas.gold_candidates, run_id=run_id, expected_step_count=None)
            
            last_error = None
            break
        except concurrent.futures.TimeoutError:
            last_error = f"LLM generation timed out after {OLLAMA_TIMEOUT} seconds."
            raise HTTPException(status_code=504, detail=last_error)
        except Exception as e:
            last_error = f"Generated SQL failed safety validation: {e}"
            if attempt == max_attempts - 1:
                raise HTTPException(status_code=422, detail=last_error)

    # Derive planned output summary from AST
    planned_changes = summarize_sql_structure(stripped_sql)

    now = datetime.datetime.utcnow().isoformat()
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO generated_sql_review (run_id, table_name, sql_text, planned_changes_json, created_at, status)
                VALUES (?, ?, ?, ?, ?, 'PENDING')
                """,
                (run_id, payload.target_table_name, stripped_sql, json.dumps(planned_changes), now)
            )
            conn.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save generated SQL for review: {e}")

    return {
        "run_id": run_id, 
        "status": "success",
        "message": "SQL generated successfully and ready for review."
    }

@router.get("/review/{run_id}")
def review_gold_sql(run_id: str):
    """P3.4a: Review the generated SQL and validate it again (no execution)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT table_name, sql_text, planned_changes_json FROM generated_sql_review WHERE run_id = ?",
            (run_id,)
        ).fetchone()
        
    if not row:
        raise HTTPException(status_code=404, detail="Run ID not found.")
        
    sql_text = row[1]
    
    try:
        schemas = load_layer_schemas()
        validated_sql = validate_generated_sql(sql_text, expected_schema=schemas.gold_candidates, run_id=run_id, expected_step_count=None)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"SQL failed structural validation: {e}")

    return {
        "run_id": run_id,
        "table_name": row[0],
        "planned_changes": json.loads(row[2]),
        "sql_text": validated_sql,
        "executed": False,
        "message": "SQL is validated and ready for execution."
    }

@router.post("/execute/{run_id}")
def execute_gold_sql(run_id: str, payload: ExecuteGoldPayload):
    """P3.4b & P3.5: Execute generated SQL, fetch preview, and promote to gold."""
    with get_connection() as conn_db:
        row = conn_db.execute(
            "SELECT table_name, sql_text FROM generated_sql_review WHERE run_id = ?",
            (run_id,)
        ).fetchone()
        
    if not row:
        raise HTTPException(status_code=404, detail="Run ID not found or already executed.")
        
    table_name = row[0]
    sql_text = row[1]
    
    schemas = load_layer_schemas()
    
    # 1. TOCTOU Check: Ensure overwrite is respected at execution time
    exists = check_table_exists(schemas.gold, table_name)
    if exists and not payload.overwrite:
        raise HTTPException(
            status_code=409, 
            detail=f"Table '{table_name}' exists in the gold schema. Provide overwrite=True to replace it."
        )

    # 2. Execution and Ownership Transfer (aurum_generated_sql -> aurum_promotion)
    try:
        with get_generated_sql_pool().connection() as conn:
            execute_candidate_sql(sql_text, conn, expected_schema=schemas.gold_candidates, run_id=run_id)
            conn.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to execute candidate SQL: {e}")

    candidate_name = f"{table_name}_candidate_{run_id}"

    # 3. P3.5: Gold preview via LIMIT from the candidate table
    preview_rows = []
    total_rows = 0
    try:
        with get_generated_sql_pool().connection() as conn:
            with conn.cursor() as cur:
                # Count
                cur.execute(f'SELECT COUNT(*) FROM "{schemas.gold_candidates}"."{candidate_name}"')
                total_rows = cur.fetchone()[0]
                
                # Preview
                cur.execute(f'SELECT * FROM "{schemas.gold_candidates}"."{candidate_name}" LIMIT 5')
                cols = [desc[0] for desc in cur.description] if cur.description else []
                preview_rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to preview gold candidate table: {e}")

    # 4. Promotion to Gold (aurum_promotion)
    try:
        promote_candidate_table(
            candidate_table=candidate_name,
            candidate_schema=schemas.gold_candidates,
            target_table=table_name,
            target_schema=schemas.gold,
            promotion_conninfo=postgres_promotion_conninfo()
        )
        now_promoted = datetime.datetime.utcnow().isoformat()
        with get_connection() as conn_db:
            conn_db.execute(
                "UPDATE generated_sql_review SET status = 'PROMOTED', promoted_at = ? WHERE run_id = ?",
                (now_promoted, run_id)
            )
            conn_db.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to promote candidate to gold: {e}")
        
    return {
        "status": "success",
        "run_id": run_id,
        "table_name": table_name,
        "total_rows": total_rows,
        "preview_rows": preview_rows,
        "message": f"Successfully executed and promoted {table_name} to Gold."
    }
