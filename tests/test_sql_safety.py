"""Unit tests for AST structural safety gate."""

import pytest
import src.sql_safety as sql_safety
from src.sql_safety import validate_generated_sql as _validate_generated_sql, SqlSafetyViolation
from src.db_config import load_layer_schemas

schemas = load_layer_schemas()

def validate_generated_sql(sql_str: str, **kwargs):
    kwargs.setdefault('expected_schema', schemas.silver_candidates)
    return _validate_generated_sql(sql_str, **kwargs)


RUN_ID = "run_20260721"


def test_generic_validation_does_not_load_current_layer_config(monkeypatch):
    calls = {"count": 0}

    def unavailable_config():
        calls["count"] += 1
        pytest.fail("generic structural validation must not load layer config")

    monkeypatch.setattr(
        sql_safety,
        "load_layer_schemas",
        unavailable_config,
        raising=False,
    )
    sql = (
        f"CREATE TABLE {schemas.silver_candidates}."
        f"orders_candidate_{RUN_ID} AS SELECT * FROM bronze.orders"
    )
    result = validate_generated_sql(
        sql,
        expected_table_name="orders",
        run_id=RUN_ID,
    )
    assert "CREATE TABLE" in result
    assert calls["count"] == 0


def test_valid_select_query():
    sql = "SELECT id, amount FROM bronze.users WHERE amount > 0;"
    result = validate_generated_sql(sql)
    assert "SELECT" in result

def test_valid_ctas_query():
    sql = f"CREATE TABLE silver_candidates.my_candidate_{RUN_ID} AS SELECT * FROM bronze.orders;"
    result = validate_generated_sql(sql, run_id=RUN_ID)
    assert "CREATE TABLE" in result
    assert f"my_candidate_{RUN_ID}" in result

def test_ctas_with_chained_ctes():
    sql = f"""
    CREATE TABLE silver_candidates.complex_candidate_{RUN_ID} AS
    WITH step_1 AS (SELECT * FROM a),
         step_2 AS (SELECT * FROM step_1)
    SELECT * FROM step_2;
    """
    result = validate_generated_sql(sql, run_id=RUN_ID)
    assert "CREATE TABLE" in result

def test_reject_multiple_statements():
    sql = "SELECT * FROM a; SELECT * FROM b;"
    with pytest.raises(SqlSafetyViolation, match="Only exactly one SQL statement is allowed"):
        validate_generated_sql(sql)

def test_reject_bare_create_table():
    sql = f"CREATE TABLE silver.test_candidate_{RUN_ID} (id INT);"
    with pytest.raises(SqlSafetyViolation, match="CREATE TABLE must have an AS SELECT body"):
        validate_generated_sql(sql, run_id=RUN_ID)

def test_reject_create_non_candidate():
    sql = "CREATE TABLE silver_orders AS SELECT * FROM bronze;"
    with pytest.raises(SqlSafetyViolation, match="Generated tables must be named"):
        validate_generated_sql(sql, run_id=RUN_ID)

def test_reject_candidate_for_wrong_run():
    sql = "CREATE TABLE silver.orders_candidate_other AS SELECT * FROM bronze.orders;"
    with pytest.raises(SqlSafetyViolation, match="must end with"):
        validate_generated_sql(sql, run_id=RUN_ID)

def test_reject_ctas_to_source_schema():
    sql = f"CREATE TABLE source.orders_candidate_{RUN_ID} AS SELECT * FROM bronze.orders;"
    with pytest.raises(SqlSafetyViolation, match="Target schema must be"):
        validate_generated_sql(sql, run_id=RUN_ID)

def test_reject_ctas_to_bronze_schema():
    sql = f"CREATE TABLE bronze.orders_candidate_{RUN_ID} AS SELECT * FROM bronze.orders;"
    with pytest.raises(SqlSafetyViolation, match="Target schema must be"):
        validate_generated_sql(sql, run_id=RUN_ID)

def test_reject_drop_operation():
    sql = "DROP TABLE users;"
    with pytest.raises(SqlSafetyViolation, match="Statement must be SELECT or CREATE TABLE AS"):
        validate_generated_sql(sql)

