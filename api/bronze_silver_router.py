"""API Router for P2-A Bronze-to-Silver transformations via LLM."""

from __future__ import annotations

import json
import re
import uuid
import datetime
from typing import List, Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import requests

from src.app_state.db import get_connection
from src.db_config import (
    get_ingestion_pool, 
    get_generated_sql_pool, 
    postgres_promotion_conninfo,
    load_layer_schemas
)
from src.sql_safety import validate_generated_sql, execute_candidate_sql
from src.promotion import promote_candidate_table
import sqlglot

router = APIRouter(prefix="/api/v1/transform", tags=["transform"])

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3"
OLLAMA_TIMEOUT = 15

class RulesPayload(BaseModel):
    table_name: str
    rules: List[str]

class GeneratePayload(BaseModel):
    table_name: str

def get_table_schema(table_name: str) -> str:
    """Fetch schema details for a table in the bronze schema."""
    import psycopg
    schemas = load_layer_schemas()
    try:
        with get_ingestion_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name, data_type 
                    FROM information_schema.columns 
                    WHERE table_schema = %s AND table_name = %s
                    ORDER BY ordinal_position
                    """,
                    (schemas.bronze, table_name)
                )
                rows = cur.fetchall()
                if not rows:
                    raise ValueError(f"Table {schemas.bronze}.{table_name} not found.")
                return "\n".join([f"- {r[0]} ({r[1]})" for r in rows])
    except Exception as e:
        raise ValueError(f"Could not retrieve schema for {table_name}: {e}")

def call_llm_stubbed(prompt: str) -> str:
    """
    TODO(sassee): Replace this stub with the real LLM integration.
    This function currently returns a hardcoded mock CTE response 
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

    # Extract the run_id from the prompt for the mock
    run_id_match = re.search(r"_candidate_(run_[a-f0-9]+)", prompt)
    run_id = run_id_match.group(1) if run_id_match else "run_mock"

    if "NO_CTE_TEST" in prompt:
        return "SELECT 1;"

    if "TOO_MANY_CTE_TEST" in prompt:
        schemas = load_layer_schemas()
        return f"CREATE TABLE {schemas.silver_candidates}.src_orders_TOO_MANY_CTE_TEST_candidate_{run_id} AS WITH step_1 AS (SELECT 1), step_2 AS (SELECT 2), step_3 AS (SELECT 3) SELECT * FROM step_3;"
    # Extract the run_id from the prompt for the mock
    run_id_match = re.search(r"_candidate_(run_[a-f0-9]+)", prompt)
    run_id = run_id_match.group(1) if run_id_match else "run_mock"
    
    # Extract table name from the prompt to make the mock match
    table_match = re.search(r"Candidate Table Name: ([a-zA-Z0-9_]+)_candidate_", prompt)
    table_name = table_match.group(1) if table_match else "src_orders_test"
    
    schemas = load_layer_schemas()
    return f"""Here is the SQL!
```sql
CREATE TABLE {schemas.silver_candidates}.{table_name}_candidate_{run_id} AS
WITH step_1 AS (
    SELECT * FROM {schemas.bronze}.{table_name} WHERE total_amount >= 0
),
step_2 AS (
    SELECT id, customer_id, total_amount, UPPER(status) as status FROM step_1
),
step_3 AS (
    SELECT * FROM step_2 WHERE customer_id IS NOT NULL
)
SELECT * FROM step_3;
```
"""

def strip_markdown(raw_text: str) -> str:
    """Strip markdown code blocks from LLM response."""
    stripped_sql = raw_text.strip()
    
    matches = re.findall(r'```(?:sql|postgresql)?\n(.*?)```', stripped_sql, re.DOTALL | re.IGNORECASE)
    if matches:
        stripped_sql = matches[0].strip()
    else:
        stripped_sql = re.sub(r'^```(?:sql|postgresql)?\n', '', stripped_sql, flags=re.IGNORECASE)
        stripped_sql = re.sub(r'\n```$', '', stripped_sql)
        stripped_sql = stripped_sql.strip()
        
    return stripped_sql

