# Aurum Frontend Inventory (Read-Only Reconnaissance)

> **HISTORICAL:** Generated before Ring 4 shipped on `main` @ `251586c` and
> before the React migration API pin. Sections mentioning "uncommitted Ring 4"
> or needing contract confirmation are outdated. See `docs/API_CONTRACT.md`.

Generated from repository state on disk. Scope: Streamlit frontend (`app/`) and the report/API contract it depends on. No migration proposals.

---

## 1. Frontend File Tree

```
app/
└── streamlit_app.py
```

| File | Purpose | Reads `report.json` | Renders UI | Shared config/util |
|------|---------|---------------------|------------|--------------------|
| `app/streamlit_app.py` | Single-file Streamlit demo UI (3 screens: landing, verdict, detail) | **Yes** — `load_report_from_disk()` reads `reports/report.json`; can also receive in-memory dict from `run_engine_validation()` | **Yes** — all HTML/CSS/markdown rendering | **Yes** — `FIELDS` mapping, `COLORS`, `STATUS_STYLES`, `VERDICT_STYLES`, path constants |

No other files exist under `app/`.

Evidence (path + load):

```python
# app/streamlit_app.py
ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "reports" / "report.json"
```

---

## 2. Report.json Contract

### 2.1 Source file

- **Path:** `c:/Users/prakh/OneDrive/Documents/Aurum/reports/report.json`
- **Size:** 75,412 bytes, 2031 lines
- **Produced by:** `src/report_builder.py:write_report()` after `build_report()` (also written by Streamlit's `run_engine_validation()`)

### 2.2 Full verbatim contents

```json
{
  "project": "Aurum",
  "description": "Cross-layer data quality validation framework",
  "pipeline": "Raw \u2192 Bronze \u2192 Silver \u2192 Gold",
  "dataset": "Retail Orders",
  "run_id": "demo_run_001",
  "layer_status": {
    "bronze": "PASS",
    "silver": "FAIL",
    "gold": "IMPACTED"
  },
  "final_verdict": "NOT TRUSTED",
  "severity": "HIGH",
  "first_failed_layer": "Bronze \u2192 Silver",
  "root_cause": {
    "summary": "Valid high-quantity orders were wrongly removed during the Silver transformation.",
    "failed_check_ids": [
      "S1",
      "S2",
      "S8",
      "S9",
      "S10",
      "L2-REC-COUNT",
      "L3-ANO-SILVER",
      "L3-ANO-DROP_P"
    ],
    "suspected_filter": "quantity > 20 records are being filtered out",
    "evidence": [
      {
        "check_id": "S1",
        "detail": "Drop is far outside the learned normal range.",
        "evidence_query": "SELECT (1 - (SELECT COUNT(*) FROM silver_orders)::DOUBLE / (SELECT COUNT(*) FROM bronze_orders)) * 100 AS drop_pct"
      },
      {
        "check_id": "S2",
        "detail": "Actual drop 28.00% far exceeds expected 2.0%-10.0%.",
        "evidence_query": "SELECT (1 - (SELECT COUNT(*) FROM silver_orders)::DOUBLE / (SELECT COUNT(*) FROM bronze_orders)) * 100 AS drop_pct"
      },
      {
        "check_id": "S8",
        "detail": "24,000 valid business records were wrongly removed during the Silver transformation (25.00% of valid Bronze records).",
        "evidence_query": "SELECT COUNT(*) FROM bronze_orders b WHERE quantity > 0 AND unit_price > 0 AND invoice_no IS NOT NULL AND stock_code IS NOT NULL AND NOT EXISTS (SELECT 1 FROM silver_orders s WHERE s.invoice_no IS NOT DISTINCT FROM b.invoice_no AND s.stock_code IS NOT DISTINCT FROM b.stock_code AND s.customer_id IS NOT DISTINCT FROM b.customer_id AND s.invoice_date IS NOT DISTINCT FROM b.invoice_date)"
      },
      {
        "check_id": "S9",
        "detail": "Segment 'quantity > 20' lost 100.00% of valid records -- a structural loss, not random.",
        "evidence_query": "WITH valid_bronze AS (\n        SELECT * FROM bronze_orders WHERE quantity > 0 AND unit_price > 0 AND invoice_no IS NOT NULL AND stock_code IS NOT NULL\n    ),\n    seg AS (\n        SELECT\n            CASE WHEN quantity > 20\n                 THEN 'quantity > 20'\n                 ELSE 'quantity <= 20' END AS segment,\n            COUNT(*) AS bronze_valid\n        FROM valid_bronze GROUP BY 1\n    ),\n    sil AS (\n        SELECT\n            CASE WHEN quantity > 20\n                 THEN 'quantity > 20'\n                 ELSE 'quantity <= 20' END AS segment,\n            COUNT(*) AS silver_count\n        FROM silver_orders GROUP BY 1\n    )\n    SELECT seg.segment, seg.bronze_valid,\n           COALESCE(sil.silver_count, 0) AS silver_count,\n           ROUND((1 - COALESCE(sil.silver_count, 0)::DOUBLE / seg.bronze_valid) * 100, 2)\n               AS loss_pct\n    FROM seg LEFT JOIN sil ON seg.segment = sil.segment\n    ORDER BY loss_pct DESC"
      },
      {
        "check_id": "S10",
        "detail": "All 24,000 missing valid records have quantity >= 25; suspected bad filter: quantity > 20 records are being filtered out.",
        "evidence_query": "SELECT MIN(quantity), MAX(quantity), COUNT(*) FROM bronze_orders b WHERE quantity > 0 AND unit_price > 0 AND invoice_no IS NOT NULL AND stock_code IS NOT NULL AND NOT EXISTS (SELECT 1 FROM silver_orders s WHERE s.invoice_no IS NOT DISTINCT FROM b.invoice_no AND s.stock_code IS NOT DISTINCT FROM b.stock_code AND s.customer_id IS NOT DISTINCT FROM b.customer_id AND s.invoice_date IS NOT DISTINCT FROM b.invoice_date)"
      },
      {
        "check_id": "L2-REC-COUNT",
        "detail": "24,000 valid Bronze rows missing from Silver (4,000 invalid rows legitimately removed).",
        "evidence_query": "SELECT COUNT(*) FROM bronze_orders b WHERE quantity > 0 AND unit_price > 0 AND invoice_no IS NOT NULL AND stock_code IS NOT NULL AND NOT EXISTS (SELECT 1 FROM silver_orders s WHERE s.invoice_no = b.invoice_no)"
      },
      {
        "check_id": "L3-ANO-SILVER",
        "detail": "Extreme outlier: modified Z=-38.77 (> 3.5) and outside IQR [9.327e+04, 9.628e+04].",
        "evidence_query": "SELECT COUNT(*) FROM silver_orders"
      },
      {
        "check_id": "L3-ANO-DROP_P",
        "detail": "Extreme outlier: modified Z=38.45 (> 3.5) and outside IQR [3.65, 6.85].",
        "evidence_query": "SELECT (1 - (SELECT COUNT(*) FROM silver_orders)::DOUBLE / NULLIF((SELECT COUNT(*) FROM bronze_orders), 0)) * 100"
      }
    ]
  },
  "business_impact": {
    "expected_revenue": 101800000.0,
    "actual_revenue": 97000000.0,
    "estimated_loss": 4800000.0,
    "loss_percent": 4.72,
    "detail": "Expected revenue is the revenue of all valid Bronze records; actual is current Gold revenue. The gap is the value lost to dropped valid records."
  },
  "suggested_action": "Fix the Silver transformation rule (quantity > 20 records are being filtered out) and rerun the ETL.",
  "coverage": {
    "total_checks": 69,
    "passed": 56,
    "warned": 0,
    "failed": 10,
    "impacted": 2,
    "skipped": 1,
    "skipped_details": [
      {
        "check_id": "L1-SIL-CONS-FK-CUST",
        "reason": "table 'customers' not present -- FK check not applicable."
      }
    ],
    "full_coverage": false
  },
  "detection_layers": {
    "layer_1_rules": [
      {
        "check_id": "L1-RAW-COMP-EMPTY",
        "check_name": "Empty Table Check",
        "layer": "Bronze",
        "status": "PASS",
        "observed": 100000,
        "expected": "> 0",
        "detail": "Table has rows.",
        "evidence_query": "SELECT COUNT(*) FROM raw_orders",
        "extra": {
          "dimension": "completeness",
          "detection_layer": "layer_1_rules",
          "table": "raw_orders"
        }
      },
      {
        "check_id": "L1-RAW-COMP-NULL",
        "check_name": "Mandatory Column Null Check",
        "layer": "Bronze",
        "status": "PASS",
        "observed": {
          "invoice_no": 0,
          "stock_code": 0,
          "quantity": 0,
          "unit_price": 0,
          "invoice_date": 0,
          "customer_id": 0,
          "country": 0
        },
        "expected": {
          "invoice_no": 0,
          "stock_code": 0,
          "quantity": 0,
          "unit_price": 0,
          "invoice_date": 0,
          "customer_id": 0,
          "country": 0
        },
        "detail": "No nulls in mandatory columns.",
        "evidence_query": "SELECT COUNT(*) FROM raw_orders WHERE invoice_no IS NULL",
        "extra": {
          "dimension": "completeness",
          "detection_layer": "layer_1_rules",
          "table": "raw_orders"
        }
      },
      {
        "check_id": "L1-RAW-VAL-UNIT",
        "check_name": "Range Check: unit_price",
        "layer": "Bronze",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No invalid unit_price values.",
        "evidence_query": "SELECT COUNT(*) FROM raw_orders WHERE unit_price <= 0",
        "extra": {
          "dimension": "validity",
          "detection_layer": "layer_1_rules",
          "table": "raw_orders"
        }
      },
      {
        "check_id": "L1-RAW-VAL-DATE",
        "check_name": "Date Parse Validity: invoice_date",
        "layer": "Bronze",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "All invoice_date values parse as dates.",
        "evidence_query": "SELECT COUNT(*) FROM raw_orders WHERE TRY_CAST(invoice_date AS DATE) IS NULL",
        "extra": {
          "dimension": "validity",
          "detection_layer": "layer_1_rules",
          "table": "raw_orders"
        }
      },
      {
        "check_id": "L1-RAW-UNIQ-PK",
        "check_name": "Primary Key Duplicate Check",
        "layer": "Bronze",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No primary-key duplicates.",
        "evidence_query": "SELECT invoice_no, COUNT(*) FROM raw_orders GROUP BY invoice_no HAVING COUNT(*) > 1",
        "extra": {
          "dimension": "uniqueness",
          "detection_layer": "layer_1_rules",
          "table": "raw_orders"
        }
      },
      {
        "check_id": "L1-RAW-UNIQ-FULL",
        "check_name": "Full Row Duplicate Check",
        "layer": "Bronze",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No full-row duplicates.",
        "evidence_query": "SELECT COUNT(*) - (SELECT COUNT(*) FROM (SELECT DISTINCT * FROM raw_orders)) FROM raw_orders",
        "extra": {
          "dimension": "uniqueness",
          "detection_layer": "layer_1_rules",
          "table": "raw_orders"
        }
      },
      {
        "check_id": "L1-RAW-TIME-FRESH",
        "check_name": "Date Freshness: invoice_date",
        "layer": "Bronze",
        "status": "PASS",
        "observed": {
          "max_date": "2026-06-17 00:00:00",
          "run_date": "2026-07-02 00:00:00",
          "max_future_days": 0,
          "expected_freshness_days": 365
        },
        "expected": "max_date <= run_date + 0d and not stale",
        "detail": "Max invoice_date (2026-06-17 00:00:00) is within freshness window (not future, not stale beyond 365 days).",
        "evidence_query": "SELECT MAX(TRY_CAST(invoice_date AS DATE)) AS max_d, CURRENT_DATE AS run_date FROM raw_orders WHERE invoice_date IS NOT NULL",
        "extra": {
          "dimension": "timeliness",
          "detection_layer": "layer_1_rules",
          "table": "raw_orders"
        }
      },
      {
        "check_id": "L1-RAW-TIME",
        "check_name": "Timeliness Window: invoice_date",
        "layer": "Bronze",
        "status": "PASS",
        "observed": "span=0d",
        "expected": "<= 365d",
        "detail": "Date span 0 days within window.",
        "evidence_query": "SELECT MIN(invoice_date), MAX(invoice_date) FROM raw_orders",
        "extra": {
          "dimension": "timeliness",
          "detection_layer": "layer_1_rules",
          "table": "raw_orders"
        }
      },
      {
        "check_id": "L1-BRO-COMP-EMPTY",
        "check_name": "Empty Table Check",
        "layer": "Bronze",
        "status": "PASS",
        "observed": 100000,
        "expected": "> 0",
        "detail": "Table has rows.",
        "evidence_query": "SELECT COUNT(*) FROM bronze_orders",
        "extra": {
          "dimension": "completeness",
          "detection_layer": "layer_1_rules",
          "table": "bronze_orders"
        }
      },
      {
        "check_id": "L1-BRO-COMP-NULL",
        "check_name": "Mandatory Column Null Check",
        "layer": "Bronze",
        "status": "PASS",
        "observed": {
          "invoice_no": 0,
          "stock_code": 0,
          "quantity": 0,
          "unit_price": 0,
          "invoice_date": 0,
          "customer_id": 0,
          "country": 0
        },
        "expected": {
          "invoice_no": 0,
          "stock_code": 0,
          "quantity": 0,
          "unit_price": 0,
          "invoice_date": 0,
          "customer_id": 0,
          "country": 0
        },
        "detail": "No nulls in mandatory columns.",
        "evidence_query": "SELECT COUNT(*) FROM bronze_orders WHERE invoice_no IS NULL",
        "extra": {
          "dimension": "completeness",
          "detection_layer": "layer_1_rules",
          "table": "bronze_orders"
        }
      },
      {
        "check_id": "L1-BRO-COMP-SRC",
        "check_name": "Source to Table Row Count",
        "layer": "Bronze",
        "status": "PASS",
        "observed": 100000,
        "expected": 100000,
        "detail": "Row counts match.",
        "evidence_query": "SELECT COUNT(*) FROM bronze_orders",
        "extra": {
          "dimension": "completeness",
          "detection_layer": "layer_1_rules",
          "table": "bronze_orders"
        }
      },
      {
        "check_id": "L1-BRO-VAL-UNIT",
        "check_name": "Range Check: unit_price",
        "layer": "Bronze",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No invalid unit_price values.",
        "evidence_query": "SELECT COUNT(*) FROM bronze_orders WHERE unit_price < 0",
        "extra": {
          "dimension": "validity",
          "detection_layer": "layer_1_rules",
          "table": "bronze_orders"
        }
      },
      {
        "check_id": "L1-BRO-VAL-DATE",
        "check_name": "Date Parse Validity: invoice_date",
        "layer": "Bronze",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "All invoice_date values parse as dates.",
        "evidence_query": "SELECT COUNT(*) FROM bronze_orders WHERE TRY_CAST(invoice_date AS DATE) IS NULL",
        "extra": {
          "dimension": "validity",
          "detection_layer": "layer_1_rules",
          "table": "bronze_orders"
        }
      },
      {
        "check_id": "L1-BRO-UNIQ-PK",
        "check_name": "Primary Key Duplicate Check",
        "layer": "Bronze",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No primary-key duplicates.",
        "evidence_query": "SELECT invoice_no, COUNT(*) FROM bronze_orders GROUP BY invoice_no HAVING COUNT(*) > 1",
        "extra": {
          "dimension": "uniqueness",
          "detection_layer": "layer_1_rules",
          "table": "bronze_orders"
        }
      },
      {
        "check_id": "L1-BRO-UNIQ-FULL",
        "check_name": "Full Row Duplicate Check",
        "layer": "Bronze",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No full-row duplicates.",
        "evidence_query": "SELECT COUNT(*) - (SELECT COUNT(*) FROM (SELECT DISTINCT * FROM bronze_orders)) FROM bronze_orders",
        "extra": {
          "dimension": "uniqueness",
          "detection_layer": "layer_1_rules",
          "table": "bronze_orders"
        }
      },
      {
        "check_id": "L1-BRO-TIME-FRESH",
        "check_name": "Date Freshness: invoice_date",
        "layer": "Bronze",
        "status": "PASS",
        "observed": {
          "max_date": "2026-06-17 00:00:00",
          "run_date": "2026-07-02 00:00:00",
          "max_future_days": 0,
          "expected_freshness_days": 365
        },
        "expected": "max_date <= run_date + 0d and not stale",
        "detail": "Max invoice_date (2026-06-17 00:00:00) is within freshness window (not future, not stale beyond 365 days).",
        "evidence_query": "SELECT MAX(TRY_CAST(invoice_date AS DATE)) AS max_d, CURRENT_DATE AS run_date FROM bronze_orders WHERE invoice_date IS NOT NULL",
        "extra": {
          "dimension": "timeliness",
          "detection_layer": "layer_1_rules",
          "table": "bronze_orders"
        }
      },
      {
        "check_id": "L1-BRO-TIME",
        "check_name": "Timeliness Window: invoice_date",
        "layer": "Bronze",
        "status": "PASS",
        "observed": "span=0d",
        "expected": "<= 365d",
        "detail": "Date span 0 days within window.",
        "evidence_query": "SELECT MIN(invoice_date), MAX(invoice_date) FROM bronze_orders",
        "extra": {
          "dimension": "timeliness",
          "detection_layer": "layer_1_rules",
          "table": "bronze_orders"
        }
      },
      {
        "check_id": "L1-SIL-COMP-EMPTY",
        "check_name": "Empty Table Check",
        "layer": "Silver",
        "status": "PASS",
        "observed": 72000,
        "expected": "> 0",
        "detail": "Table has rows.",
        "evidence_query": "SELECT COUNT(*) FROM silver_orders",
        "extra": {
          "dimension": "completeness",
          "detection_layer": "layer_1_rules",
          "table": "silver_orders"
        }
      },
      {
        "check_id": "L1-SIL-COMP-NULL",
        "check_name": "Mandatory Column Null Check",
        "layer": "Silver",
        "status": "PASS",
        "observed": {
          "invoice_no": 0,
          "stock_code": 0,
          "quantity": 0,
          "unit_price": 0,
          "invoice_date": 0,
          "customer_id": 0,
          "country": 0
        },
        "expected": {
          "invoice_no": 0,
          "stock_code": 0,
          "quantity": 0,
          "unit_price": 0,
          "invoice_date": 0,
          "customer_id": 0,
          "country": 0
        },
        "detail": "No nulls in mandatory columns.",
        "evidence_query": "SELECT COUNT(*) FROM silver_orders WHERE invoice_no IS NULL",
        "extra": {
          "dimension": "completeness",
          "detection_layer": "layer_1_rules",
          "table": "silver_orders"
        }
      },
      {
        "check_id": "L1-SIL-VAL-QUAN",
        "check_name": "Range Check: quantity",
        "layer": "Silver",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No invalid quantity values.",
        "evidence_query": "SELECT COUNT(*) FROM silver_orders WHERE quantity <= 0",
        "extra": {
          "dimension": "validity",
          "detection_layer": "layer_1_rules",
          "table": "silver_orders"
        }
      },
      {
        "check_id": "L1-SIL-VAL-UNIT",
        "check_name": "Range Check: unit_price",
        "layer": "Silver",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No invalid unit_price values.",
        "evidence_query": "SELECT COUNT(*) FROM silver_orders WHERE unit_price <= 0",
        "extra": {
          "dimension": "validity",
          "detection_layer": "layer_1_rules",
          "table": "silver_orders"
        }
      },
      {
        "check_id": "L1-SIL-VAL-DATE",
        "check_name": "Date Parse Validity: invoice_date",
        "layer": "Silver",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "All invoice_date values parse as dates.",
        "evidence_query": "SELECT COUNT(*) FROM silver_orders WHERE TRY_CAST(invoice_date AS DATE) IS NULL",
        "extra": {
          "dimension": "validity",
          "detection_layer": "layer_1_rules",
          "table": "silver_orders"
        }
      },
      {
        "check_id": "L1-SIL-UNIQ-PK",
        "check_name": "Primary Key Duplicate Check",
        "layer": "Silver",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No primary-key duplicates.",
        "evidence_query": "SELECT invoice_no, COUNT(*) FROM silver_orders GROUP BY invoice_no HAVING COUNT(*) > 1",
        "extra": {
          "dimension": "uniqueness",
          "detection_layer": "layer_1_rules",
          "table": "silver_orders"
        }
      },
      {
        "check_id": "L1-SIL-UNIQ-FULL",
        "check_name": "Full Row Duplicate Check",
        "layer": "Silver",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No full-row duplicates.",
        "evidence_query": "SELECT COUNT(*) - (SELECT COUNT(*) FROM (SELECT DISTINCT * FROM silver_orders)) FROM silver_orders",
        "extra": {
          "dimension": "uniqueness",
          "detection_layer": "layer_1_rules",
          "table": "silver_orders"
        }
      },
      {
        "check_id": "L1-SIL-CONS-FK-CUST",
        "check_name": "Foreign Key Integrity: customer_id -> customers.customer_id",
        "layer": "Silver",
        "status": "SKIPPED",
        "observed": null,
        "expected": "check could not be evaluated",
        "detail": "table 'customers' not present -- FK check not applicable.",
        "evidence_query": ""
      },
      {
        "check_id": "L1-SIL-TIME-FRESH",
        "check_name": "Date Freshness: invoice_date",
        "layer": "Silver",
        "status": "PASS",
        "observed": {
          "max_date": "2026-06-17 00:00:00",
          "run_date": "2026-07-02 00:00:00",
          "max_future_days": 0,
          "expected_freshness_days": 365
        },
        "expected": "max_date <= run_date + 0d and not stale",
        "detail": "Max invoice_date (2026-06-17 00:00:00) is within freshness window (not future, not stale beyond 365 days).",
        "evidence_query": "SELECT MAX(TRY_CAST(invoice_date AS DATE)) AS max_d, CURRENT_DATE AS run_date FROM silver_orders WHERE invoice_date IS NOT NULL",
        "extra": {
          "dimension": "timeliness",
          "detection_layer": "layer_1_rules",
          "table": "silver_orders"
        }
      },
      {
        "check_id": "L1-SIL-TIME",
        "check_name": "Timeliness Window: invoice_date",
        "layer": "Silver",
        "status": "PASS",
        "observed": "span=0d",
        "expected": "<= 365d",
        "detail": "Date span 0 days within window.",
        "evidence_query": "SELECT MIN(invoice_date), MAX(invoice_date) FROM silver_orders",
        "extra": {
          "dimension": "timeliness",
          "detection_layer": "layer_1_rules",
          "table": "silver_orders"
        }
      },
      {
        "check_id": "L1-GOL-COMP-EMPTY",
        "check_name": "Empty Table Check",
        "layer": "Gold",
        "status": "PASS",
        "observed": 1,
        "expected": "> 0",
        "detail": "Table has rows.",
        "evidence_query": "SELECT COUNT(*) FROM gold_metrics",
        "extra": {
          "dimension": "completeness",
          "detection_layer": "layer_1_rules",
          "table": "gold_metrics"
        }
      },
      {
        "check_id": "L1-GOL-COMP-NULL",
        "check_name": "Mandatory Column Null Check",
        "layer": "Gold",
        "status": "PASS",
        "observed": {
          "total_revenue": 0,
          "total_orders": 0,
          "total_customers": 0,
          "average_order_value": 0
        },
        "expected": {
          "total_revenue": 0,
          "total_orders": 0,
          "total_customers": 0,
          "average_order_value": 0
        },
        "detail": "No nulls in mandatory columns.",
        "evidence_query": "SELECT COUNT(*) FROM gold_metrics WHERE total_revenue IS NULL",
        "extra": {
          "dimension": "completeness",
          "detection_layer": "layer_1_rules",
          "table": "gold_metrics"
        }
      },
      {
        "check_id": "L1-GOL-VAL-TOTA",
        "check_name": "Range Check: total_revenue",
        "layer": "Gold",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No invalid total_revenue values.",
        "evidence_query": "SELECT COUNT(*) FROM gold_metrics WHERE total_revenue < 0",
        "extra": {
          "dimension": "validity",
          "detection_layer": "layer_1_rules",
          "table": "gold_metrics"
        }
      },
      {
        "check_id": "L1-GOL-VAL-TOTA",
        "check_name": "Range Check: total_orders",
        "layer": "Gold",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No invalid total_orders values.",
        "evidence_query": "SELECT COUNT(*) FROM gold_metrics WHERE total_orders < 0",
        "extra": {
          "dimension": "validity",
          "detection_layer": "layer_1_rules",
          "table": "gold_metrics"
        }
      },
      {
        "check_id": "L1-GOL-VAL-TOTA",
        "check_name": "Range Check: total_customers",
        "layer": "Gold",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No invalid total_customers values.",
        "evidence_query": "SELECT COUNT(*) FROM gold_metrics WHERE total_customers < 0",
        "extra": {
          "dimension": "validity",
          "detection_layer": "layer_1_rules",
          "table": "gold_metrics"
        }
      },
      {
        "check_id": "L1-GOL-UNIQ-FULL",
        "check_name": "Full Row Duplicate Check",
        "layer": "Gold",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No full-row duplicates.",
        "evidence_query": "SELECT COUNT(*) - (SELECT COUNT(*) FROM (SELECT DISTINCT * FROM gold_metrics)) FROM gold_metrics",
        "extra": {
          "dimension": "uniqueness",
          "detection_layer": "layer_1_rules",
          "table": "gold_metrics"
        }
      }
    ],
    "layer_2_reconciliation": [
      {
        "check_id": "L2-REC-COUNT",
        "check_name": "Count Reconciliation: Unexplained Valid Row Loss",
        "layer": "Silver",
        "status": "FAIL",
        "observed": {
          "bronze_total": 100000,
          "bronze_valid": 96000,
          "silver_count": 72000,
          "missing_valid": 24000,
          "explained_removals": 4000,
          "unexplained_loss": 24000
        },
        "expected": {
          "unexplained_loss": 0
        },
        "detail": "24,000 valid Bronze rows missing from Silver (4,000 invalid rows legitimately removed).",
        "evidence_query": "SELECT COUNT(*) FROM bronze_orders b WHERE quantity > 0 AND unit_price > 0 AND invoice_no IS NOT NULL AND stock_code IS NOT NULL AND NOT EXISTS (SELECT 1 FROM silver_orders s WHERE s.invoice_no = b.invoice_no)",
        "extra": {
          "dimension": "completeness",
          "detection_layer": "layer_2_reconciliation"
        }
      },
      {
        "check_id": "L2-REC-KEY",
        "check_name": "Key-Set Reconciliation: Bronze \u2287 Silver, Silver \u2287 Gold keys",
        "layer": "Silver",
        "status": "PASS",
        "observed": {
          "silver_keys_not_in_bronze": 0,
          "silver_distinct_invoices": 72000,
          "gold_total_orders": 72000,
          "gold_excess_over_silver": 0
        },
        "expected": {
          "violations": 0
        },
        "detail": "Key sets are consistent across layers.",
        "evidence_query": "SELECT COUNT(*) FROM silver_orders s WHERE NOT EXISTS (SELECT 1 FROM bronze_orders b WHERE b.invoice_no = s.invoice_no)",
        "extra": {
          "dimension": "consistency",
          "detection_layer": "layer_2_reconciliation"
        }
      },
      {
        "check_id": "L2-REC-REV",
        "check_name": "Revenue Reconciliation: Silver SUM vs Gold (within rounding tolerance)",
        "layer": "Gold",
        "status": "PASS",
        "observed": {
          "silver_revenue": 97000000.0,
          "gold_revenue": 97000000.0,
          "difference": 0.0,
          "revenue_rounding_tolerance": 1.0
        },
        "expected": {
          "difference": "<= 1.0 (reconciles within rounding tolerance of 1.0 currency unit(s) (float SUM drift; counts remain exact))"
        },
        "detail": "Silver revenue reconciles with Gold (reconciles within rounding tolerance of 1.0 currency unit(s) (float SUM drift; counts remain exact)).",
        "evidence_query": "SELECT SUM(net_revenue) FROM silver_orders",
        "extra": {
          "dimension": "accuracy",
          "detection_layer": "layer_2_reconciliation",
          "table": "gold_metrics",
          "revenue_rounding_tolerance": 1.0
        }
      },
      {
        "check_id": "L2-REC-AGG",
        "check_name": "Aggregate Cross-Check: Recompute Gold from Silver",
        "layer": "Gold",
        "status": "PASS",
        "observed": {
          "silver": {
            "revenue": 97000000.0,
            "orders": 72000,
            "customers": 5000
          },
          "gold": {
            "total_revenue": 97000000.0,
            "total_orders": 72000,
            "total_customers": 5000
          },
          "mismatched_fields": []
        },
        "expected": {
          "mismatched_fields": []
        },
        "detail": "All Gold aggregates match Silver recomputation (revenue within rounding tolerance).",
        "evidence_query": "SELECT SUM(net_revenue), COUNT(DISTINCT invoice_no), COUNT(DISTINCT customer_id) FROM silver_orders",
        "extra": {
          "dimension": "accuracy",
          "detection_layer": "layer_2_reconciliation",
          "table": "gold_metrics"
        }
      }
    ],
    "layer_3_robust_anomaly": [
      {
        "check_id": "L3-ANO-BRONZE",
        "check_name": "Robust Anomaly: Bronze Row Count",
        "layer": "Bronze",
        "status": "PASS",
        "observed": {
          "value": 100000.0,
          "median": 100000.0,
          "iqr_lower": 99840.0,
          "iqr_upper": 100160.0,
          "modified_z": 0.0,
          "history_count": 15,
          "method": "median + IQR (Q1 - 1.5*IQR, Q3 + 1.5*IQR)",
          "detail": "Within robust IQR band."
        },
        "expected": "within robust IQR band",
        "detail": "Within robust IQR band.",
        "evidence_query": "SELECT COUNT(*) FROM bronze_orders",
        "extra": {
          "dimension": "completeness",
          "detection_layer": "layer_3_robust_anomaly",
          "metric": "bronze_count",
          "method": "median + IQR; modified Z (MAD)"
        }
      },
      {
        "check_id": "L3-ANO-SILVER",
        "check_name": "Robust Anomaly: Silver Row Count",
        "layer": "Silver",
        "status": "FAIL",
        "observed": {
          "value": 72000.0,
          "median": 94705.0,
          "iqr_lower": 93267.5,
          "iqr_upper": 96279.5,
          "modified_z": -38.77,
          "history_count": 15,
          "method": "median + IQR (Q1 - 1.5*IQR, Q3 + 1.5*IQR)",
          "detail": "Extreme outlier: modified Z=-38.77 (> 3.5) and outside IQR [9.327e+04, 9.628e+04]."
        },
        "expected": "within robust IQR band",
        "detail": "Extreme outlier: modified Z=-38.77 (> 3.5) and outside IQR [9.327e+04, 9.628e+04].",
        "evidence_query": "SELECT COUNT(*) FROM silver_orders",
        "extra": {
          "dimension": "completeness",
          "detection_layer": "layer_3_robust_anomaly",
          "metric": "silver_count",
          "method": "median + IQR; modified Z (MAD)"
        }
      },
      {
        "check_id": "L3-ANO-DROP_P",
        "check_name": "Robust Anomaly: Bronze-to-Silver Drop %",
        "layer": "Silver",
        "status": "FAIL",
        "observed": {
          "value": 28.000000000000004,
          "median": 5.2,
          "iqr_lower": 3.6499999999999986,
          "iqr_upper": 6.850000000000001,
          "modified_z": 38.45,
          "history_count": 15,
          "method": "median + IQR (Q1 - 1.5*IQR, Q3 + 1.5*IQR)",
          "detail": "Extreme outlier: modified Z=38.45 (> 3.5) and outside IQR [3.65, 6.85]."
        },
        "expected": "within robust IQR band",
        "detail": "Extreme outlier: modified Z=38.45 (> 3.5) and outside IQR [3.65, 6.85].",
        "evidence_query": "SELECT (1 - (SELECT COUNT(*) FROM silver_orders)::DOUBLE / NULLIF((SELECT COUNT(*) FROM bronze_orders), 0)) * 100",
        "extra": {
          "dimension": "completeness",
          "detection_layer": "layer_3_robust_anomaly",
          "metric": "drop_pct",
          "method": "median + IQR; modified Z (MAD)"
        }
      },
      {
        "check_id": "L3-ANO-GOLD_R",
        "check_name": "Robust Anomaly: Gold Revenue",
        "layer": "Gold",
        "status": "FAIL",
        "observed": {
          "value": 97000000.0,
          "median": 101800000.0,
          "iqr_lower": 101500000.0,
          "iqr_upper": 102100000.0,
          "modified_z": -32.38,
          "history_count": 15,
          "method": "median + IQR (Q1 - 1.5*IQR, Q3 + 1.5*IQR)",
          "detail": "Extreme outlier: modified Z=-32.38 (> 3.5) and outside IQR [1.015e+08, 1.021e+08]."
        },
        "expected": "within robust IQR band",
        "detail": "Extreme outlier: modified Z=-32.38 (> 3.5) and outside IQR [1.015e+08, 1.021e+08].",
        "evidence_query": "SELECT total_revenue FROM gold_metrics",
        "extra": {
          "dimension": "accuracy",
          "detection_layer": "layer_3_robust_anomaly",
          "metric": "gold_revenue",
          "method": "median + IQR; modified Z (MAD)"
        }
      }
    ]
  },
  "checks": {
    "bronze": [
      {
        "check_id": "B1",
        "check_name": "Source to Bronze Row Count",
        "layer": "Bronze",
        "status": "PASS",
        "observed": 100000,
        "expected": 100000,
        "detail": "Source and Bronze row counts match.",
        "evidence_query": "SELECT COUNT(*) FROM bronze_orders"
      },
      {
        "check_id": "B2",
        "check_name": "Low / High / Normal Count",
        "layer": "Bronze",
        "status": "PASS",
        "observed": 100000,
        "expected": "99775-100225 (mean +/- 3 std)",
        "detail": "Bronze count is within the learned normal range.",
        "evidence_query": "SELECT COUNT(*) FROM bronze_orders"
      },
      {
        "check_id": "B3",
        "check_name": "Empty Table Check",
        "layer": "Bronze",
        "status": "PASS",
        "observed": 100000,
        "expected": "> 0",
        "detail": "Bronze table has rows.",
        "evidence_query": "SELECT COUNT(*) FROM bronze_orders"
      },
      {
        "check_id": "B4",
        "check_name": "Required Columns Present",
        "layer": "Bronze",
        "status": "PASS",
        "observed": [
          "invoice_no",
          "stock_code",
          "description",
          "quantity",
          "invoice_date",
          "unit_price",
          "customer_id",
          "country"
        ],
        "expected": [
          "invoice_no",
          "stock_code",
          "description",
          "quantity",
          "invoice_date",
          "unit_price",
          "customer_id",
          "country"
        ],
        "detail": "All required columns are present.",
        "evidence_query": "SELECT * FROM bronze_orders LIMIT 0"
      },
      {
        "check_id": "B5",
        "check_name": "Extra / Missing Columns",
        "layer": "Bronze",
        "status": "PASS",
        "observed": {
          "missing_columns": [],
          "extra_columns": []
        },
        "expected": {
          "missing_columns": [],
          "extra_columns": []
        },
        "detail": "missing_columns=[], extra_columns=[]",
        "evidence_query": "SELECT * FROM bronze_orders LIMIT 0",
        "extra": {
          "missing_columns": [],
          "extra_columns": []
        }
      },
      {
        "check_id": "B6",
        "check_name": "Null Count per Mandatory Column",
        "layer": "Bronze",
        "status": "PASS",
        "observed": {
          "invoice_no": 0,
          "quantity": 0,
          "invoice_date": 0,
          "unit_price": 0,
          "country": 0
        },
        "expected": {
          "invoice_no": 0,
          "quantity": 0,
          "invoice_date": 0,
          "unit_price": 0,
          "country": 0
        },
        "detail": "No nulls in mandatory columns.",
        "evidence_query": "SELECT COUNT(*) FROM bronze_orders WHERE invoice_no IS NULL"
      },
      {
        "check_id": "B7",
        "check_name": "Negative Value Profiling",
        "layer": "Bronze",
        "status": "PASS",
        "observed": {
          "negative_quantity": 0,
          "negative_unit_price": 0
        },
        "expected": "profiled (not blocking at Bronze)",
        "detail": "No negative quantity or unit_price values.",
        "evidence_query": "SELECT COUNT(*) FROM bronze_orders WHERE quantity < 0"
      },
      {
        "check_id": "B8",
        "check_name": "Duplicate Check",
        "layer": "Bronze",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No duplicate business keys in Bronze.",
        "evidence_query": "SELECT invoice_no, stock_code, customer_id, invoice_date, COUNT(*) FROM bronze_orders GROUP BY invoice_no, stock_code, customer_id, invoice_date HAVING COUNT(*) > 1"
      },
      {
        "check_id": "L1-RAW-COMP-EMPTY",
        "check_name": "Empty Table Check",
        "layer": "Bronze",
        "status": "PASS",
        "observed": 100000,
        "expected": "> 0",
        "detail": "Table has rows.",
        "evidence_query": "SELECT COUNT(*) FROM raw_orders",
        "extra": {
          "dimension": "completeness",
          "detection_layer": "layer_1_rules",
          "table": "raw_orders"
        }
      },
      {
        "check_id": "L1-RAW-COMP-NULL",
        "check_name": "Mandatory Column Null Check",
        "layer": "Bronze",
        "status": "PASS",
        "observed": {
          "invoice_no": 0,
          "stock_code": 0,
          "quantity": 0,
          "unit_price": 0,
          "invoice_date": 0,
          "customer_id": 0,
          "country": 0
        },
        "expected": {
          "invoice_no": 0,
          "stock_code": 0,
          "quantity": 0,
          "unit_price": 0,
          "invoice_date": 0,
          "customer_id": 0,
          "country": 0
        },
        "detail": "No nulls in mandatory columns.",
        "evidence_query": "SELECT COUNT(*) FROM raw_orders WHERE invoice_no IS NULL",
        "extra": {
          "dimension": "completeness",
          "detection_layer": "layer_1_rules",
          "table": "raw_orders"
        }
      },
      {
        "check_id": "L1-RAW-VAL-UNIT",
        "check_name": "Range Check: unit_price",
        "layer": "Bronze",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No invalid unit_price values.",
        "evidence_query": "SELECT COUNT(*) FROM raw_orders WHERE unit_price <= 0",
        "extra": {
          "dimension": "validity",
          "detection_layer": "layer_1_rules",
          "table": "raw_orders"
        }
      },
      {
        "check_id": "L1-RAW-VAL-DATE",
        "check_name": "Date Parse Validity: invoice_date",
        "layer": "Bronze",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "All invoice_date values parse as dates.",
        "evidence_query": "SELECT COUNT(*) FROM raw_orders WHERE TRY_CAST(invoice_date AS DATE) IS NULL",
        "extra": {
          "dimension": "validity",
          "detection_layer": "layer_1_rules",
          "table": "raw_orders"
        }
      },
      {
        "check_id": "L1-RAW-UNIQ-PK",
        "check_name": "Primary Key Duplicate Check",
        "layer": "Bronze",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No primary-key duplicates.",
        "evidence_query": "SELECT invoice_no, COUNT(*) FROM raw_orders GROUP BY invoice_no HAVING COUNT(*) > 1",
        "extra": {
          "dimension": "uniqueness",
          "detection_layer": "layer_1_rules",
          "table": "raw_orders"
        }
      },
      {
        "check_id": "L1-RAW-UNIQ-FULL",
        "check_name": "Full Row Duplicate Check",
        "layer": "Bronze",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No full-row duplicates.",
        "evidence_query": "SELECT COUNT(*) - (SELECT COUNT(*) FROM (SELECT DISTINCT * FROM raw_orders)) FROM raw_orders",
        "extra": {
          "dimension": "uniqueness",
          "detection_layer": "layer_1_rules",
          "table": "raw_orders"
        }
      },
      {
        "check_id": "L1-RAW-TIME-FRESH",
        "check_name": "Date Freshness: invoice_date",
        "layer": "Bronze",
        "status": "PASS",
        "observed": {
          "max_date": "2026-06-17 00:00:00",
          "run_date": "2026-07-02 00:00:00",
          "max_future_days": 0,
          "expected_freshness_days": 365
        },
        "expected": "max_date <= run_date + 0d and not stale",
        "detail": "Max invoice_date (2026-06-17 00:00:00) is within freshness window (not future, not stale beyond 365 days).",
        "evidence_query": "SELECT MAX(TRY_CAST(invoice_date AS DATE)) AS max_d, CURRENT_DATE AS run_date FROM raw_orders WHERE invoice_date IS NOT NULL",
        "extra": {
          "dimension": "timeliness",
          "detection_layer": "layer_1_rules",
          "table": "raw_orders"
        }
      },
      {
        "check_id": "L1-RAW-TIME",
        "check_name": "Timeliness Window: invoice_date",
        "layer": "Bronze",
        "status": "PASS",
        "observed": "span=0d",
        "expected": "<= 365d",
        "detail": "Date span 0 days within window.",
        "evidence_query": "SELECT MIN(invoice_date), MAX(invoice_date) FROM raw_orders",
        "extra": {
          "dimension": "timeliness",
          "detection_layer": "layer_1_rules",
          "table": "raw_orders"
        }
      },
      {
        "check_id": "L1-BRO-COMP-EMPTY",
        "check_name": "Empty Table Check",
        "layer": "Bronze",
        "status": "PASS",
        "observed": 100000,
        "expected": "> 0",
        "detail": "Table has rows.",
        "evidence_query": "SELECT COUNT(*) FROM bronze_orders",
        "extra": {
          "dimension": "completeness",
          "detection_layer": "layer_1_rules",
          "table": "bronze_orders"
        }
      },
      {
        "check_id": "L1-BRO-COMP-NULL",
        "check_name": "Mandatory Column Null Check",
        "layer": "Bronze",
        "status": "PASS",
        "observed": {
          "invoice_no": 0,
          "stock_code": 0,
          "quantity": 0,
          "unit_price": 0,
          "invoice_date": 0,
          "customer_id": 0,
          "country": 0
        },
        "expected": {
          "invoice_no": 0,
          "stock_code": 0,
          "quantity": 0,
          "unit_price": 0,
          "invoice_date": 0,
          "customer_id": 0,
          "country": 0
        },
        "detail": "No nulls in mandatory columns.",
        "evidence_query": "SELECT COUNT(*) FROM bronze_orders WHERE invoice_no IS NULL",
        "extra": {
          "dimension": "completeness",
          "detection_layer": "layer_1_rules",
          "table": "bronze_orders"
        }
      },
      {
        "check_id": "L1-BRO-COMP-SRC",
        "check_name": "Source to Table Row Count",
        "layer": "Bronze",
        "status": "PASS",
        "observed": 100000,
        "expected": 100000,
        "detail": "Row counts match.",
        "evidence_query": "SELECT COUNT(*) FROM bronze_orders",
        "extra": {
          "dimension": "completeness",
          "detection_layer": "layer_1_rules",
          "table": "bronze_orders"
        }
      },
      {
        "check_id": "L1-BRO-VAL-UNIT",
        "check_name": "Range Check: unit_price",
        "layer": "Bronze",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No invalid unit_price values.",
        "evidence_query": "SELECT COUNT(*) FROM bronze_orders WHERE unit_price < 0",
        "extra": {
          "dimension": "validity",
          "detection_layer": "layer_1_rules",
          "table": "bronze_orders"
        }
      },
      {
        "check_id": "L1-BRO-VAL-DATE",
        "check_name": "Date Parse Validity: invoice_date",
        "layer": "Bronze",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "All invoice_date values parse as dates.",
        "evidence_query": "SELECT COUNT(*) FROM bronze_orders WHERE TRY_CAST(invoice_date AS DATE) IS NULL",
        "extra": {
          "dimension": "validity",
          "detection_layer": "layer_1_rules",
          "table": "bronze_orders"
        }
      },
      {
        "check_id": "L1-BRO-UNIQ-PK",
        "check_name": "Primary Key Duplicate Check",
        "layer": "Bronze",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No primary-key duplicates.",
        "evidence_query": "SELECT invoice_no, COUNT(*) FROM bronze_orders GROUP BY invoice_no HAVING COUNT(*) > 1",
        "extra": {
          "dimension": "uniqueness",
          "detection_layer": "layer_1_rules",
          "table": "bronze_orders"
        }
      },
      {
        "check_id": "L1-BRO-UNIQ-FULL",
        "check_name": "Full Row Duplicate Check",
        "layer": "Bronze",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No full-row duplicates.",
        "evidence_query": "SELECT COUNT(*) - (SELECT COUNT(*) FROM (SELECT DISTINCT * FROM bronze_orders)) FROM bronze_orders",
        "extra": {
          "dimension": "uniqueness",
          "detection_layer": "layer_1_rules",
          "table": "bronze_orders"
        }
      },
      {
        "check_id": "L1-BRO-TIME-FRESH",
        "check_name": "Date Freshness: invoice_date",
        "layer": "Bronze",
        "status": "PASS",
        "observed": {
          "max_date": "2026-06-17 00:00:00",
          "run_date": "2026-07-02 00:00:00",
          "max_future_days": 0,
          "expected_freshness_days": 365
        },
        "expected": "max_date <= run_date + 0d and not stale",
        "detail": "Max invoice_date (2026-06-17 00:00:00) is within freshness window (not future, not stale beyond 365 days).",
        "evidence_query": "SELECT MAX(TRY_CAST(invoice_date AS DATE)) AS max_d, CURRENT_DATE AS run_date FROM bronze_orders WHERE invoice_date IS NOT NULL",
        "extra": {
          "dimension": "timeliness",
          "detection_layer": "layer_1_rules",
          "table": "bronze_orders"
        }
      },
      {
        "check_id": "L1-BRO-TIME",
        "check_name": "Timeliness Window: invoice_date",
        "layer": "Bronze",
        "status": "PASS",
        "observed": "span=0d",
        "expected": "<= 365d",
        "detail": "Date span 0 days within window.",
        "evidence_query": "SELECT MIN(invoice_date), MAX(invoice_date) FROM bronze_orders",
        "extra": {
          "dimension": "timeliness",
          "detection_layer": "layer_1_rules",
          "table": "bronze_orders"
        }
      },
      {
        "check_id": "L3-ANO-BRONZE",
        "check_name": "Robust Anomaly: Bronze Row Count",
        "layer": "Bronze",
        "status": "PASS",
        "observed": {
          "value": 100000.0,
          "median": 100000.0,
          "iqr_lower": 99840.0,
          "iqr_upper": 100160.0,
          "modified_z": 0.0,
          "history_count": 15,
          "method": "median + IQR (Q1 - 1.5*IQR, Q3 + 1.5*IQR)",
          "detail": "Within robust IQR band."
        },
        "expected": "within robust IQR band",
        "detail": "Within robust IQR band.",
        "evidence_query": "SELECT COUNT(*) FROM bronze_orders",
        "extra": {
          "dimension": "completeness",
          "detection_layer": "layer_3_robust_anomaly",
          "metric": "bronze_count",
          "method": "median + IQR; modified Z (MAD)"
        }
      }
    ],
    "silver": [
      {
        "check_id": "S1",
        "check_name": "Bronze to Silver Drop Percentage",
        "layer": "Silver",
        "status": "FAIL",
        "observed": "28.00%",
        "expected": "3.72%-6.80% (mean +/- 3 std)",
        "detail": "Drop is far outside the learned normal range.",
        "evidence_query": "SELECT (1 - (SELECT COUNT(*) FROM silver_orders)::DOUBLE / (SELECT COUNT(*) FROM bronze_orders)) * 100 AS drop_pct",
        "extra": {
          "bronze": 100000,
          "silver": 72000,
          "drop_pct": 28.0
        }
      },
      {
        "check_id": "S2",
        "check_name": "Expected Drop Check",
        "layer": "Silver",
        "status": "FAIL",
        "observed": "28.00%",
        "expected": "2.0%-10.0%",
        "detail": "Actual drop 28.00% far exceeds expected 2.0%-10.0%.",
        "evidence_query": "SELECT (1 - (SELECT COUNT(*) FROM silver_orders)::DOUBLE / (SELECT COUNT(*) FROM bronze_orders)) * 100 AS drop_pct"
      },
      {
        "check_id": "S3",
        "check_name": "Deduplication Count Check",
        "layer": "Silver",
        "status": "PASS",
        "observed": {
          "bronze_duplicates": 0,
          "silver_duplicates": 0
        },
        "expected": {
          "silver_duplicates": 0
        },
        "detail": "Bronze had 0 duplicate keys; Silver has none.",
        "evidence_query": "SELECT invoice_no, stock_code, customer_id, invoice_date, COUNT(*) FROM silver_orders GROUP BY invoice_no, stock_code, customer_id, invoice_date HAVING COUNT(*) > 1"
      },
      {
        "check_id": "S4",
        "check_name": "Mandatory Columns Not Null",
        "layer": "Silver",
        "status": "PASS",
        "observed": {
          "invoice_no": 0,
          "stock_code": 0,
          "quantity": 0,
          "unit_price": 0,
          "invoice_date": 0,
          "country": 0
        },
        "expected": {
          "invoice_no": 0,
          "stock_code": 0,
          "quantity": 0,
          "unit_price": 0,
          "invoice_date": 0,
          "country": 0
        },
        "detail": "No nulls in Silver mandatory columns.",
        "evidence_query": "SELECT COUNT(*) FROM silver_orders WHERE invoice_no IS NULL"
      },
      {
        "check_id": "S5",
        "check_name": "Quantity > 0",
        "layer": "Silver",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "All Silver rows have quantity > 0.",
        "evidence_query": "SELECT COUNT(*) FROM silver_orders WHERE quantity <= 0"
      },
      {
        "check_id": "S6",
        "check_name": "Unit Price > 0",
        "layer": "Silver",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "All Silver rows have unit_price > 0.",
        "evidence_query": "SELECT COUNT(*) FROM silver_orders WHERE unit_price <= 0"
      },
      {
        "check_id": "S7",
        "check_name": "Revenue Not Negative",
        "layer": "Silver",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "All Silver rows have non-negative net_revenue.",
        "evidence_query": "SELECT COUNT(*) FROM silver_orders WHERE net_revenue < 0"
      },
      {
        "check_id": "S8",
        "check_name": "Valid Record Wrongly Removed",
        "layer": "Silver",
        "status": "FAIL",
        "observed": 24000,
        "expected": 0,
        "detail": "24,000 valid business records were wrongly removed during the Silver transformation (25.00% of valid Bronze records).",
        "evidence_query": "SELECT COUNT(*) FROM bronze_orders b WHERE quantity > 0 AND unit_price > 0 AND invoice_no IS NOT NULL AND stock_code IS NOT NULL AND NOT EXISTS (SELECT 1 FROM silver_orders s WHERE s.invoice_no IS NOT DISTINCT FROM b.invoice_no AND s.stock_code IS NOT DISTINCT FROM b.stock_code AND s.customer_id IS NOT DISTINCT FROM b.customer_id AND s.invoice_date IS NOT DISTINCT FROM b.invoice_date)",
        "extra": {
          "valid_bronze": 96000,
          "missing": 24000,
          "loss_pct": 25.0
        }
      },
      {
        "check_id": "S9",
        "check_name": "Record-Loss by Segment",
        "layer": "Silver",
        "status": "FAIL",
        "observed": [
          {
            "segment": "quantity > 20",
            "bronze_valid": 24000,
            "silver_count": 0,
            "loss_pct": 100.0
          },
          {
            "segment": "quantity <= 20",
            "bronze_valid": 72000,
            "silver_count": 72000,
            "loss_pct": 0.0
          }
        ],
        "expected": "< 5% loss per segment",
        "detail": "Segment 'quantity > 20' lost 100.00% of valid records -- a structural loss, not random.",
        "evidence_query": "WITH valid_bronze AS (\n        SELECT * FROM bronze_orders WHERE quantity > 0 AND unit_price > 0 AND invoice_no IS NOT NULL AND stock_code IS NOT NULL\n    ),\n    seg AS (\n        SELECT\n            CASE WHEN quantity > 20\n                 THEN 'quantity > 20'\n                 ELSE 'quantity <= 20' END AS segment,\n            COUNT(*) AS bronze_valid\n        FROM valid_bronze GROUP BY 1\n    ),\n    sil AS (\n        SELECT\n            CASE WHEN quantity > 20\n                 THEN 'quantity > 20'\n                 ELSE 'quantity <= 20' END AS segment,\n            COUNT(*) AS silver_count\n        FROM silver_orders GROUP BY 1\n    )\n    SELECT seg.segment, seg.bronze_valid,\n           COALESCE(sil.silver_count, 0) AS silver_count,\n           ROUND((1 - COALESCE(sil.silver_count, 0)::DOUBLE / seg.bronze_valid) * 100, 2)\n               AS loss_pct\n    FROM seg LEFT JOIN sil ON seg.segment = sil.segment\n    ORDER BY loss_pct DESC",
        "extra": {
          "segments": [
            {
              "segment": "quantity > 20",
              "bronze_valid": 24000,
              "silver_count": 0,
              "loss_pct": 100.0
            },
            {
              "segment": "quantity <= 20",
              "bronze_valid": 72000,
              "silver_count": 72000,
              "loss_pct": 0.0
            }
          ]
        }
      },
      {
        "check_id": "S10",
        "check_name": "Wrong Filter Detection",
        "layer": "Silver",
        "status": "FAIL",
        "observed": "quantity > 20 records are being filtered out",
        "expected": "no suspect filter",
        "detail": "All 24,000 missing valid records have quantity >= 25; suspected bad filter: quantity > 20 records are being filtered out.",
        "evidence_query": "SELECT MIN(quantity), MAX(quantity), COUNT(*) FROM bronze_orders b WHERE quantity > 0 AND unit_price > 0 AND invoice_no IS NOT NULL AND stock_code IS NOT NULL AND NOT EXISTS (SELECT 1 FROM silver_orders s WHERE s.invoice_no IS NOT DISTINCT FROM b.invoice_no AND s.stock_code IS NOT DISTINCT FROM b.stock_code AND s.customer_id IS NOT DISTINCT FROM b.customer_id AND s.invoice_date IS NOT DISTINCT FROM b.invoice_date)",
        "extra": {
          "suspected_filter": "quantity > 20 records are being filtered out",
          "missing": 24000
        }
      },
      {
        "check_id": "L1-SIL-COMP-EMPTY",
        "check_name": "Empty Table Check",
        "layer": "Silver",
        "status": "PASS",
        "observed": 72000,
        "expected": "> 0",
        "detail": "Table has rows.",
        "evidence_query": "SELECT COUNT(*) FROM silver_orders",
        "extra": {
          "dimension": "completeness",
          "detection_layer": "layer_1_rules",
          "table": "silver_orders"
        }
      },
      {
        "check_id": "L1-SIL-COMP-NULL",
        "check_name": "Mandatory Column Null Check",
        "layer": "Silver",
        "status": "PASS",
        "observed": {
          "invoice_no": 0,
          "stock_code": 0,
          "quantity": 0,
          "unit_price": 0,
          "invoice_date": 0,
          "customer_id": 0,
          "country": 0
        },
        "expected": {
          "invoice_no": 0,
          "stock_code": 0,
          "quantity": 0,
          "unit_price": 0,
          "invoice_date": 0,
          "customer_id": 0,
          "country": 0
        },
        "detail": "No nulls in mandatory columns.",
        "evidence_query": "SELECT COUNT(*) FROM silver_orders WHERE invoice_no IS NULL",
        "extra": {
          "dimension": "completeness",
          "detection_layer": "layer_1_rules",
          "table": "silver_orders"
        }
      },
      {
        "check_id": "L1-SIL-VAL-QUAN",
        "check_name": "Range Check: quantity",
        "layer": "Silver",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No invalid quantity values.",
        "evidence_query": "SELECT COUNT(*) FROM silver_orders WHERE quantity <= 0",
        "extra": {
          "dimension": "validity",
          "detection_layer": "layer_1_rules",
          "table": "silver_orders"
        }
      },
      {
        "check_id": "L1-SIL-VAL-UNIT",
        "check_name": "Range Check: unit_price",
        "layer": "Silver",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No invalid unit_price values.",
        "evidence_query": "SELECT COUNT(*) FROM silver_orders WHERE unit_price <= 0",
        "extra": {
          "dimension": "validity",
          "detection_layer": "layer_1_rules",
          "table": "silver_orders"
        }
      },
      {
        "check_id": "L1-SIL-VAL-DATE",
        "check_name": "Date Parse Validity: invoice_date",
        "layer": "Silver",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "All invoice_date values parse as dates.",
        "evidence_query": "SELECT COUNT(*) FROM silver_orders WHERE TRY_CAST(invoice_date AS DATE) IS NULL",
        "extra": {
          "dimension": "validity",
          "detection_layer": "layer_1_rules",
          "table": "silver_orders"
        }
      },
      {
        "check_id": "L1-SIL-UNIQ-PK",
        "check_name": "Primary Key Duplicate Check",
        "layer": "Silver",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No primary-key duplicates.",
        "evidence_query": "SELECT invoice_no, COUNT(*) FROM silver_orders GROUP BY invoice_no HAVING COUNT(*) > 1",
        "extra": {
          "dimension": "uniqueness",
          "detection_layer": "layer_1_rules",
          "table": "silver_orders"
        }
      },
      {
        "check_id": "L1-SIL-UNIQ-FULL",
        "check_name": "Full Row Duplicate Check",
        "layer": "Silver",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No full-row duplicates.",
        "evidence_query": "SELECT COUNT(*) - (SELECT COUNT(*) FROM (SELECT DISTINCT * FROM silver_orders)) FROM silver_orders",
        "extra": {
          "dimension": "uniqueness",
          "detection_layer": "layer_1_rules",
          "table": "silver_orders"
        }
      },
      {
        "check_id": "L1-SIL-CONS-FK-CUST",
        "check_name": "Foreign Key Integrity: customer_id -> customers.customer_id",
        "layer": "Silver",
        "status": "SKIPPED",
        "observed": null,
        "expected": "check could not be evaluated",
        "detail": "table 'customers' not present -- FK check not applicable.",
        "evidence_query": ""
      },
      {
        "check_id": "L1-SIL-TIME-FRESH",
        "check_name": "Date Freshness: invoice_date",
        "layer": "Silver",
        "status": "PASS",
        "observed": {
          "max_date": "2026-06-17 00:00:00",
          "run_date": "2026-07-02 00:00:00",
          "max_future_days": 0,
          "expected_freshness_days": 365
        },
        "expected": "max_date <= run_date + 0d and not stale",
        "detail": "Max invoice_date (2026-06-17 00:00:00) is within freshness window (not future, not stale beyond 365 days).",
        "evidence_query": "SELECT MAX(TRY_CAST(invoice_date AS DATE)) AS max_d, CURRENT_DATE AS run_date FROM silver_orders WHERE invoice_date IS NOT NULL",
        "extra": {
          "dimension": "timeliness",
          "detection_layer": "layer_1_rules",
          "table": "silver_orders"
        }
      },
      {
        "check_id": "L1-SIL-TIME",
        "check_name": "Timeliness Window: invoice_date",
        "layer": "Silver",
        "status": "PASS",
        "observed": "span=0d",
        "expected": "<= 365d",
        "detail": "Date span 0 days within window.",
        "evidence_query": "SELECT MIN(invoice_date), MAX(invoice_date) FROM silver_orders",
        "extra": {
          "dimension": "timeliness",
          "detection_layer": "layer_1_rules",
          "table": "silver_orders"
        }
      },
      {
        "check_id": "L2-REC-COUNT",
        "check_name": "Count Reconciliation: Unexplained Valid Row Loss",
        "layer": "Silver",
        "status": "FAIL",
        "observed": {
          "bronze_total": 100000,
          "bronze_valid": 96000,
          "silver_count": 72000,
          "missing_valid": 24000,
          "explained_removals": 4000,
          "unexplained_loss": 24000
        },
        "expected": {
          "unexplained_loss": 0
        },
        "detail": "24,000 valid Bronze rows missing from Silver (4,000 invalid rows legitimately removed).",
        "evidence_query": "SELECT COUNT(*) FROM bronze_orders b WHERE quantity > 0 AND unit_price > 0 AND invoice_no IS NOT NULL AND stock_code IS NOT NULL AND NOT EXISTS (SELECT 1 FROM silver_orders s WHERE s.invoice_no = b.invoice_no)",
        "extra": {
          "dimension": "completeness",
          "detection_layer": "layer_2_reconciliation"
        }
      },
      {
        "check_id": "L2-REC-KEY",
        "check_name": "Key-Set Reconciliation: Bronze \u2287 Silver, Silver \u2287 Gold keys",
        "layer": "Silver",
        "status": "PASS",
        "observed": {
          "silver_keys_not_in_bronze": 0,
          "silver_distinct_invoices": 72000,
          "gold_total_orders": 72000,
          "gold_excess_over_silver": 0
        },
        "expected": {
          "violations": 0
        },
        "detail": "Key sets are consistent across layers.",
        "evidence_query": "SELECT COUNT(*) FROM silver_orders s WHERE NOT EXISTS (SELECT 1 FROM bronze_orders b WHERE b.invoice_no = s.invoice_no)",
        "extra": {
          "dimension": "consistency",
          "detection_layer": "layer_2_reconciliation"
        }
      },
      {
        "check_id": "L3-ANO-SILVER",
        "check_name": "Robust Anomaly: Silver Row Count",
        "layer": "Silver",
        "status": "FAIL",
        "observed": {
          "value": 72000.0,
          "median": 94705.0,
          "iqr_lower": 93267.5,
          "iqr_upper": 96279.5,
          "modified_z": -38.77,
          "history_count": 15,
          "method": "median + IQR (Q1 - 1.5*IQR, Q3 + 1.5*IQR)",
          "detail": "Extreme outlier: modified Z=-38.77 (> 3.5) and outside IQR [9.327e+04, 9.628e+04]."
        },
        "expected": "within robust IQR band",
        "detail": "Extreme outlier: modified Z=-38.77 (> 3.5) and outside IQR [9.327e+04, 9.628e+04].",
        "evidence_query": "SELECT COUNT(*) FROM silver_orders",
        "extra": {
          "dimension": "completeness",
          "detection_layer": "layer_3_robust_anomaly",
          "metric": "silver_count",
          "method": "median + IQR; modified Z (MAD)"
        }
      },
      {
        "check_id": "L3-ANO-DROP_P",
        "check_name": "Robust Anomaly: Bronze-to-Silver Drop %",
        "layer": "Silver",
        "status": "FAIL",
        "observed": {
          "value": 28.000000000000004,
          "median": 5.2,
          "iqr_lower": 3.6499999999999986,
          "iqr_upper": 6.850000000000001,
          "modified_z": 38.45,
          "history_count": 15,
          "method": "median + IQR (Q1 - 1.5*IQR, Q3 + 1.5*IQR)",
          "detail": "Extreme outlier: modified Z=38.45 (> 3.5) and outside IQR [3.65, 6.85]."
        },
        "expected": "within robust IQR band",
        "detail": "Extreme outlier: modified Z=38.45 (> 3.5) and outside IQR [3.65, 6.85].",
        "evidence_query": "SELECT (1 - (SELECT COUNT(*) FROM silver_orders)::DOUBLE / NULLIF((SELECT COUNT(*) FROM bronze_orders), 0)) * 100",
        "extra": {
          "dimension": "completeness",
          "detection_layer": "layer_3_robust_anomaly",
          "metric": "drop_pct",
          "method": "median + IQR; modified Z (MAD)"
        }
      }
    ],
    "gold": [
      {
        "check_id": "G1",
        "check_name": "Revenue Reconciliation (within rounding tolerance)",
        "layer": "Gold",
        "status": "PASS",
        "observed": {
          "gold_revenue": 97000000.0,
          "difference": 0.0,
          "revenue_rounding_tolerance": 1.0
        },
        "expected": {
          "silver_revenue": 97000000.0
        },
        "detail": "Gold total_revenue reconciles with Silver (reconciles within rounding tolerance of 1.0 currency unit(s) (float SUM drift; counts remain exact)).",
        "evidence_query": "SELECT SUM(net_revenue) FROM silver_orders",
        "extra": {
          "revenue_rounding_tolerance": 1.0
        }
      },
      {
        "check_id": "G2",
        "check_name": "Order Count Reconciliation",
        "layer": "Gold",
        "status": "PASS",
        "observed": 72000,
        "expected": 72000,
        "detail": "Gold total_orders reconciles with Silver.",
        "evidence_query": "SELECT COUNT(DISTINCT invoice_no) FROM silver_orders"
      },
      {
        "check_id": "G3",
        "check_name": "Customer Count Reconciliation",
        "layer": "Gold",
        "status": "PASS",
        "observed": 5000,
        "expected": 5000,
        "detail": "Gold total_customers reconciles with Silver.",
        "evidence_query": "SELECT COUNT(DISTINCT customer_id) FROM silver_orders"
      },
      {
        "check_id": "G4",
        "check_name": "Average Order Value Check",
        "layer": "Gold",
        "status": "PASS",
        "observed": 1347.2222222222222,
        "expected": 1347.22,
        "detail": "Gold AOV reconciles (recomputed 1,347.22).",
        "evidence_query": "SELECT total_revenue / total_orders FROM gold_metrics"
      },
      {
        "check_id": "G5",
        "check_name": "Revenue vs Expected Baseline",
        "layer": "Gold",
        "status": "IMPACTED",
        "observed": 97000000.0,
        "expected": 101800000.0,
        "detail": "Gold math is correct, but revenue is 4,800,000 below the expected baseline -- impacted by an upstream layer failure.",
        "evidence_query": "SELECT total_revenue FROM gold_metrics",
        "extra": {
          "expected_revenue": 101800000.0,
          "actual_revenue": 97000000.0,
          "impact": 4800000.0,
          "gold_math_correct": true
        }
      },
      {
        "check_id": "G6",
        "check_name": "Country-wise Revenue Reconciliation",
        "layer": "Gold",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "Country-wise revenue reconciles with Silver.",
        "evidence_query": "SELECT country, SUM(net_revenue) FROM silver_orders GROUP BY country"
      },
      {
        "check_id": "L1-GOL-COMP-EMPTY",
        "check_name": "Empty Table Check",
        "layer": "Gold",
        "status": "PASS",
        "observed": 1,
        "expected": "> 0",
        "detail": "Table has rows.",
        "evidence_query": "SELECT COUNT(*) FROM gold_metrics",
        "extra": {
          "dimension": "completeness",
          "detection_layer": "layer_1_rules",
          "table": "gold_metrics"
        }
      },
      {
        "check_id": "L1-GOL-COMP-NULL",
        "check_name": "Mandatory Column Null Check",
        "layer": "Gold",
        "status": "PASS",
        "observed": {
          "total_revenue": 0,
          "total_orders": 0,
          "total_customers": 0,
          "average_order_value": 0
        },
        "expected": {
          "total_revenue": 0,
          "total_orders": 0,
          "total_customers": 0,
          "average_order_value": 0
        },
        "detail": "No nulls in mandatory columns.",
        "evidence_query": "SELECT COUNT(*) FROM gold_metrics WHERE total_revenue IS NULL",
        "extra": {
          "dimension": "completeness",
          "detection_layer": "layer_1_rules",
          "table": "gold_metrics"
        }
      },
      {
        "check_id": "L1-GOL-VAL-TOTA",
        "check_name": "Range Check: total_revenue",
        "layer": "Gold",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No invalid total_revenue values.",
        "evidence_query": "SELECT COUNT(*) FROM gold_metrics WHERE total_revenue < 0",
        "extra": {
          "dimension": "validity",
          "detection_layer": "layer_1_rules",
          "table": "gold_metrics"
        }
      },
      {
        "check_id": "L1-GOL-VAL-TOTA",
        "check_name": "Range Check: total_orders",
        "layer": "Gold",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No invalid total_orders values.",
        "evidence_query": "SELECT COUNT(*) FROM gold_metrics WHERE total_orders < 0",
        "extra": {
          "dimension": "validity",
          "detection_layer": "layer_1_rules",
          "table": "gold_metrics"
        }
      },
      {
        "check_id": "L1-GOL-VAL-TOTA",
        "check_name": "Range Check: total_customers",
        "layer": "Gold",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No invalid total_customers values.",
        "evidence_query": "SELECT COUNT(*) FROM gold_metrics WHERE total_customers < 0",
        "extra": {
          "dimension": "validity",
          "detection_layer": "layer_1_rules",
          "table": "gold_metrics"
        }
      },
      {
        "check_id": "L1-GOL-UNIQ-FULL",
        "check_name": "Full Row Duplicate Check",
        "layer": "Gold",
        "status": "PASS",
        "observed": 0,
        "expected": 0,
        "detail": "No full-row duplicates.",
        "evidence_query": "SELECT COUNT(*) - (SELECT COUNT(*) FROM (SELECT DISTINCT * FROM gold_metrics)) FROM gold_metrics",
        "extra": {
          "dimension": "uniqueness",
          "detection_layer": "layer_1_rules",
          "table": "gold_metrics"
        }
      },
      {
        "check_id": "L2-REC-REV",
        "check_name": "Revenue Reconciliation: Silver SUM vs Gold (within rounding tolerance)",
        "layer": "Gold",
        "status": "PASS",
        "observed": {
          "silver_revenue": 97000000.0,
          "gold_revenue": 97000000.0,
          "difference": 0.0,
          "revenue_rounding_tolerance": 1.0
        },
        "expected": {
          "difference": "<= 1.0 (reconciles within rounding tolerance of 1.0 currency unit(s) (float SUM drift; counts remain exact))"
        },
        "detail": "Silver revenue reconciles with Gold (reconciles within rounding tolerance of 1.0 currency unit(s) (float SUM drift; counts remain exact)).",
        "evidence_query": "SELECT SUM(net_revenue) FROM silver_orders",
        "extra": {
          "dimension": "accuracy",
          "detection_layer": "layer_2_reconciliation",
          "table": "gold_metrics",
          "revenue_rounding_tolerance": 1.0
        }
      },
      {
        "check_id": "L2-REC-AGG",
        "check_name": "Aggregate Cross-Check: Recompute Gold from Silver",
        "layer": "Gold",
        "status": "PASS",
        "observed": {
          "silver": {
            "revenue": 97000000.0,
            "orders": 72000,
            "customers": 5000
          },
          "gold": {
            "total_revenue": 97000000.0,
            "total_orders": 72000,
            "total_customers": 5000
          },
          "mismatched_fields": []
        },
        "expected": {
          "mismatched_fields": []
        },
        "detail": "All Gold aggregates match Silver recomputation (revenue within rounding tolerance).",
        "evidence_query": "SELECT SUM(net_revenue), COUNT(DISTINCT invoice_no), COUNT(DISTINCT customer_id) FROM silver_orders",
        "extra": {
          "dimension": "accuracy",
          "detection_layer": "layer_2_reconciliation",
          "table": "gold_metrics"
        }
      },
      {
        "check_id": "L3-ANO-GOLD_R",
        "check_name": "Robust Anomaly: Gold Revenue",
        "layer": "Gold",
        "status": "IMPACTED",
        "observed": {
          "value": 97000000.0,
          "median": 101800000.0,
          "iqr_lower": 101500000.0,
          "iqr_upper": 102100000.0,
          "modified_z": -32.38,
          "history_count": 15,
          "method": "median + IQR (Q1 - 1.5*IQR, Q3 + 1.5*IQR)",
          "detail": "Extreme outlier: modified Z=-32.38 (> 3.5) and outside IQR [1.015e+08, 1.021e+08]."
        },
        "expected": "within robust IQR band",
        "detail": "Extreme outlier: modified Z=-32.38 (> 3.5) and outside IQR [1.015e+08, 1.021e+08]. (Gold impacted by upstream Silver failure.)",
        "evidence_query": "SELECT total_revenue FROM gold_metrics",
        "extra": {
          "dimension": "accuracy",
          "detection_layer": "layer_3_robust_anomaly",
          "metric": "gold_revenue",
          "method": "median + IQR; modified Z (MAD)",
          "upstream_adjusted": true
        }
      }
    ],
    "cross_layer": [
      {
        "check_id": "X1",
        "check_name": "Source to Bronze Completeness",
        "layer": "Cross-Layer",
        "status": "PASS",
        "observed": "PASS",
        "expected": "PASS",
        "detail": "Source and Bronze row counts match.",
        "evidence_query": ""
      },
      {
        "check_id": "X2",
        "check_name": "Bronze to Silver Transformation Quality",
        "layer": "Cross-Layer",
        "status": "FAIL",
        "observed": "FAIL",
        "expected": "PASS",
        "detail": "Transformation quality issues in checks: ['S1', 'S8', 'S9', 'S10'].",
        "evidence_query": ""
      },
      {
        "check_id": "X3",
        "check_name": "Silver to Gold Metric Correctness",
        "layer": "Cross-Layer",
        "status": "PASS",
        "observed": "PASS",
        "expected": "PASS",
        "detail": "Silver-to-Gold metrics reconcile correctly.",
        "evidence_query": ""
      },
      {
        "check_id": "X4",
        "check_name": "First Failed Layer Locator",
        "layer": "Cross-Layer",
        "status": "FAIL",
        "observed": "Bronze \u2192 Silver",
        "expected": null,
        "detail": "First failed transition: Bronze \u2192 Silver.",
        "evidence_query": ""
      }
    ]
  }
}
```

### 2.3 Schema (top-level + nested)

| Key | Type | Layer / scope | Notes |
|-----|------|---------------|-------|
| `project` | `string` | Meta | Constant `"Aurum"` from `build_report()` |
| `description` | `string` | Meta | Constant framework description |
| `pipeline` | `string` | Meta | `"Raw ? Bronze ? Silver ? Gold"` |
| `dataset` | `string` | Meta | e.g. `"Retail Orders"` |
| `run_id` | `string` | Meta | e.g. `"demo_run_001"` |
| `layer_status` | `object` | Cross-layer rollup | Keys: `bronze`, `silver`, `gold` ? status strings |
| `layer_status.bronze` | `string` | Bronze | Layer rollup |
| `layer_status.silver` | `string` | Silver | Layer rollup |
| `layer_status.gold` | `string` | Gold | Layer rollup |
| `final_verdict` | `string` | Cross-layer | `TRUSTED` / `WARNING` / `NOT TRUSTED` |
| `severity` | `string` | Cross-layer | `LOW` / `MEDIUM` / `HIGH` |
| `first_failed_layer` | `string` or `null` | Cross-layer | e.g. `"Bronze ? Silver"` |
| `root_cause` | `object` | Cross-layer (Silver-focused) | Built from failed Silver checks |
| `root_cause.summary` | `string` | Silver / cross | Human summary |
| `root_cause.failed_check_ids` | `string[]` | Silver / cross | e.g. `["S1","S8",?]` |
| `root_cause.suspected_filter` | `string` or `null` | Silver | From S10 |
| `root_cause.evidence` | `object[]` | Silver / detection | Each: `check_id`, `detail`, `evidence_query` |
| `business_impact` | `object` | Cross-layer / Gold | Revenue gap |
| `business_impact.expected_revenue` | `number` | Bronze basis | Sum valid Bronze revenue |
| `business_impact.actual_revenue` | `number` | Gold | `gold_metrics.total_revenue` |
| `business_impact.estimated_loss` | `number` | Cross-layer | `expected - actual` |
| `business_impact.loss_percent` | `number` | Cross-layer | Percent loss |
| `business_impact.detail` | `string` | Cross-layer | Explanation text |
| `business_impact.status` | `string` | Cross-layer | Only when unavailable: `"NOT_AVAILABLE"` |
| `suggested_action` | `string` | Cross-layer | Remediation text |
| `coverage` | `object` | Cross-layer (Ring 4) | Honesty payload ? **present in current report, not read by Streamlit** |
| `coverage.total_checks` | `number` | Cross-layer | |
| `coverage.passed` | `number` | Cross-layer | |
| `coverage.warned` | `number` | Cross-layer | |
| `coverage.failed` | `number` | Cross-layer | |
| `coverage.impacted` | `number` | Cross-layer | |
| `coverage.skipped` | `number` | Cross-layer | |
| `coverage.skipped_details` | `object[]` | Cross-layer | `check_id`, `reason` |
| `coverage.full_coverage` | `boolean` | Cross-layer | |
| `coverage.verdict_caveat` | `string` | Cross-layer | Optional; when TRUSTED downgraded due to skips |
| `detection_layers` | `object` | Detection stack | Three arrays by Pain-1 layer |
| `detection_layers.layer_1_rules` | `CheckResult[]` | Bronze/Silver/Gold (per check) | Config-driven rule library |
| `detection_layers.layer_2_reconciliation` | `CheckResult[]` | Silver/Gold | Reconciliation checks |
| `detection_layers.layer_3_robust_anomaly` | `CheckResult[]` | Bronze/Silver/Gold | Anomaly checks |
| `checks` | `object` | Pipeline validators | Four arrays |
| `checks.bronze` | `CheckResult[]` | Bronze | B1?B8 + merged L1/L3 for Bronze |
| `checks.silver` | `CheckResult[]` | Silver | S1?S10 + merged L1/L2/L3 for Silver |
| `checks.gold` | `CheckResult[]` | Gold | G1?G6 + merged L1/L2/L3 for Gold |
| `checks.cross_layer` | `CheckResult[]` | Cross-layer | X1?X4 |

**`CheckResult` object shape** (from `src/contracts.py:CheckResult.to_dict()`):

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `check_id` | `string` | yes | e.g. `"S8"`, `"L2-REC-COUNT"` |
| `check_name` | `string` | yes | Display name |
| `layer` | `string` | yes | `"Bronze"` / `"Silver"` / `"Gold"` / `"Cross-Layer"` |
| `status` | `string` | yes | `PASS` / `WARN` / `FAIL` / `IMPACTED` / `SKIPPED` |
| `observed` | `any` | yes | Scalar, object, or array ? check-specific |
| `expected` | `any` | yes | Scalar, object, or string threshold |
| `detail` | `string` | yes | Human-readable result |
| `evidence_query` | `string` | no (default `""`) | SQL evidence |
| `extra` | `object` | no | Omitted when empty; may include `dimension`, `detection_layer`, `table`, `metric`, `method`, `segments`, etc. |

### 2.4 Fields: UI vs report.json mismatches

**In `report.json` but NOT read/rendered by Streamlit UI**

| Field | Present in current report? |
|-------|--------------------------|
| `project` | Yes ? ignored |
| `description` | Yes ? ignored |
| `pipeline` | Yes ? mapped in `FIELDS` but never passed to `get_field()` in render code |
| `run_id` | Yes ? mapped in `FIELDS` but never displayed |
| `severity` | Yes ? mapped in `FIELDS` but never displayed |
| `root_cause.failed_check_ids` | Yes ? mapped but never displayed directly |
| `root_cause.suspected_filter` | Yes ? mapped but never displayed directly |
| `coverage` (entire block) | Yes ? **not in `FIELDS` at all** |
| `checks.*` PASS rows | Present ? UI only surfaces FAIL/WARN/IMPACTED via `collect_failed_checks()` |
| `detection_layers.*` PASS rows | Present ? only used for metrics fallback and first L3 method sample |

**Referenced by Streamlit `FIELDS` / render logic ? all present in current `report.json`**

All keys used by `get_field()` in render paths exist in the dumped report. No UI field points at a missing top-level key.

**In report.json with statuses Streamlit does not surface**

| Status | In report? | UI behavior |
|--------|------------|-------------|
| `SKIPPED` | Yes (`L1-SIL-CONS-FK-CUST`) | Not collected by `collect_failed_checks()` (only FAIL/WARN/IMPACTED) ? invisible in UI |

---

## 3. Streamlit Render Map

Navigation is **session-state screens**, not Streamlit multipage tabs:

| Screen key | Function | Trigger |
|------------|----------|---------|
| `landing` | `render_landing()` | Default; "Back to Run" |
| `verdict` | `render_verdict()` | After run / view last report |
| `detail` | `render_detail()` | "View Details" from verdict |

### 3.1 Landing (`render_landing`)

| UI element | `report.json` fields | Display |
|------------|---------------------|---------|
| Header subtitle | `dataset` | `"{dataset} ? Data quality workflow"` |
| Intro paragraph | *(none)* | **Hardcoded** marketing copy |
| Pipeline grid (Source/Bronze/Silver/Gold) | *(none)* | **Hardcoded** `PIPELINE_STAGES` + actions Ingest/Validate |
| "Run Validation" button | *(none)* | Calls `run_engine_validation()` ? engine ? writes disk + session |
| Last report caption | filesystem | Shows `REPORT_PATH` string |
| "View last report" | disk `report.json` | `load_report_from_disk()` |

### 3.2 Verdict (`render_verdict`)

| UI element | `report.json` fields | Display |
|------------|---------------------|---------|
| Header subtitle | `dataset` | `"{dataset} ? Trust verdict"` |
| Trust verdict banner | `final_verdict` | Large banner text via `VERDICT_STYLES` |
| Bronze layer card | `layer_status.bronze` + derived metrics | Status label + row count + drop text |
| Silver layer card | `layer_status.silver` + derived metrics | Status label + row count + drop text |
| Gold layer card | `layer_status.gold` + derived metrics | Status label + row count + drop vs Silver |
| Business impact ? detail | `business_impact.detail` | Paragraph |
| Business impact ? Expected | `business_impact.expected_revenue` | **Derived:** `money_cr()` ? `?X.XX Cr` |
| Business impact ? Actual | `business_impact.actual_revenue` | **Derived:** `money_cr()` |
| Business impact ? Under-reported | `business_impact.estimated_loss` | **Derived:** `money_cr()` |
| Root cause | `root_cause.summary` | Paragraph |
| First failed layer caption | `first_failed_layer` | Caption text |

**Layer card metric derivation (`layer_metrics`) ? migration risks:**

| Layer | Row count source (fallback chain) | Drop / secondary text |
|-------|-----------------------------------|------------------------|
| Bronze | `checks.bronze[B1].observed` ? `detection_layers.layer_1_rules[L1-BRO-COMP-EMPTY].observed` | Literal `"baseline"` (**not from report**) |
| Silver | `detection_layers.layer_1_rules[L1-SIL-COMP-EMPTY].observed` ? `checks.silver[L1-SIL-COMP-EMPTY].observed` | `checks.silver[S1].observed` passed through `format_drop()` |
| Gold | `checks.gold[G2].observed` ? `detection_layers.layer_2_reconciliation[L2-REC-AGG].observed.gold.total_orders` | **Computed:** `(1 - gold_rows/silver_rows)*100` then `format_drop()` + `" vs Silver"` |

### 3.3 Detail (`render_detail`)

| UI element | `report.json` fields | Display |
|------------|---------------------|---------|
| Header subtitle | `dataset` | `"{dataset} ? Detection evidence"` |
| First failed layer | `first_failed_layer` | Bold line |
| Failed checks list (max 12) | Merged from `checks.{bronze,silver,gold,cross_layer}` + `detection_layers.{layer_1,2,3}` | Cards with name, status pill, detail, SQL |
| Check card title | `check_name` or `check_id` | Text |
| Check status pill | `status` | **Derived label:** WARN ? displays `"WARNING"` |
| "Caught by" tag | `extra.detection_layer` or **inferred from `check_id` prefix** | Rule Library / Reconciliation / Robust Anomaly |
| Check detail | `detail` or `root_cause.evidence[]` fallback | Paragraph |
| SQL block | `evidence_query` or `root_cause.evidence[].evidence_query` | `<pre>` code block |
| Reconciliation math bullets | `business_impact.{expected_revenue,actual_revenue,estimated_loss}` | **Derived:** `money_cr()` on each |
| Reconciliation caption | `checks.*` or `detection_layers.*` entry `L2-REC-REV` | `observed.difference`, `observed.revenue_rounding_tolerance` |
| Detection method | `detection_layers.layer_3_robust_anomaly[0].extra.method` | Info box; **fallback string** if missing |
| Suggested action | `suggested_action` | Plain text |

**`collect_failed_checks()` derivation ? migration risk:**

- Scans 7 arrays; keeps `status in ("FAIL","WARN","IMPACTED")`
- De-dupes by `check_id` (first wins)
- **SKIPPED checks never appear**
- Same `check_id` may exist in both `checks.*` and `detection_layers.*` ? only first section wins

**Explicit UI-side derivations (migration risks):**

1. `money_cr(value)` ? `float(value) / 10_000_000` formatted as `?{:.2f} Cr`
2. `format_int(value)` ? thousands separators
3. `format_drop(value)` ? strips `%`, rounds to integer %, optional `?` prefix
4. `layer_metrics()` ? multi-source fallbacks + Gold drop computed from Silver/Gold row counts
5. `collect_failed_checks()` ? merge 7 lists, filter statuses, de-dupe by `check_id`, cap at 12 in detail view
6. `detection_layer_for_check()` ? infers detection layer from `extra.detection_layer` or `check_id` prefix heuristics
7. `evidence_for_check()` ? falls back to `root_cause.evidence[]` when `evidence_query` empty
8. `STATUS_STYLES` ? maps `WARN` label to display string `"WARNING"`
9. Landing pipeline grid ? hardcoded stages, not `report.pipeline`

---

## 4. API Response Shapes

Source: `api/main.py` (committed Ring 3). Streamlit **does not call the API today**.

### `GET /health`

**Returns (200):**
```json
{"status": "ok", "database": "ok"}
```

**Returns (503 body, when DB unreachable):**
```json
{"status": "degraded", "database": "unreachable"}
```

Not a report shape. Never runs the engine.

### `POST /runs`

**Request body (optional):**
```json
{"run_id": "demo_run_001"}
```

**Returns (200):** full `build_report()` dict ? same top-level keys as `report.json`.

Handler (`api/main.py`):
```python
report = run_validation(run_id=run_id)
_last_report = report
return report
```

`run_validation()` does **not** write `reports/report.json` (side-effect-free core).

### `GET /reports/latest`

**Returns (200):** report dict from in-memory `_last_report` if set in this API process, else `json.loads(reports/report.json)` from disk.

**Returns (404):**
```json
{"detail": "No report available yet. Trigger a run via POST /runs."}
```

### `GET /reports/{run_id}`

**Returns (200):** same latest report dict when `report["run_id"] == run_id`.

**Returns (404):** no report, or id mismatch (v1 ? only latest stored).

### POST /runs vs GET /reports/latest

| Aspect | `POST /runs` | `GET /reports/latest` |
|--------|--------------|------------------------|
| Runs engine | Yes (synchronous ~5s) | No |
| Writes `report.json` | No | No (read cache/disk) |
| Updates API in-memory cache | Yes | No |
| Response shape | Full report dict | Full report dict (cached or disk) |
| `run_id` in body | Optional (default `demo_run_001`) | N/A |

When both come from the same engine run, shape is identical; only provenance differs.

### API report vs on-disk `report.json` ? byte identity

| Comparison | Result |
|------------|--------|
| **Top-level keys** | Identical set (15 keys in current report including `coverage`) |
| **Structure** | API returns `build_report()` dict unchanged (no reshaping in `api/main.py`) |
| **Byte-identical JSON** | **Not guaranteed** ? disk file is `json.dumps(report, indent=2, default=str)`; API serializes via FastAPI/Starlette JSON encoder. Same data, possible float/string formatting differences. |
| **Content after `POST /runs` vs disk** | Differs until `python src/run_demo.py` or Streamlit run writes disk ? API POST does not persist |
| **Ring 4 `coverage` block** | Present in current on-disk report (uncommitted Ring 4 work); API would include it once Ring 4 is deployed |

**Migration risk:** React must not assume `GET /reports/latest` equals last `POST /runs` unless cache/file sync is defined.

---

## 5. Dependencies & Config

### Python dependencies (frontend-relevant)

From `requirements.txt`:
```
streamlit==1.36.0
```

`app/streamlit_app.py` also imports:
- stdlib: `json`, `html`, `sys`, `pathlib`
- `streamlit.components.v1`

When "Run Validation" is clicked, UI imports engine modules:
- `src.data_loader.DataLoader`
- `src.report_builder.build_report`, `write_report`

### Hardcoded paths

| Constant | Value | File |
|----------|-------|------|
| `REPORT_PATH` | `<repo_root>/reports/report.json` | `app/streamlit_app.py:24` |
| `ROOT` | parent of `app/` | `app/streamlit_app.py:23` |

### Ports / URLs

| Service | Port | Documented in |
|---------|------|---------------|
| Streamlit default | **8501** (Streamlit default; not set in code) | README: `streamlit run app/streamlit_app.py` |
| FastAPI | **8000** | `api/main.py` comment, README |

**Streamlit has no API base URL, no env vars, no `.env` usage.**

### Environment variables

Streamlit UI reads **none**. Engine invoked from UI uses Postgres config from `src/db_config.py` (`AURUM_POSTGRES_*` or `DATABASE_URL`).

---

## 6. Open Questions

1. **Ring 4 `coverage` block:** Present in current `report.json` but invisible in Streamlit. Should React show coverage/skips, or parity-only with current UI?
2. **`SKIPPED` status:** In report (`L1-SIL-CONS-FK-CUST`) but filtered out of failed-check views. Show skips in React?
3. **Severity:** Emitted by engine (`HIGH` in demo) but never displayed in Streamlit. Include in React header?
4. **`run_id` / `pipeline` / `project` / `description`:** In report but unused by UI. Display in React metadata panel?
5. **Run trigger architecture:** Streamlit calls Python engine in-process (`run_engine_validation`). React should call `POST /runs` ? define loading/error UX for ~5s synchronous run.
6. **Report freshness:** After `POST /runs`, disk `report.json` is stale until `run_demo.py` or Streamlit run writes it. Will React use API only, or also expect a local file?
7. **Failed-check cap:** Detail screen shows `failed[:12]` only. Intentional limit for React?
8. **Duplicate `check_id` entries:** `L1-GOL-VAL-TOTA` appears 3? with different `check_name` in `detection_layers.layer_1_rules`. `collect_failed_checks()` de-dupes by id ? React needs same rule.
9. **Currency formatting:** UI hardcodes `?` and Crore (`/ 10_000_000`). Is this locale-specific forever?
10. **Ring 4 commit state:** Current `report.json` includes `coverage` from uncommitted Ring 4 worktree. Committed `main` report shape may differ until Ring 4 lands ? confirm baseline for React contract tests.
11. **`GET /reports/{run_id}` v1 limitation:** Only latest id works. Does React need history before Ring 5 Quality Store?
12. **Health endpoint:** Not used by Streamlit. Will React ops dashboard call `GET /health` separately from report views?
