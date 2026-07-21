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
from src.db_config import postgres_conninfo, get_ingestion_pool
from src.sql_safety import validate_generated_sql

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
    try:
        with get_ingestion_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name, data_type 
                    FROM information_schema.columns 
                    WHERE table_schema = 'bronze' AND table_name = %s
                    ORDER BY ordinal_position
                    """,
                    (table_name,)
                )
                rows = cur.fetchall()
                if not rows:
                    raise ValueError(f"Table bronze.{table_name} not found.")
                return "\n".join([f"- {r[0]} ({r[1]})" for r in rows])
    except Exception as e:
        raise ValueError(f"Could not retrieve schema for {table_name}: {e}")

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
    
    prompt = f"""You are an expert PostgreSQL Data Engineer.

Table: {payload.table_name}
Source schema: bronze
Target schema: silver_candidates
Candidate Table Name: {payload.table_name}_candidate_{run_id}
Columns:
{schema_text}

User Cleaning Rules (apply in exact order):
{rules_text}

Generate a single valid PostgreSQL statement to apply these rules.
You MUST output ONLY raw SQL code. No markdown code blocks (```sql), no explanations, no conversational text.

Requirement:
The output must exactly follow this structure, using exactly ONE Common Table Expression (CTE) per rule (e.g., step_1, step_2, step_3) so that rules are applied sequentially:

CREATE TABLE silver_candidates.{payload.table_name}_candidate_{run_id} AS
WITH step_1 AS (
    SELECT ... FROM bronze.{payload.table_name} WHERE ...
),
step_2 AS (
    SELECT ... FROM step_1 ...
),
step_3 AS (
    SELECT ... FROM step_2 ...
)
SELECT * FROM step_3;
"""

    # 4. Call Ollama
    raw_response = ""
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=OLLAMA_TIMEOUT
        )
        resp.raise_for_status()
        raw_response = resp.json().get("response", "")
    except requests.exceptions.RequestException as e:
        # P2.3: Single retry on parse/network failure
        try:
            resp = requests.post(
                OLLAMA_URL,
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
                timeout=OLLAMA_TIMEOUT
            )
            resp.raise_for_status()
            raw_response = resp.json().get("response", "")
        except Exception as retry_e:
            raise HTTPException(status_code=502, detail=f"LLM communication failed: {retry_e}")

    # 5. Parse and strip markdown
    stripped_sql = strip_markdown(raw_response)
    
    # 6. Pre-flight structural check (P0 AST safety gate, before saving for review)
    try:
        validate_generated_sql(stripped_sql, run_id=run_id)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Generated SQL failed safety validation: {e}")

    # 7. Build planned changes summary (P2.4)
    # Simple summary based on rules list and CTE detection
    cte_count = len(re.findall(r'step_\d+\s+AS\s*\(', stripped_sql, flags=re.IGNORECASE))
    
    if cte_count == len(rules):
        summary_text = f"Successfully planned {cte_count} sequential steps matching your {len(rules)} rules. Each rule will be applied cumulatively."
    else:
        summary_text = f"Warning: The AI generated {cte_count} SQL steps for your {len(rules)} rules. Cumulative attribution per rule might not perfectly align."

    planned_changes = {
        "summary": summary_text,
        "rules": [f"Step {i+1}: {r}" for i, r in enumerate(rules)],
        "cte_steps_detected": cte_count,
        "attribution_safe": cte_count == len(rules)
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
    
    # Validate the SQL again right before returning for review to be absolutely certain
    try:
        validated_sql = validate_generated_sql(sql_text, run_id=run_id)
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