@router.post("/rules")
def save_rules(payload: RulesPayload):
    """P2.1: Save free-text rules for a Bronze table."""
    now = datetime.datetime.utcnow().isoformat()
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO table_rules (table_name, rules_json, updated_at) 
                VALUES (?, ?, ?)
                ON CONFLICT(table_name) DO UPDATE SET 
                    rules_json=excluded.rules_json,
                    updated_at=excluded.updated_at
                """,
                (payload.table_name, json.dumps(payload.rules), now)
            )
            conn.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save rules: {e}")
    
    return {"status": "success", "message": "Rules saved successfully"}

@router.get("/rules/{table_name}")
def get_rules(table_name: str):
    """Fetch saved rules for a table."""
    with get_connection() as conn:
        row = conn.execute("SELECT rules_json FROM table_rules WHERE table_name = ?", (table_name,)).fetchone()
        if row:
            return {"table_name": table_name, "rules": json.loads(row[0])}
        return {"table_name": table_name, "rules": []}

@router.post("/generate")
def generate_sql(payload: GeneratePayload):
    """P2.2 & P2.3: Generate SQL via LLM for the requested table."""
    # 1. Fetch rules
    rules_resp = get_rules(payload.table_name)
    rules = rules_resp.get("rules", [])
    if not rules:
        raise HTTPException(status_code=400, detail="No rules defined for this table.")
        
    # 2. Fetch schema
    try:
        schema_text = get_table_schema(payload.table_name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
        
    # 3. Construct prompt
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    rules_text = "\n".join([f"{i+1}. {r}" for i, r in enumerate(rules)])
    
    schemas = load_layer_schemas()
    prompt = f"""You are an expert PostgreSQL Data Engineer.

Table: {payload.table_name}
Source schema: {schemas.bronze}
Target schema: {schemas.silver_candidates}
Candidate Table Name: {payload.table_name}_candidate_{run_id}
Columns:
{schema_text}

User Cleaning Rules (apply in exact order):
{rules_text}

