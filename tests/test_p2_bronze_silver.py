from fastapi.testclient import TestClient
from api.main import app

def test_p2_bronze_to_silver_pipeline():
    client = TestClient(app)
    base_url = "/api/v1/transform"
    table_name = "src_orders_test"
    
    # 1. Provide Rules
    print("1. Submitting Rules...")
    resp = client.post(f"{base_url}/rules", json={
        "table_name": table_name,
        "rules": [
            "Remove orders where total_amount is less than 0.",
            "Uppercase the status column.",
            "Remove orders where customer_id is null."
        ]
    })
    resp.raise_for_status()
    print("   Rules submitted successfully.\n")

    # 2. Generate SQL (using stub)
    print("2. Generating SQL...")
    resp = client.post(f"{base_url}/generate", json={
        "table_name": table_name
    })
    resp.raise_for_status()
    gen_data = resp.json()
    run_id = gen_data["run_id"]
    print(f"   Generated SQL with run_id: {run_id}\n")

    # 3. Review SQL
    print("3. Reviewing Planned Changes...")
    resp = client.get(f"{base_url}/review/{run_id}")
    resp.raise_for_status()
    review_data = resp.json()
    print("   Planned Summary:")
    print("   " + review_data["planned_changes"]["summary"])
    print("   SQL:")
    print("   " + review_data["sql_text"].replace("\n", "\n   ") + "\n")

    # 4. Execute and Promote
    print("4. Executing and Promoting...")
    resp = client.post(f"{base_url}/execute/{run_id}")
    if resp.status_code != 200:
        print(f"Error {resp.status_code}: {resp.text}")
    resp.raise_for_status()
    exec_data = resp.json()
    
    print("   Execution Successful!")
    print("   Attribution Log:")
    for log_entry in exec_data["attribution_log"]:
        print("     " + log_entry)
        
    # Check if table exists in silver schema
    import psycopg
    from src.db_config import postgres_conninfo
    
    with psycopg.connect(postgres_conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM silver.src_orders_test")
            silver_count = cur.fetchone()[0]
            print(f"   Final Silver Table Count: {silver_count}")
            assert silver_count == 3

