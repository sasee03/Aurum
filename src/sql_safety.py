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

_FORBIDDEN_FUNCTIONS = frozenset({
    # Session / Runtime configuration & role switching
    "set_config",
    "current_setting",
    "set_user",
    "set_session_authorization",
    "reset_session_authorization",
})

_ALLOWED_FUNCTION_CLASSES: tuple[type[exp.Expression], ...] = (
    # Aggregates
    exp.Sum,
    exp.Count,
    exp.Avg,
    exp.Min,
    exp.Max,
    exp.Stddev,
    exp.Variance,
    # Logic / Nulls / Conditionals
    exp.Coalesce,
    exp.Nullif,
    exp.If,
    exp.Case,
    exp.Least,
    exp.Greatest,
    exp.Exists,
    # Strings
    exp.Lower,
    exp.Upper,
    exp.Concat,
    exp.Substring,
    exp.Trim,
    exp.Replace,
    exp.Length,
    exp.StrPosition,
    # Math
    exp.Round,
    exp.Abs,
    exp.Ceil,
    exp.Floor,
    exp.Sqrt,
    exp.Log,
    exp.Exp,
    exp.Mod,
    # Date / Time
    exp.Extract,
    exp.TimestampTrunc,
    exp.DateTrunc,
    exp.CurrentTimestamp,
    exp.CurrentDate,
    exp.CurrentTime,
    exp.DateAdd,
    exp.DateSub,
    exp.DateDiff,
    exp.TimeToStr,
    exp.StrToTime,
    exp.Date,
    # Conversion / Casting
    exp.Cast,
    exp.TryCast,
    # Window functions
    exp.RowNumber,
    exp.Lag,
    exp.Lead,
    exp.FirstValue,
    exp.LastValue,
)

_ALLOWED_ANONYMOUS_FUNCTIONS: frozenset[str] = frozenset({
    "sum",
    "count",
    "avg",
    "min",
    "max",
    "coalesce",
    "nullif",
    "round",
    "lower",
    "upper",
    "length",
    "concat",
    "substring",
    "trim",
    "ltrim",
    "rtrim",
    "replace",
    "abs",
    "ceil",
    "floor",
    "sqrt",
    "power",
    "log",
    "exp",
    "extract",
    "date_trunc",
    "now",
    "current_timestamp",
    "current_date",
    "current_time",
    "row_number",
    "rank",
    "dense_rank",
    "ntile",
    "lag",
    "lead",
    "first_value",
    "last_value",
    "cast",
    "try_cast",
    "least",
    "greatest",
    "stddev",
    "variance",
    "median",
    "mode",
    "percentile_cont",
    "percentile_disc",
    "to_char",
    "to_date",
    "to_timestamp",
    "to_number",
    "split_part",
})


_ALLOWED_CAST_TYPES = frozenset({
    exp.DataType.Type.SMALLINT,
    exp.DataType.Type.INT,
    exp.DataType.Type.BIGINT,
    exp.DataType.Type.DECIMAL,
    exp.DataType.Type.FLOAT,
    exp.DataType.Type.DOUBLE,
    exp.DataType.Type.TEXT,
    exp.DataType.Type.VARCHAR,
    exp.DataType.Type.CHAR,
    exp.DataType.Type.BOOLEAN,
    exp.DataType.Type.DATE,
    exp.DataType.Type.TIMESTAMP,
    exp.DataType.Type.TIMESTAMPTZ,
    exp.DataType.Type.TIME,
    exp.DataType.Type.INTERVAL,
    exp.DataType.Type.JSON,
    exp.DataType.Type.JSONB,
    exp.DataType.Type.UUID,
})


_ALLOWED_CATALOG_TYPES = frozenset({
    "int2",
    "int4",
    "int8",
    "numeric",
    "float4",
    "float8",
    "text",
    "varchar",
    "bpchar",
    "bool",
    "date",
    "timestamp",
    "timestamptz",
    "time",
    "timetz",
    "interval",
    "json",
    "jsonb",
    "uuid",
})


def get_referenced_physical_columns(stmt: exp.Expression, approved_sources: tuple[tuple[str, str], ...]) -> dict[tuple[str, str], set[str]]:
    """Extract physical source columns referenced in the query mapped by (schema, table)."""
    sources_map = {(schema.lower(), table.lower()): (schema, table) for schema, table in approved_sources}
    result: dict[tuple[str, str], set[str]] = {src: set() for src in sources_map.values()}

    for node in stmt.walk():
        if isinstance(node, exp.Star):
            for src in result:
                result[src].add("*")
        elif isinstance(node, exp.Column):
            col_name = node.name.lower() if node.name else None
            tbl_name = node.table.lower() if node.table else None
            db_name = node.db.lower() if node.db else None

            if db_name and tbl_name:
                key = (db_name, tbl_name)
                if key in sources_map:
                    result[sources_map[key]].add(col_name if col_name else "*")
            elif len(result) == 1:
                single_src = list(result.keys())[0]
                result[single_src].add(col_name if col_name else "*")
            else:
                for src in result:
                    result[src].add(col_name if col_name else "*")

    for src in result:
        if not result[src]:
            result[src].add("*")

    return result