Generate a single valid PostgreSQL statement to apply these rules.
You MUST output ONLY raw SQL code. No markdown code blocks (```sql), no explanations, no conversational text.

Requirement:
The output must exactly follow this structure, using exactly ONE Common Table Expression (CTE) per rule (e.g., step_1, step_2, step_3) so that rules are applied sequentially:

CREATE TABLE {schemas.silver_candidates}.{payload.table_name}_candidate_{run_id} AS
WITH step_1 AS (
    SELECT ... FROM {schemas.bronze}.{payload.table_name} WHERE ...
),
step_2 AS (
    SELECT ... FROM step_1 ...
),
step_3 AS (
    SELECT ... FROM step_2 ...
)
SELECT * FROM step_3;
"""

    # 4. Call Ollama (Stubbed for now, awaiting sassee's integration)
    import concurrent.futures
    max_attempts = 2
    last_error = None
    
    for attempt in range(max_attempts):
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(call_llm_stubbed, prompt)
                raw_response = future.result(timeout=OLLAMA_TIMEOUT)

            # 5. Parse and strip markdown
            stripped_sql = strip_markdown(raw_response)
            
            # 6. Pre-flight structural check (P0 AST safety gate, before saving for review)
            validate_generated_sql(stripped_sql, expected_schema=schemas.silver_candidates, run_id=run_id, expected_step_count=len(rules))
            
            last_error = None
            break
        except concurrent.futures.TimeoutError:
            last_error = f"LLM generation timed out after {OLLAMA_TIMEOUT} seconds."
            # Immediately raise, do not retry on timeout for UX reasons
            raise HTTPException(status_code=504, detail=last_error)
        except Exception as e:
            last_error = f"Generated SQL failed safety validation: {e}"
            if attempt == max_attempts - 1:
                raise HTTPException(status_code=422, detail=last_error)

    # 7. Build planned changes summary (P2.4)
    # CTE count matches rule count because validate_generated_sql enforced it
    cte_count = len(rules)
    summary_text = f"Successfully planned {cte_count} sequential steps matching your {len(rules)} rules. Each rule will be applied cumulatively."

    planned_changes = {
        "summary": summary_text,
        "rules": [f"Step {i+1}: {r}" for i, r in enumerate(rules)],
        "cte_steps_detected": cte_count,
        "attribution_safe": True
    }

    # 8. Persist for review
    now = datetime.datetime.utcnow().isoformat()
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO generated_sql_review (run_id, table_name, sql_text, planned_changes_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, payload.table_name, stripped_sql, json.dumps(planned_changes), now)
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
def review_sql(run_id: str):
    """P2.5: Review the generated SQL and validate it again (no execution)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT table_name, sql_text, planned_changes_json, created_at FROM generated_sql_review WHERE run_id = ?",
            (run_id,)
        ).fetchone()
        
    if not row:
        raise HTTPException(status_code=404, detail="Run ID not found.")
        
    sql_text = row[1]
    planned_changes = json.loads(row[2])
    
    # Validate the SQL again right before returning for review to be absolutely certain
    try:
        schemas = load_layer_schemas()
        validated_sql = validate_generated_sql(sql_text, expected_schema=schemas.silver_candidates, run_id=run_id, expected_step_count=len(planned_changes.get("rules", [])))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"SQL failed structural validation: {e}")

    return {
        "run_id": run_id,
        "table_name": row[0],
        "planned_changes": json.loads(row[2]),
        "sql_text": validated_sql,
        "executed": False,
        "message": "SQL is validated and ready for execution (P2-B)."
    }

@router.post("/execute/{run_id}")
def execute_sql(run_id: str):
    """P2-B: Execute generated SQL, compute cumulative attribution, and promote to silver."""
    with get_connection() as conn_db:
        row = conn_db.execute(
            "SELECT table_name, sql_text, planned_changes_json FROM generated_sql_review WHERE run_id = ?",
            (run_id,)
        ).fetchone()
        
    if not row:
        raise HTTPException(status_code=404, detail="Run ID not found or already executed.")
        
    table_name = row[0]
    sql_text = row[1]
    planned_changes = json.loads(row[2])
    rules = planned_changes.get("rules", [])
    
    schemas = load_layer_schemas()
    
    # 1. Cumulative Attribution Measurement
    stmt = sqlglot.parse_one(sql_text, read="postgres")
    try:
        select_expr = stmt.args.get("expression")
        with_clause = select_expr.args.get("with")
        cte_names = [cte.alias for cte in with_clause.expressions]
        
        selects = [f"(SELECT COUNT(*) FROM {schemas.bronze}.{table_name}) as step_0_count"]
        for name in cte_names:
            selects.append(f"(SELECT COUNT(*) FROM {name}) as {name}_count")
            
        count_sql = f"{with_clause.sql(dialect='postgres')} SELECT {', '.join(selects)}"
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to build attribution query: {e}")

    attribution_results = []
    try:
        # Run count query securely with generated_sql role
        with get_generated_sql_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(count_sql)
                counts = cur.fetchone()
                
                initial_count = counts[0]
                attribution_results.append(f"Initial Bronze Rows: {initial_count}")
                
                # Match steps to rules if safe, otherwise just show steps
                for i in range(len(cte_names)):
                    prev_count = counts[i]
                    curr_count = counts[i+1]
                    diff = prev_count - curr_count
                    
                    rule_label = rules[i] if i < len(rules) else f"Step {i+1}"
                    
                    if diff > 0:
                        attribution_results.append(f"{rule_label}: {diff} rows removed (Remaining: {curr_count})")
                    else:
                        attribution_results.append(f"{rule_label}: Transformation applied (Remaining: {curr_count})")
                        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to execute attribution query: {e}")

    # 2. Execution and Ownership Transfer (aurum_generated_sql -> aurum_promotion)
    try:
        with get_generated_sql_pool().connection() as conn:
            execute_candidate_sql(sql_text, conn, expected_schema=schemas.silver_candidates, run_id=run_id)
            conn.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to execute candidate SQL: {e}")

    # 3. Promotion to Silver (aurum_promotion)
    candidate_name = f"{table_name}_candidate_{run_id}"
    try:
        promote_candidate_table(
            candidate_table=candidate_name,
            candidate_schema=schemas.silver_candidates,
            target_table=table_name,
            target_schema=schemas.silver,
            promotion_conninfo=postgres_promotion_conninfo()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to promote candidate to silver: {e}")
        
    return {
        "status": "success",
        "run_id": run_id,
        "table_name": table_name,
        "attribution_log": attribution_results,
        "message": f"Successfully executed and promoted {table_name} to Silver."
    }
