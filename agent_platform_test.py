import requests
import json
import sys

BASE_URL = "http://localhost:8011"

print("==================================================")
print("AURUM AGENT END-TO-END PLATFORM TEST")
print("==================================================")

# 1. Health Check
print("\n[1/5] Checking API & Database Health...")
r = requests.get(f"{BASE_URL}/health")
assert r.status_code == 200, f"Health check failed: {r.text}"
print(f"[OK] Health OK: {r.json()}")

# 2. Check Silver Tables Availability
print("\n[2/5] Fetching Silver relations for Gold curation...")
r = requests.get(f"{BASE_URL}/api/v1/gold/silver-tables")
assert r.status_code == 200, f"Silver tables call failed: {r.text}"
tables = r.json().get("tables", [])
print(f"[OK] Available Silver relations ({len(tables)}): {[t['name'] for t in tables]}")
silver_table = tables[0]["name"] if tables else "orders"

# 3. Test Various Business Intent & Rules against Gold AI
test_cases = [
    {
        "intent": "Calculate total revenue by country",
        "target": "gold_country_revenue",
        "source": silver_table,
    },
    {
        "intent": "Find total sales quantity per product category",
        "target": "gold_product_quantity",
        "source": silver_table,
    },
    {
        "intent": "Calculate average order value by customer",
        "target": "gold_customer_aov",
        "source": silver_table,
    },
]

print("\n[3/5] Testing Gold AI Curation Engine with custom Business Intents & Rules...")
promoted_runs = []

for idx, test_case in enumerate(test_cases, 1):
    print(f"\n  --- Test Case {idx}: Intent = '{test_case['intent']}' ---")
    import time
    time.sleep(2)
    payload = {
        "source": {"schema": "silver", "table": test_case["source"]},
        "target_table_name": test_case["target"],
        "business_requirement": test_case["intent"]
    }
    
    # AI Generate with retry for API rate limits
    r = None
    for attempt in range(5):
        time.sleep(3)
        r = requests.post(f"{BASE_URL}/api/v1/gold/ai/generate", json=payload)
        if r.status_code == 200:
            break
        print(f"    [Retry {attempt+1}/5] Status {r.status_code}: {r.text[:80]}")

    print(f"  [Generate AI] Status: {r.status_code}")
    assert r.status_code == 200, f"Gold AI Generate failed: {r.text}"
    gen_data = r.json()
    run_id = gen_data["run_id"]
    verdict = gen_data.get("verdict")
    ai_interp = gen_data.get("ai_interpretation")
    print(f"  [OK] Run ID: {run_id}")
    print(f"  [OK] Verdict: {verdict}")
    print(f"  [OK] Interpretation: {json.dumps(ai_interp, indent=2)}")
    
    # Review
    r = requests.get(f"{BASE_URL}/api/v1/gold/review/{run_id}")
    assert r.status_code == 200, f"Gold Review failed: {r.text}"
    review_data = r.json()
    print(f"  [OK] Review SQL Generated: {review_data['sql_text'][:80]}...")
    
    # Approve
    # Check if target table exists in gold schema
    gold_tables_resp = requests.get(f"{BASE_URL}/api/v1/gold/gold-tables").json()
    existing_gold_names = [t["name"] for t in gold_tables_resp.get("tables", [])]
    target_exists = test_case["target"] in existing_gold_names
    
    approve_payload = {
        "review_revision": review_data["review_revision"],
        "overwrite": target_exists
    }
    r = requests.post(f"{BASE_URL}/api/v1/gold/approve/{run_id}", json=approve_payload)
    assert r.status_code == 200, f"Gold Approve failed: {r.text}"
    approve_data = r.json()
    print(f"  [OK] Approved Revision: {approve_data['approved_revision']}")
    
    # Execute
    exec_payload = {"overwrite": approve_data["overwrite_authorized"]}
    r = requests.post(f"{BASE_URL}/api/v1/gold/execute/{run_id}", json=exec_payload)
    assert r.status_code == 200, f"Gold Execute failed: {r.text}"
    print(f"  [OK] Execution Claim ID: {r.json()['execution_claim_id']}")
    
    # Promote
    r = requests.post(f"{BASE_URL}/api/v1/gold/promote/{run_id}")
    assert r.status_code == 200, f"Gold Promote failed: {r.text}"
    print(f"  [OK] Promoted to Live Gold Relation: {r.json()['target']}")
    promoted_runs.append((test_case["target"], run_id))

# 4. Verify Live Gold Tables & Data Preview
print("\n[4/5] Verifying Live Gold Data Product Tables & Preview...")
r = requests.get(f"{BASE_URL}/api/v1/gold/gold-tables")
assert r.status_code == 200, f"Gold tables call failed: {r.text}"
gold_tables = [t["name"] for t in r.json().get("tables", [])]
print(f"[OK] Discovered Live Gold Tables: {gold_tables}")

for target_name, r_id in promoted_runs:
    r = requests.get(f"{BASE_URL}/metadata/tables/{target_name}/preview?schema=gold")
    if r.status_code == 200:
        p_data = r.json()
        print(f"[OK] Preview {target_name}: {len(p_data.get('rows', []))} rows returned.")

# 5. Test Grounded Aurum Assistant
print("\n[5/5] Testing Grounded Aurum Assistant Chat...")
assistant_payload = {
    "message": "What is the status of the Gold business pipeline?",
    "run_id": promoted_runs[0][1] if promoted_runs else None
}
r = requests.post(f"{BASE_URL}/api/v1/assistant/chat", json=assistant_payload)
assert r.status_code == 200, f"Assistant chat failed: {r.text}"
chat_resp = r.json()
print(f"[OK] Assistant Response Status: {chat_resp.get('status')}")
print(f"[OK] Grounded Evidence: {chat_resp.get('evidence')}")
print(f"[OK] Rendered Answer:\n{chat_resp.get('answer')}")

print("\n==================================================")
print("ALL AGENT PLATFORM TESTS PASSED SUCCESSFULLY! (100%)")
print("==================================================")
