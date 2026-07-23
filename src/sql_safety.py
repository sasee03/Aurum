"""AST structural safety gate for Aurum generated SQL."""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import Scope, traverse_scope

from src.db_config import LayerSchemas


class SqlSafetyViolation(Exception):
    """Raised when generated SQL fails structural AST safety checks."""
    pass


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CANDIDATE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*_candidate_[A-Za-z0-9_]+$")
_COMMENT_RE = re.compile(r"(--|/\*)")
POSTGRES_IDENTIFIER_MAX_BYTES = 63

_IF_NOT_EXISTS_RE = re.compile(r"\bIF\s+NOT\s+EXISTS\b", re.IGNORECASE)
_FORBIDDEN_NODES = (
    exp.Drop,
    exp.Alter,
    exp.Update,
    exp.Insert,
    exp.Delete,
    exp.TruncateTable,
    exp.Grant,
    exp.Command,
)


def _is_select_like(expression: exp.Expression) -> bool:
    return isinstance(expression, (exp.Select, exp.Union, exp.Intersect, exp.Except))


def _identifier_value(identifier: exp.Expression | None, *, field: str) -> str:
    if not isinstance(identifier, exp.Identifier):
        raise SqlSafetyViolation(f"{field} must be a PostgreSQL identifier.")
    value = identifier.name if identifier.args.get("quoted") else identifier.name.lower()
    if (
        not _IDENTIFIER_RE.fullmatch(value)
        or len(value.encode("utf-8")) > POSTGRES_IDENTIFIER_MAX_BYTES
    ):
        raise SqlSafetyViolation(f"{field} is not a safe PostgreSQL identifier.")
    return value


def _validate_candidate_name(table_name: str, run_id: str | None, expected_table_name: str | None = None) -> None:
    if not _CANDIDATE_RE.match(table_name):
        raise SqlSafetyViolation(
            f"Generated tables must be named <target>_candidate_<run_id>, found: {table_name}"
        )
    if run_id is not None:
        if not _IDENTIFIER_RE.match(run_id):
            raise SqlSafetyViolation(f"Unsafe run id: {run_id}")
        suffix = f"_candidate_{run_id}"
        if not table_name.endswith(suffix):
            raise SqlSafetyViolation(
                f"Candidate table must end with {suffix}, found: {table_name}"
            )
    if expected_table_name is not None and run_id is not None:
        expected_full_name = f"{expected_table_name}_candidate_{run_id}"
        if table_name != expected_full_name:
            raise SqlSafetyViolation(
                f"Candidate table target must be EXACTLY {expected_full_name}, found: {table_name}"
            )


def _validate_gold_sources(
    select_expression: exp.Expression,
    *,
    selected_sources: tuple[tuple[str, str], ...],
) -> None:
    allowed = frozenset(selected_sources)
    physical_sources: set[tuple[str, str]] = set()

    if any(
        isinstance(dot.expression, exp.Func)
        for dot in select_expression.find_all(exp.Dot)
    ):
        raise SqlSafetyViolation(
            "Gold SQL cannot call schema-qualified functions."
        )

    for scope in traverse_scope(select_expression):
        if scope.udtfs:
            raise SqlSafetyViolation(
                "Gold SQL cannot use table functions, VALUES, or generated relation sources."
            )
        for table in scope.tables:
            if not isinstance(table.this, exp.Identifier):
                raise SqlSafetyViolation(
                    "Gold SQL physical sources must be ordinary tables."
                )
            source = scope.sources.get(table.alias_or_name)
            if isinstance(source, Scope):
                continue
            if not isinstance(source, exp.Table):
                raise SqlSafetyViolation("Gold SQL contains an unresolved relation source.")
            if table.args.get("catalog") is not None:
                raise SqlSafetyViolation(
                    "Gold SQL cannot use catalog-qualified physical sources."
                )
            if table.args.get("db") is None:
                raise SqlSafetyViolation(
                    "Gold SQL physical sources must be schema-qualified."
                )
            source_ref = (
                _identifier_value(
                    table.args.get("db"),
                    field="Gold source schema",
                ),
                _identifier_value(table.this, field="Gold source relation"),
            )
            if source_ref not in allowed:
                raise SqlSafetyViolation(
                    "Gold SQL references a physical source outside the approved Silver set."
                )
            physical_sources.add(source_ref)

    if not physical_sources:
        raise SqlSafetyViolation(
            "Gold SQL must read at least one approved physical Silver source."
        )


