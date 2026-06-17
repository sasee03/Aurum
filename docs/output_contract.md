# Aurum Output Contract

This is the frozen backend-to-dashboard contract for the MVP. Prakhar owns the contract definition. The Integration Lead owns conformance to this contract.

`run_demo.py` writes the live contract JSON to `reports/report.json`.

```json
{
  "run_id": "today",
  "profile": {
    "bronze_count": 100000,
    "silver_count": 72000,
    "drop_pct": 28.0
  },
  "baseline": {
    "normal_drop_pct": 3.81,
    "std_dev": 0.032,
    "lower_bound": 3.71,
    "upper_bound": 3.91,
    "method": "mean +/- 3 std"
  },
  "anomaly": {
    "is_anomaly": true,
    "drop_today": 28.0,
    "deviation_sigma": 755.9,
    "severity": "CRITICAL"
  },
  "root_cause": {
    "cause": "Silver transformation wrongly filtered valid discounted orders",
    "dropped_rows": 24000,
    "evidence_ref": "missing_discounted_orders"
  },
  "impact": {
    "expected_revenue_cr": 10.18,
    "actual_revenue_cr": 9.7,
    "impact_cr": 0.48,
    "risk_level": "HIGH"
  },
  "evidence": [
    {
      "name": "Bronze order count",
      "sql": "SELECT COUNT(*) FROM bronze_orders;",
      "result": "100,000 rows",
      "meaning": "Total orders ingested in the raw layer."
    },
    {
      "name": "Silver valid count (today)",
      "sql": "SELECT COUNT(*) FROM silver_orders_buggy;",
      "result": "72,000 rows",
      "meaning": "Valid orders surviving the Silver transformation today."
    },
    {
      "name": "Gold revenue delta",
      "sql": "SELECT SUM(net_amount) FROM silver_orders_buggy;",
      "result": "Rs 9.70 Cr",
      "meaning": "Today's Gold revenue vs Rs 10.18 Cr expected = Rs 0.48 Cr short."
    }
  ],
  "verdict": {
    "decision": "BLOCK PUBLISH",
    "reasons": [
      "Bronze->Silver drop 28% vs learned normal 3.81% (+/- 3 std)",
      "Gold revenue Rs 0.48 Cr below expected",
      "Finance Board Dashboard impacted"
    ],
    "suggested_action": "Review the Silver transformation filter. The likely issue is that valid discounted orders are being excluded by the condition is_discounted == 0."
  }
}
```

`deviation_sigma` is deliberately computed, not copied from a placeholder. With the current data it is `(28.00 - 3.81) / 0.032 = 755.9`.

