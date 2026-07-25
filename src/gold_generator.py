"""Ollama-backed Gold SQL Generator for Aurum Batch 5."""

from __future__ import annotations

import os
import logging
import requests
from typing import Sequence

from src.db_config import load_layer_schemas, get_generated_sql_pool
from src.sql_safety import validate_generated_sql, extract_gold_physical_sources, SqlSafetyViolation

logger = logging.getLogger(__name__)

OLLAMA_GOLD_PROVENANCE = "ollama_gold_generator_v1"
OLLAMA_GOLD_VERSION = "1.0.0"
DEFAULT_OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_OLLAMA_MODEL = "llama3"
OLLAMA_HTTP_TIMEOUT_SECONDS = 15.0


def fetch_silver_table_columns(silver_table_names: Sequence[str]) -> dict[str, list[tuple[str, str]]]:
    """Fetch schema details (columns and types) for the specified Silver tables."""
    schemas = load_layer_schemas()
    silver_schema = schemas.silver
    table_metadata: dict[str, list[tuple[str, str]]] = {}

    with get_generated_sql_pool().connection() as conn:
        with conn.cursor() as cur:
            for table_name in silver_table_names:
                cur.execute(
                    """
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s
                    ORDER BY ordinal_position
                    """,
                    (silver_schema, table_name),
                )
                rows = cur.fetchall()
                if rows:
                    table_metadata[table_name] = [(r[0], r[1]) for r in rows]
                else:
                    table_metadata[table_name] = []

    return table_metadata


def build_gold_prompt(
    *,
    silver_tables_meta: dict[str, list[tuple[str, str]]],
    target_table_name: str,
    candidate_table_name: str,
    candidate_schema: str,
    silver_schema: str,
    business_requirement: str,
    feedback: str | None = None,
) -> str:
    """Build structured prompt for Ollama Gold CTAS SQL generation."""
    table_descriptions = []
    for table_name, columns in silver_tables_meta.items():
        col_str = "\n".join(f"  - {name} ({dtype})" for name, dtype in columns) if columns else "  (No columns found)"
        table_descriptions.append(f"Table: {silver_schema}.{table_name}\nColumns:\n{col_str}")

    tables_text = "\n\n".join(table_descriptions)

    prompt = (
        f"You are a PostgreSQL data engineering expert.\n"
        f"Generate a single executable PostgreSQL SQL statement creating a Gold analytical dataset.\n\n"
        f"SOURCE TABLES ({silver_schema} schema):\n{tables_text}\n\n"
        f"TARGET CANDIDATE STATEMENT:\n"
        f"Create a candidate table in schema '{candidate_schema}' named '{candidate_table_name}'.\n"
        f"Format: CREATE TABLE {candidate_schema}.{candidate_table_name} AS SELECT ...\n\n"
        f"BUSINESS REQUIREMENT:\n{business_requirement}\n\n"
        f"STRICT RULES:\n"
        f"1. Output ONLY a single SQL statement: CREATE TABLE {candidate_schema}.{candidate_table_name} AS SELECT ...\n"
        f"2. Use ONLY valid PostgreSQL syntax.\n"
        f"3. References to source tables MUST use the full schema qualification: {silver_schema}.<table_name>\n"
        f"4. Do NOT include markdown formatting, code block fences (```), comments, or explanations.\n"
        f"5. Do NOT include any trailing semicolon or extra text.\n"
    )

    if feedback:
        prompt += f"\nPREVIOUS ATTEMPT FAILED SAFETY VALIDATION:\n{feedback}\nPlease fix the SQL to satisfy all strict rules."

    return prompt


def strip_markdown_code_fences(text: str) -> str:
    """Strip markdown code fences (```sql ... ```) if present in LLM output."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def call_ollama_gold_generator(
    *,
    target_table_name: str,
    candidate_table_name: str,
    silver_table_names: Sequence[str],
    business_requirement: str,
    run_id: str,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    model: str = DEFAULT_OLLAMA_MODEL,
    timeout_seconds: float = OLLAMA_HTTP_TIMEOUT_SECONDS,
) -> str:
    """Call Ollama to generate Gold SQL, stripping code fences, validating against AST safety gate, with 1 retry on parse/validation failure."""
    schemas = load_layer_schemas()
    silver_schema = schemas.silver
    candidate_schema = schemas.gold_candidates

    silver_meta = fetch_silver_table_columns(silver_table_names)
    selected_sources = tuple((silver_schema, name) for name in silver_table_names)

    attempts = 0
    max_attempts = 2
    feedback = None

    while attempts < max_attempts:
        attempts += 1
        prompt = build_gold_prompt(
            silver_tables_meta=silver_meta,
            target_table_name=target_table_name,
            candidate_table_name=candidate_table_name,
            candidate_schema=candidate_schema,
            silver_schema=silver_schema,
            business_requirement=business_requirement,
            feedback=feedback,
        )

        try:
            resp = requests.post(
                ollama_url,
                json={"model": model, "prompt": prompt, "stream": False},
                timeout=timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()
            raw_output = data.get("response", "")
        except requests.exceptions.Timeout as exc:
            logger.error("Ollama generator request timed out after %.1fs for run %s", timeout_seconds, run_id)
            raise TimeoutError(f"Ollama SQL generator request timed out after {timeout_seconds}s") from exc
        except requests.exceptions.RequestException as exc:
            logger.error("Ollama generator HTTP error for run %s: %s", run_id, exc)
            raise RuntimeError(f"Ollama connection error: {exc}") from exc

        sql_text = strip_markdown_code_fences(raw_output)

        try:
            # 1. AST Validation
            validated_sql = validate_generated_sql(
                sql_text,
                expected_schema=candidate_schema,
                expected_table_name=target_table_name,
                run_id=run_id,
                mode="generic",
            )
            # 2. Extract and verify physical sources match selected silver sources
            extracted_sources = extract_gold_physical_sources(validated_sql, selected_sources=selected_sources)
            if not extracted_sources:
                raise SqlSafetyViolation("Generated Gold SQL does not reference any of the selected Silver source tables.")

            return validated_sql
        except (SqlSafetyViolation, Exception) as exc:
            logger.warning("Attempt %d/%d generated invalid SQL for run %s: %s", attempts, max_attempts, run_id, exc)
            feedback = str(exc)
            if attempts >= max_attempts:
                raise ValueError(f"Generated SQL failed safety gate after retry: {exc}") from exc

    raise ValueError("Generated SQL failed safety gate.")