def validate_catalog_source_types(cursor, physical_relations: Any) -> None:
    """Validate catalog type capabilities of physical source relations in PostgreSQL.

    Queries pg_attribute, pg_type, pg_namespace under relation lock.
    Enforces that ALL non-dropped user columns on EACH physical relation used by the SQL
    resolve to allowed pg_catalog built-in base types.
    Fails closed on custom domains, enums, composites, ranges, or unapproved types.
    """
    if isinstance(physical_relations, dict):
        relations = list(physical_relations.keys())
    else:
        relations = list(physical_relations)

    for (schema_name, table_name) in relations:
        cursor.execute(
            """
            SELECT
                a.attname,
                t.typname,
                n.nspname AS type_nspname,
                t.typtype,
                t.oid AS type_oid
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n_tbl ON n_tbl.oid = c.relnamespace
            JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
            JOIN pg_catalog.pg_type t ON t.oid = a.atttypid
            JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace
            WHERE n_tbl.nspname = %s AND c.relname = %s AND a.attnum > 0 AND NOT a.attisdropped
            """,
            (schema_name, table_name),
        )
        rows = cursor.fetchall()
        if not rows:
            raise SqlSafetyViolation(f"Physical source table {schema_name}.{table_name} missing from catalog.")

        found_cols: dict[str, tuple[str, str, str]] = {}
        for row in rows:
            attname = str(row[0])
            typname = str(row[1])
            type_nspname = str(row[2])
            typtype = row[3].decode("utf-8") if isinstance(row[3], bytes) else str(row[3])
            found_cols[attname.lower()] = (typname.lower(), type_nspname.lower(), typtype.lower())

        for col, (typname, type_nspname, typtype) in found_cols.items():
            if type_nspname != "pg_catalog":
                raise SqlSafetyViolation(
                    f"Physical source column '{col}' in {schema_name}.{table_name} uses non-pg_catalog type "
                    f"'{type_nspname}.{typname}'. Custom source types are forbidden."
                )

            if typtype != "b":
                raise SqlSafetyViolation(
                    f"Physical source column '{col}' in {schema_name}.{table_name} uses non-base type "
                    f"'{typname}' (typtype='{typtype}'). Domains, enums, composites, and ranges are forbidden."
                )

            if typname not in _ALLOWED_CATALOG_TYPES:
                raise SqlSafetyViolation(
                    f"Physical source column '{col}' in {schema_name}.{table_name} uses unapproved built-in type "
                    f"'{typname}'. Fail closed."
                )



def _validate_no_unsafe_functions(stmt: exp.Expression) -> None:
    if list(stmt.find_all(exp.Set)):
        raise SqlSafetyViolation("Generated SQL cannot contain SET statements.")

    for node in stmt.walk():
        if isinstance(node, exp.Operator):
            raise SqlSafetyViolation("Explicit PostgreSQL OPERATOR(...) syntax is forbidden.")

        if isinstance(node, exp.Dot):
            if isinstance(node.expression, (exp.Func, exp.Anonymous)) or isinstance(node.this, (exp.Func, exp.Anonymous)):
                raise SqlSafetyViolation("Schema-qualified function calls are forbidden.")

        if isinstance(node, (exp.Cast, exp.TryCast)):
            dt = node.to
            if not isinstance(dt, exp.DataType):
                raise SqlSafetyViolation("Invalid cast target expression.")
            if dt.args.get("kind") is not None:
                raise SqlSafetyViolation("Schema-qualified or custom cast types are forbidden.")
            if dt.this not in _ALLOWED_CAST_TYPES:
                raise SqlSafetyViolation(f"Cast target type '{dt.sql('postgres')}' is forbidden or unclassified.")

        if isinstance(node, exp.Func):
            if isinstance(node, exp.Anonymous):
                name = node.this if isinstance(node.this, str) else str(node.this)
                name_clean = name.strip().lower()
                if name_clean not in _ALLOWED_ANONYMOUS_FUNCTIONS:
                    raise SqlSafetyViolation(
                        f"Generated SQL contains unclassified or forbidden function: {name_clean}"
                    )
            else:
                if not isinstance(node, _ALLOWED_FUNCTION_CLASSES):
                    raise SqlSafetyViolation(
                        f"Generated SQL contains forbidden or unclassified function node: {type(node).__name__}"
                    )
            if node.args.get("db") is not None or node.args.get("catalog") is not None:
                raise SqlSafetyViolation("Schema-qualified functions are forbidden.")



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
) -> tuple[tuple[str, str], ...]:
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

    return tuple(sorted(physical_sources))