def test_reject_drop_inside_cte():
    sql = "WITH step AS (DROP TABLE users) SELECT * FROM step;"
    with pytest.raises(SqlSafetyViolation, match="Forbidden operation found: Drop"):
        validate_generated_sql(sql)

def test_reject_delete_operation():
    sql = "DELETE FROM users WHERE id=1;"
    with pytest.raises(SqlSafetyViolation):
        validate_generated_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE silver.orders SET id = 1",
        "TRUNCATE TABLE bronze.orders",
        "ALTER TABLE silver.orders ADD COLUMN x INT",
        "GRANT SELECT ON silver.orders TO public",
        "COPY silver.orders TO '/tmp/orders.csv'",
        "INSERT INTO silver.orders VALUES (1)",
        "WITH x AS (SELECT 1) DELETE FROM silver.orders",
        "SELECT 1; DROP TABLE bronze.orders",
        "SELECT 1 -- ; DROP TABLE bronze.orders",
        "SELECT 1 /* */",
        "DO $$ BEGIN RAISE NOTICE 'x'; END $$",
        "CALL refresh_silver()",
        "SELECT * INTO silver.orders_candidate_run_20260721 FROM bronze.orders",
        "CREATE TABLE IF NOT EXISTS silver.orders_candidate_run_20260721 AS SELECT * FROM bronze.orders",
    ],
)
def test_reject_malicious_or_invalid_inputs(sql):
    with pytest.raises(SqlSafetyViolation):
        validate_generated_sql(sql, run_id=RUN_ID)