def validate_generated_sql(
    sql_str: str,
    *,
    expected_schema: str,
    expected_table_name: str | None = None,
    expected_bronze_schema: str | None = None,
    run_id: str | None = None,
    layer_schemas: LayerSchemas | None = None,
    expected_step_count: int | None = None,
    mode: str = "generic",
    selected_sources: tuple[tuple[str, str], ...] | None = None,
    expected_candidate_name: str | None = None,
) -> str:
    """Validate a single SELECT or CREATE TABLE AS SELECT generated by the LLM.

    Supports modes:
    - "generic": Basic AST safety, no forbidden DDL/DML, target schema/candidate checks.
    - "p2_silver": P2 sequential Silver transformation policy (strict CTE chain, physical source binding).
    - "gold_ctas": Exact Gold candidate CTAS with lexical-scope physical-source containment.

    Schema identities are caller-supplied so validation never reinterprets persisted
    SQL against current environment configuration.
    """
    if not sql_str or not sql_str.strip():
        raise SqlSafetyViolation("Empty SQL statement.")
    if _COMMENT_RE.search(sql_str):
        raise SqlSafetyViolation("SQL comments are not allowed in generated SQL.")
    if _IF_NOT_EXISTS_RE.search(sql_str):
        raise SqlSafetyViolation("CREATE TABLE IF NOT EXISTS is not allowed for candidates.")

    try:
        statements = sqlglot.parse(sql_str, read="postgres")
    except Exception as e:
        raise SqlSafetyViolation(f"SQL parsing failed: {e}")

    if not statements:
        raise SqlSafetyViolation("Empty SQL statement.")

    valid_stmts = [s for s in statements if s is not None]

    if len(valid_stmts) != 1:
        raise SqlSafetyViolation(f"Only exactly one SQL statement is allowed, found {len(valid_stmts)}.")

    stmt = valid_stmts[0]

    if mode == "gold_ctas" and not isinstance(stmt, exp.Create):
        raise SqlSafetyViolation(
            "Gold execution requires exactly one CREATE TABLE AS SELECT statement."
        )
    if not isinstance(stmt, exp.Create) and not _is_select_like(stmt):
        raise SqlSafetyViolation(f"Statement must be SELECT or CREATE TABLE AS, found: {type(stmt).__name__}")
        
    if _is_select_like(stmt) and stmt.args.get("into"):
        raise SqlSafetyViolation("SELECT INTO is not allowed. Use CREATE TABLE AS SELECT.")

    for node_type in _FORBIDDEN_NODES:
        for node in stmt.find_all(node_type):
            raise SqlSafetyViolation(f"Forbidden operation found: {type(node).__name__}")

    if isinstance(stmt, exp.Create):
        if stmt.args.get("kind") != "TABLE":
            raise SqlSafetyViolation(f"Only CREATE TABLE is allowed in DDL, found {stmt.args.get('kind')}.")

        expression = stmt.args.get("expression")
        if not expression or not _is_select_like(expression):
            raise SqlSafetyViolation("CREATE TABLE must have an AS SELECT body.")

        this = stmt.args.get("this")
        if not isinstance(this, exp.Table):
            raise SqlSafetyViolation("Missing table name in CREATE TABLE.")

        # Reject catalog-qualified candidate CREATE targets (e.g., evil.silver_candidates.table)
        if this.args.get("catalog"):
            catalog_name = this.args.get("catalog").name if hasattr(this.args.get("catalog"), "name") else str(this.args.get("catalog"))
            raise SqlSafetyViolation(f"Catalog-qualified target table is not allowed, found: {catalog_name}")

        table_name = _identifier_value(this.this, field="candidate relation")
        _validate_candidate_name(table_name, run_id, expected_table_name=expected_table_name)

        schema_node = this.args.get("db")
        if not schema_node:
            raise SqlSafetyViolation("CREATE TABLE must specify a target schema.")

        schema_name = _identifier_value(schema_node, field="candidate schema")
        if schema_name != expected_schema:
            raise SqlSafetyViolation(
                f"Target schema must be {expected_schema}, found: {schema_name}"
            )

        if mode == "gold_ctas":
            if selected_sources is None or expected_candidate_name is None:
                raise SqlSafetyViolation(
                    "Gold SQL validation requires persisted source and candidate authority."
                )
            if table_name != expected_candidate_name:
                raise SqlSafetyViolation(
                    "Gold SQL target does not match the exact approved candidate."
                )
            if any(
                stmt.args.get(flag)
                for flag in (
                    "replace",
                    "refresh",
                    "unique",
                    "exists",
                    "properties",
                    "indexes",
                    "no_schema_binding",
                    "begin",
                    "end",
                    "clone",
                    "concurrently",
                    "clustered",
                )
            ):
                raise SqlSafetyViolation(
                    "Gold SQL must use an unmodified permanent CREATE TABLE AS SELECT."
                )
            normalized_sources = tuple(
                (
                    _validated_authority_identifier(schema, field="selected source schema"),
                    _validated_authority_identifier(table, field="selected source relation"),
                )
                for schema, table in selected_sources
            )
            _validate_gold_sources(
                expression,
                selected_sources=normalized_sources,
            )

    # Mode-specific validation
    if mode == "p2_silver":
        if not isinstance(stmt, exp.Create):
            raise SqlSafetyViolation("P2 Silver transformation requires a CREATE TABLE AS SELECT statement.")
        select_expr = stmt.args.get("expression")
        with_clause = select_expr.args.get("with") if select_expr else None
        ctes = with_clause.expressions if with_clause else []

        if expected_step_count is not None and len(ctes) != expected_step_count:
            raise SqlSafetyViolation(f"Expected exactly {expected_step_count} CTEs, found {len(ctes)}.")

        if len(ctes) == 0:
            raise SqlSafetyViolation("P2 Silver transformation requires at least one sequential step CTE.")

        for i, cte in enumerate(ctes):
            expected_cte_name = f"step_{i+1}"
            if cte.alias != expected_cte_name:
                raise SqlSafetyViolation(
                    f"CTE #{i+1} must be named '{expected_cte_name}', found: '{cte.alias}'"
                )

            # Reject JOINs, VALUES, subqueries inside CTE step
            if list(cte.this.find_all(exp.Join)):
                raise SqlSafetyViolation(f"step_{i+1} must not contain JOINs.")
            if list(cte.this.find_all(exp.Values)):
                raise SqlSafetyViolation(f"step_{i+1} must not use VALUES relations.")
            if list(cte.this.find_all(exp.Subquery)):
                raise SqlSafetyViolation(f"step_{i+1} must not contain subqueries.")

            tables = list(cte.this.find_all(exp.Table))
            if len(tables) != 1:
                raise SqlSafetyViolation(
                    f"step_{i+1} must reference exactly one relation (no JOINs or multiple physical tables)."
                )

            tbl = tables[0]
            tbl_name = tbl.name
            tbl_catalog = tbl.args.get("catalog").name if tbl.args.get("catalog") else None
            tbl_schema = tbl.args.get("db").name if tbl.args.get("db") else None

            if tbl_catalog is not None:
                raise SqlSafetyViolation(
                    f"step_{i+1} relation cannot be catalog-qualified, found: '{tbl_catalog}.{tbl_schema or ''}.{tbl_name}'"
                )

            if i == 0:
                # step_1 must reference schema-qualified Bronze source table exactly
                req_bronze_schema = expected_bronze_schema or "bronze"
                if tbl_schema is None:
                    raise SqlSafetyViolation(
                        f"step_1 must read from schema-qualified Bronze table '{req_bronze_schema}.{expected_table_name or tbl_name}'"
                    )
                if tbl_schema != req_bronze_schema:
                    raise SqlSafetyViolation(
                        f"step_1 must read from permitted Bronze schema {req_bronze_schema}, found: {tbl_schema}"
                    )
                if expected_table_name is not None and tbl_name != expected_table_name:
                    raise SqlSafetyViolation(
                        f"step_1 must read from permitted Bronze table {req_bronze_schema}.{expected_table_name}, found: {tbl_schema}.{tbl_name}"
                    )
            else:
                # step_k (k >= 2) must reference unqualified step_{k-1} CTE
                prev_step_name = f"step_{i}"
                if tbl_schema is not None:
                    raise SqlSafetyViolation(
                        f"step_{i+1} must reference unqualified '{prev_step_name}', found schema-qualified reference '{tbl_schema}.{tbl_name}'"
                    )
                if tbl_name != prev_step_name:
                    raise SqlSafetyViolation(
                        f"step_{i+1} must read from {prev_step_name}, found: {tbl_name}"
                    )

        if not select_expr or not _is_select_like(select_expr):
            raise SqlSafetyViolation("Final query must be a SELECT statement.")

        select_body = select_expr.copy()
        select_body.set("with", None)

        from_clause = select_body.args.get("from")
        if not from_clause or not from_clause.this:
            raise SqlSafetyViolation("Final query must contain a FROM clause reading directly from final step CTE.")

        from_table = from_clause.this
        if not isinstance(from_table, exp.Table):
            raise SqlSafetyViolation("Final query FROM clause must directly reference the final step CTE table.")

        final_step_name = f"step_{len(ctes)}"
        from_catalog = from_table.args.get("catalog").name if from_table.args.get("catalog") else None
        from_schema = from_table.args.get("db").name if from_table.args.get("db") else None

        if from_catalog is not None:
            raise SqlSafetyViolation(f"Final SELECT table cannot be catalog-qualified, found: {from_catalog}")
        if from_schema is not None:
            raise SqlSafetyViolation(
                f"Final SELECT must reference unqualified step CTE '{final_step_name}', found schema-qualified reference '{from_schema}.{from_table.name}'"
            )
        if from_table.name != final_step_name:
            raise SqlSafetyViolation(
                f"Final SELECT must read from final step '{final_step_name}', found: {from_table.name}"
            )

        if select_body.args.get("joins"):
            raise SqlSafetyViolation("Final query must not contain JOINs.")
        if list(select_body.find_all(exp.Subquery)):
            raise SqlSafetyViolation("Final query must not contain subqueries.")

        all_main_tables = list(select_body.find_all(exp.Table))
        if len(all_main_tables) != 1:
            raise SqlSafetyViolation("Final query must reference only the final step CTE.")

    return stmt.sql(dialect="postgres")