def extract_gold_physical_sources(
    sql_str: str,
    *,
    selected_sources: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    """Parse and return the exact physical used Gold source relations from AST validation."""
    statements = sqlglot.parse(sql_str, read="postgres")
    if not statements or not statements[0]:
        raise SqlSafetyViolation("Empty SQL statement.")
    stmt = statements[0]
    expression = stmt.args.get("expression")
    if not expression:
        raise SqlSafetyViolation("Gold SQL missing SELECT body.")
    return _validate_gold_sources(expression, selected_sources=selected_sources)



def validate_generated_sql(
    sql_str: str,
    *,
    expected_schema: str,
    expected_table_name: str | None = None,
    expected_bronze_schema: str | None = None,
    expected_bronze_table_name: str | None = None,
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

    _validate_no_unsafe_functions(stmt)

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
                required_bronze_table = (
                    expected_bronze_table_name or expected_table_name
                )
                if (
                    required_bronze_table is not None
                    and tbl_name != required_bronze_table
                ):
                    raise SqlSafetyViolation(
                        f"step_1 must read from permitted Bronze table {req_bronze_schema}.{required_bronze_table}, found: {tbl_schema}.{tbl_name}"
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
    expected_bronze_table_name: str | None = None,
    mode: str = "generic",
    expected_bronze_identity: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Execute LLM-generated SQL and immediately transfer ownership of the created candidate table."""
    import psycopg.sql as psql
    from src.db_config import get_promotion_pool

    # 1. Validate the SQL (will raise SqlSafetyViolation if malicious/invalid)
    validated_sql = validate_generated_sql(
        sql_str,
        expected_schema=expected_schema,
        expected_table_name=expected_table_name,
        expected_bronze_schema=expected_bronze_schema,
        expected_bronze_table_name=expected_bronze_table_name,
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
        return None

    if mode == "p2_silver":
        if not expected_bronze_identity:
            raise SqlSafetyViolation("Silver transformation requires pre-bound 6-field Bronze physical source identity.")

    with get_promotion_pool().connection() as p_conn:
        with p_conn.transaction():
            with p_conn.cursor() as p_cur:
                # Check if candidate table already exists — FAIL CLOSED on collision
                p_cur.execute(
                    "SELECT to_regclass(%s)",
                    (f'"{target_schema}"."{target_table}"',)
                )
                if p_cur.fetchone()[0] is not None:
                    raise SqlSafetyViolation(
                        f"Candidate table {target_schema}.{target_table} already exists."
                    )

                # Lock Bronze source table & validate whole-relation catalog types under lock
                req_bronze_schema = expected_bronze_schema or "bronze"
                req_bronze_table = (
                    expected_bronze_table_name
                    or expected_table_name
                    or target_table.replace(
                        f"_candidate_{run_id}" if run_id else "_candidate_",
                        "",
                    )
                )
                p_cur.execute(
                    psql.SQL("LOCK TABLE {}.{} IN ACCESS SHARE MODE").format(
                        psql.Identifier(req_bronze_schema), psql.Identifier(req_bronze_table)
                    )
                )
                from src.promotion import resolve_relation_identity
                live_bronze = resolve_relation_identity(p_conn, req_bronze_schema, req_bronze_table)
                if live_bronze is None:
                    raise SqlSafetyViolation(f"Source relation {req_bronze_schema}.{req_bronze_table} not found.")

                if mode == "p2_silver" and expected_bronze_identity:
                    for k in ("database_oid", "namespace_oid", "relation_oid", "schema", "relation_name", "relation_kind"):
                        if expected_bronze_identity.get(k) != live_bronze.get(k):
                            raise SqlSafetyViolation(
                                f"Bronze source relation identity mismatch on key '{k}': live={live_bronze.get(k)} vs expected={expected_bronze_identity.get(k)}."
                            )

                validate_catalog_source_types(p_cur, ((req_bronze_schema, req_bronze_table),))

                p_cur.execute("SELECT pg_catalog.set_config(%s, %s, true)", ("search_path", "pg_catalog"))
                p_cur.execute("SET LOCAL ROLE aurum_generated_sql")
                p_cur.execute(validated_sql)

                # Revert role to session_user (aurum_promotion) for single-transaction ownership handoff
                p_cur.execute("RESET ROLE")
                p_cur.execute(psql.SQL("ALTER TABLE {}.{} OWNER TO aurum_promotion").format(
                    psql.Identifier(target_schema), psql.Identifier(target_table)
                ))
                p_cur.execute(psql.SQL("GRANT SELECT ON {}.{} TO aurum_generated_sql").format(
                    psql.Identifier(target_schema), psql.Identifier(target_table)
                ))

                p_cur.execute(
                    """
                    SELECT c.oid, n.oid, c.relname, n.nspname, c.relkind, (SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database())
                    FROM pg_catalog.pg_class c
                    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = %s AND c.relname = %s
                    """,
                    (target_schema, target_table),
                )
                row = p_cur.fetchone()
                if not row:
                    raise SqlSafetyViolation(f"Candidate table {target_schema}.{target_table} relation resolution failed.")

                return {
                    "relation_oid": int(row[0]),
                    "namespace_oid": int(row[1]),
                    "relation_name": str(row[2]),
                    "schema": str(row[3]),
                    "relation_kind": row[4].decode("utf-8") if isinstance(row[4], bytes) else str(row[4]),
                    "database_oid": int(row[5]) if row[5] is not None else 0,
                }