def _validate_gold(sql: str, *, sources=("orders", "customers", "items")):
    return _validate_generated_sql(
        sql,
        expected_schema="gold_work",
        expected_table_name="business_output",
        expected_candidate_name="business_output_candidate_run_gold",
        run_id="run_gold",
        mode="gold_ctas",
        selected_sources=tuple(("curated", table) for table in sources),
    )


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM curated.orders",
        (
            "SELECT o.* FROM curated.orders o "
            "JOIN curated.customers c ON c.id = o.customer_id"
        ),
        (
            "SELECT o.id FROM curated.orders o "
            "JOIN curated.customers c ON c.id = o.customer_id "
            "JOIN curated.items i ON i.order_id = o.id"
        ),
        (
            "SELECT customer_id, COUNT(*) AS n FROM curated.orders "
            "GROUP BY customer_id"
        ),
        (
            "SELECT id, ROW_NUMBER() OVER (ORDER BY id) AS n "
            "FROM curated.orders"
        ),
        (
            "SELECT CASE WHEN id > 0 THEN 1 ELSE 0 END AS bucket "
            "FROM curated.orders"
        ),
        (
            "SELECT * FROM curated.orders o WHERE EXISTS "
            "(SELECT 1 FROM curated.customers c WHERE c.id = o.customer_id)"
        ),
        (
            "WITH first AS (SELECT * FROM curated.orders), "
            "second AS (SELECT * FROM first) SELECT * FROM second"
        ),
        (
            "WITH orders AS (SELECT * FROM curated.orders) "
            "SELECT * FROM orders"
        ),
        (
            "WITH scoped AS (SELECT * FROM curated.orders) "
            "SELECT * FROM (WITH scoped AS "
            "(SELECT * FROM curated.customers) SELECT * FROM scoped) nested "
            "JOIN scoped outer_scope ON true"
        ),
    ],
)
def test_gold_ctas_allows_business_queries_with_lexical_cte_scopes(query):
    sql = (
        "CREATE TABLE gold_work.business_output_candidate_run_gold AS "
        f"{query}"
    )
    assert _validate_gold(sql).startswith("CREATE TABLE")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM curated.orders",
        (
            "CREATE TABLE gold_work.wrong_candidate_run_gold AS "
            "SELECT * FROM curated.orders"
        ),
        (
            "CREATE TABLE other.business_output_candidate_run_gold AS "
            "SELECT * FROM curated.orders"
        ),
        (
            "CREATE TABLE gold_work.business_output_candidate_run_gold AS "
            "SELECT * FROM curated.orders; SELECT 1"
        ),
        (
            "CREATE TEMP TABLE gold_work.business_output_candidate_run_gold AS "
            "SELECT * FROM curated.orders"
        ),
        (
            "CREATE UNLOGGED TABLE gold_work.business_output_candidate_run_gold AS "
            "SELECT * FROM curated.orders"
        ),
        (
            "CREATE TABLE IF NOT EXISTS "
            "gold_work.business_output_candidate_run_gold AS "
            "SELECT * FROM curated.orders"
        ),
        (
            "CREATE TABLE gold_work.business_output_candidate_run_gold AS "
            "SELECT * FROM curated.orders WITH NO DATA"
        ),
        (
            "CREATE TABLE gold_work.business_output_candidate_run_gold AS "
            "SELECT * INTO another_target FROM curated.orders"
        ),
        (
            "CREATE VIEW gold_work.business_output_candidate_run_gold AS "
            "SELECT * FROM curated.orders"
        ),
        (
            "CREATE MATERIALIZED VIEW "
            "gold_work.business_output_candidate_run_gold AS "
            "SELECT * FROM curated.orders"
        ),
        (
            "CREATE TABLE gold_work.business_output_candidate_run_gold AS "
            "WITH changed AS (DELETE FROM curated.orders RETURNING *) "
            "SELECT * FROM changed"
        ),
        (
            "CREATE TABLE gold_work.business_output_candidate_run_gold AS "
            "SELECT * FROM orders"
        ),
        (
            "CREATE TABLE gold_work.business_output_candidate_run_gold AS "
            "SELECT * FROM curated.unselected"
        ),
        (
            "CREATE TABLE gold_work.business_output_candidate_run_gold AS "
            "SELECT * FROM bronze.orders"
        ),
        (
            "CREATE TABLE gold_work.business_output_candidate_run_gold AS "
            "SELECT * FROM source.orders"
        ),
        (
            "CREATE TABLE gold_work.business_output_candidate_run_gold AS "
            "SELECT * FROM gold.orders"
        ),
        (
            "CREATE TABLE gold_work.business_output_candidate_run_gold AS "
            "SELECT * FROM gold_work.business_output_candidate_run_gold"
        ),
        (
            "CREATE TABLE gold_work.business_output_candidate_run_gold AS "
            "SELECT * FROM public.orders"
        ),
        (
            "CREATE TABLE gold_work.business_output_candidate_run_gold AS "
            "SELECT * FROM information_schema.tables"
        ),
        (
            "CREATE TABLE gold_work.business_output_candidate_run_gold AS "
            "SELECT * FROM pg_catalog.pg_class"
        ),
        (
            "CREATE TABLE gold_work.business_output_candidate_run_gold AS "
            "SELECT * FROM other_database.curated.orders"
        ),
        (
            "CREATE TABLE gold_work.business_output_candidate_run_gold AS "
            "SELECT o.* FROM curated.orders o "
            "CROSS JOIN LATERAL generate_series(1, 3) AS generated(value)"
        ),
        (
            "CREATE TABLE gold_work.business_output_candidate_run_gold AS "
            "SELECT evil.side_effect(id) FROM curated.orders"
        ),
        (
            "CREATE TABLE gold_work.business_output_candidate_run_gold AS "
            "SELECT o.* FROM curated.orders o "
            "CROSS JOIN LATERAL unnest(ARRAY[1, 2]) AS expanded(value)"
        ),
        (
            "CREATE TABLE gold_work.business_output_candidate_run_gold AS "
            "SELECT o.* FROM curated.orders o "
            "CROSS JOIN (VALUES (1)) AS values_source(id)"
        ),
        (
            "CREATE TABLE gold_work.business_output_candidate_run_gold AS "
            "WITH hidden AS (SELECT * FROM curated.unselected) "
            "SELECT * FROM hidden"
        ),
        (
            "CREATE TABLE gold_work.business_output_candidate_run_gold AS "
            "SELECT * FROM (SELECT * FROM curated.unselected) hidden"
        ),
    ],
)
def test_gold_ctas_rejects_non_contained_statement_or_source(sql):
    with pytest.raises(SqlSafetyViolation):
        _validate_gold(sql)