def _validated_authority_identifier(value: str, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or not _IDENTIFIER_RE.fullmatch(value)
        or len(value.encode("utf-8")) > POSTGRES_IDENTIFIER_MAX_BYTES
    ):
        raise SqlSafetyViolation(f"{field} is not a safe PostgreSQL identifier.")
    return value

def execute_candidate_sql(
    sql_str: str,
    conn,
    expected_schema: str,
    run_id: str | None = None,
    expected_table_name: str | None = None,
    expected_bronze_schema: str | None = None,
    mode: str = "generic",
) -> None:
    """Execute LLM-generated SQL and immediately transfer ownership of the created candidate table."""
    import psycopg.sql as psql
    
    # 1. Validate the SQL (will raise SqlSafetyViolation if malicious/invalid)
    validated_sql = validate_generated_sql(
        sql_str,
        expected_schema=expected_schema,
        expected_table_name=expected_table_name,
        expected_bronze_schema=expected_bronze_schema,
        run_id=run_id,
        mode=mode,
    )
    
    # 2. Extract target table and schema for the ALTER statement
    stmt = sqlglot.parse_one(validated_sql, read="postgres")
    
    if isinstance(stmt, exp.Create):
        this = stmt.args.get("this")
        target_schema = this.args.get("db").name
        target_table = this.name
    else:
        # If it's just a SELECT (which is allowed by validate_generated_sql for preview),
        # we don't have a table to hand off.
        with conn.cursor() as cur:
            cur.execute(validated_sql)
        return

    from src.db_config import postgres_promotion_conninfo
    from src.promotion import discard_candidate_table

    with conn.cursor() as cur:
        # Check if candidate table already exists (e.g. from a prior failed execution attempt)
        cur.execute(
            "SELECT to_regclass(%s)",
            (f'"{target_schema}"."{target_table}"',)
        )
        if cur.fetchone()[0] is not None:
            # Safely drop stale candidate table using trusted promotion role
            discard_candidate_table(target_table, target_schema, postgres_promotion_conninfo())

        # Execute the validated LLM statement to create the table
        cur.execute(validated_sql)
        # Immediately transfer ownership to aurum_promotion
        cur.execute(psql.SQL("ALTER TABLE {}.{} OWNER TO aurum_promotion").format(
            psql.Identifier(target_schema), psql.Identifier(target_table)
        ))

    # Grant SELECT on candidate table to aurum_generated_sql so it can preview before promotion
    import psycopg
    with psycopg.connect(postgres_promotion_conninfo()) as p_conn:
        with p_conn.cursor() as p_cur:
            p_cur.execute(psql.SQL("GRANT SELECT ON {}.{} TO aurum_generated_sql").format(
                psql.Identifier(target_schema), psql.Identifier(target_table)
            ))
