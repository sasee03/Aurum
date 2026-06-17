# Integration & Reliability Track

The Integration Lead validates and connects the product. He does not own the anomaly engine, root-cause engine, verdict engine, baseline engine, impact engine, dashboard design, demo narration, or product positioning.

## Ownership

Prakhar builds the decision. Haasya builds the proof and experience. The Integration Lead makes sure the whole product runs, validates, and survives the demo.

## Authority Direction

- Prakhar owns the contract definition.
- Integration Lead owns conformance to the contract.
- When a mismatch appears, ask which side disagrees with the frozen contract.
- Do not rename fields or change schema without Prakhar and Haasya approval.
- If a number is wrong, report it. Do not hardcode it.

## Daily Validation

Run from the project root:

```powershell
python verify_demo.py
python run_demo.py
streamlit run streamlit_app.py
```

The verifier checks:

- contract fields and block keys
- Bronze 100,000, correct Silver 96,000, buggy Silver 72,000
- 28% today drop and learned normal range 3.71%-3.91%
- expected revenue Rs 10.18 Cr, actual revenue Rs 9.70 Cr, impact Rs 0.48 Cr
- root cause derives 24,000 dropped discounted orders
- evidence SQLs run and reproduce their displayed results
- dashboard reads `reports/report.json` instead of hardcoding demo values

## Daily Update Format

```text
Integration & Reliability Update
Tested:
Contract Issues:
Number Validation:
Evidence QA:
Bugs Found:
Screenshots / Notes:
Need from Prakhar:
Need from Haasya:
Tomorrow:
```

## Demo Readiness Checklist

- Backend emits `reports/report.json`.
- Dashboard loads the same JSON.
- Evidence table is visible without scrolling too much.
- Verdict can be explained in one breath.
- Root cause can be shown from a real table diff.
- Screenshots are captured before demo day.
- Backup terminal command is ready: `python verify_demo.py`.

## Scalability Q&A Notes

- DuckDB is fine for the MVP because it gives local, deterministic SQL over CSVs without infrastructure delay.
- In production, the same checks can run after Airflow or dbt jobs.
- Warehouse targets can be Snowflake, BigQuery, Databricks, or Postgres because the contract boundary is JSON.
- Policy thresholds can move into YAML once the demo rules stabilize.
- Kafka, Kubernetes, and API gateways are roadmap items, not MVP dependencies.