def test_gold_ctas_requires_quotes_for_case_sensitive_approved_identifier():
    unquoted = (
        "CREATE TABLE gold_work.business_output_candidate_run_gold AS "
        "SELECT * FROM curated.Orders"
    )
    with pytest.raises(SqlSafetyViolation):
        _validate_gold(unquoted, sources=("Orders",))

    quoted = (
        "CREATE TABLE gold_work.business_output_candidate_run_gold AS "
        'SELECT * FROM curated."Orders"'
    )
    assert _validate_gold(quoted, sources=("Orders",)).startswith("CREATE TABLE")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT nextval('seq') FROM curated.orders",
        "SELECT set_config('role', 'aurum_promotion', true) FROM curated.orders",
        "SELECT pg_advisory_lock(1) FROM curated.orders",
        "SELECT pg_read_file('/etc/passwd') FROM curated.orders",
        "SELECT pg_sleep(5) FROM curated.orders",
        "SELECT SUM(nextval('seq')) FROM curated.orders",
        "SELECT COALESCE(set_config('a', 'b', true), '0') FROM curated.orders",
        "SELECT public.custom_func(id) FROM curated.orders",
        "SELECT evil_func(id) FROM curated.orders",
    ],
)
def test_reject_unclassified_or_forbidden_functions(sql):
    ctas = f"CREATE TABLE gold_work.business_output_candidate_run_gold AS {sql}"
    with pytest.raises(SqlSafetyViolation):
        _validate_gold(ctas)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT SUM(amount), COUNT(*), AVG(amount), MIN(amount), MAX(amount) FROM curated.orders",
        "SELECT COALESCE(amount, 0), NULLIF(amount, 0), ROUND(amount, 2), LOWER(status), UPPER(status) FROM curated.orders",
        "SELECT EXTRACT(year FROM created_at), DATE_TRUNC('month', created_at), NOW(), CURRENT_TIMESTAMP FROM curated.orders",
        "SELECT CAST(id AS int), SUBSTRING(status, 1, 3), TRIM(status), ABS(amount) FROM curated.orders",
        "SELECT ROW_NUMBER() OVER (ORDER BY id), LAG(amount, 1) OVER () FROM curated.orders",
        "SELECT a + b, a - b, a * b, a / b, a = b, a < b, a > b FROM curated.orders",
        "SELECT id::integer, amount::numeric, status::varchar, created_at::timestamp FROM curated.orders",
    ],
)
def test_allow_analytical_functions(sql):
    ctas = f"CREATE TABLE gold_work.business_output_candidate_run_gold AS {sql}"
    assert _validate_gold(ctas).startswith("CREATE TABLE")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1 OPERATOR(public.+) 2 FROM curated.orders",
        "SELECT status::public.custom_type FROM curated.orders",
        "SELECT amount::custom_unclassified_type FROM curated.orders",
        "SELECT public.evil_func(id) FROM curated.orders",
        "SELECT CAST(id AS public.my_type) FROM curated.orders",
    ],
)
def test_reject_operator_and_custom_cast_bypasses(sql):
    ctas = f"CREATE TABLE gold_work.business_output_candidate_run_gold AS {sql}"
    with pytest.raises(SqlSafetyViolation):
        _validate_gold(ctas)


def test_validate_catalog_source_types_rejects_non_base_types():
    from src.sql_safety import validate_catalog_source_types, SqlSafetyViolation

    class MockCursor:
        def execute(self, query, params):
            pass
        def fetchall(self):
            # Return column 'status' as enum type (typtype='e')
            return [("status", "my_enum", "public", "e", 1234)]

    with pytest.raises(SqlSafetyViolation, match="non-pg_catalog type|non-base type"):
        validate_catalog_source_types(MockCursor(), {("bronze", "orders"): {"status"}})


def test_validate_catalog_source_types_allows_pg_catalog_base_types():
    from src.sql_safety import validate_catalog_source_types

    class MockCursor:
        def execute(self, query, params):
            pass
        def fetchall(self):
            # Return column 'id' as int4 (typtype='b', nspname='pg_catalog')
            return [("id", "int4", "pg_catalog", "b", 23)]

    # Should complete without error
    validate_catalog_source_types(MockCursor(), {("bronze", "orders"): {"id"}})
