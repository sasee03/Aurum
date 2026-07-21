"""Unit tests for AST structural safety gate."""

import pytest
from src.sql_safety import validate_generated_sql as _validate_generated_sql, SqlSafetyViolation
from src.db_config import load_layer_schemas

schemas = load_layer_schemas()

def validate_generated_sql(sql_str: str, **kwargs):
    kwargs.setdefault('expected_schema', schemas.silver_candidates)
    return _validate_generated_sql(sql_str, **kwargs)


RUN_ID = "run_20260721"


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
