# Aurum Check Catalogue

Reference list of every data quality check in the cross-layer framework.

- **Status values:** `PASS`, `WARN`, `FAIL`, `IMPACTED`
- **Layer status:** worst check in the layer (`FAIL` > `IMPACTED` > `WARN` > `PASS`)
- **Final verdict:** any `FAIL` -> `NOT TRUSTED`; any `WARN`/`IMPACTED` -> `WARNING`; else `TRUSTED`
- Every check returns the same `CheckResult` shape: `check_id`, `check_name`,
  `layer`, `status`, `observed`, `expected`, `detail`, `evidence_query`.

"MVP" marks the P0 checks implemented and wired into `run_demo.py` today. All
checks below are implemented in this MVP.

## Bronze (`src/bronze_validator.py`)

| ID | Check | What it verifies | MVP |
|----|-------|------------------|-----|
| B1 | Source to Bronze Row Count | `count(source) == count(bronze)` | Yes |
| B2 | Low / High / Normal Count | Bronze count inside learned (mean +/- 3 std) or configured band | Yes |
| B3 | Empty Table Check | `count(bronze) > 0` | Yes |
| B4 | Required Columns Present | All required retail columns exist | Yes |
| B5 | Extra / Missing Columns | Reports `missing_columns` / `extra_columns` | Yes |
| B6 | Null Count per Mandatory Column | No nulls in mandatory columns | Yes |
| B7 | Negative Value Profiling | Profiles negative quantity/price (WARN, not blocking) | Yes |
| B8 | Duplicate Check | Full-row + business-key duplicate detection | Yes |

## Silver (`src/silver_validator.py`)

| ID | Check | What it verifies | MVP |
|----|-------|------------------|-----|
| S1 | Bronze to Silver Drop Percentage | Drop vs learned/configured tolerance | Yes |
| S2 | Expected Drop Check | Actual drop vs expected min/max window | Yes |
| S3 | Deduplication Count Check | Dedup removals are explainable; no dups remain | Yes |
| S4 | Mandatory Columns Not Null | No nulls in Silver key columns | Yes |
| S5 | Quantity > 0 | No `quantity <= 0` rows remain | Yes |
| S6 | Unit Price > 0 | No `unit_price <= 0` rows remain | Yes |
| S7 | Revenue Not Negative | `net_revenue >= 0` for all rows | Yes |
| S8 | Valid Record Wrongly Removed | Valid Bronze records missing from Silver (hero check) | Yes |
| S9 | Record-Loss by Segment | Per-segment loss %, surfaces worst segment | Yes |
| S10 | Wrong Filter Detection | Infers the bad filter from missing valid records | Yes |

## Gold (`src/gold_validator.py`)

| ID | Check | What it verifies | MVP |
|----|-------|------------------|-----|
| G1 | Revenue Reconciliation | `sum(silver.net_revenue) == gold.total_revenue` | Yes |
| G2 | Order Count Reconciliation | `count_distinct(invoice_no) == gold.total_orders` | Yes |
| G3 | Customer Count Reconciliation | `count_distinct(customer_id) == gold.total_customers` | Yes |
| G4 | Average Order Value Check | Gold AOV matches recomputed AOV | Yes |
| G5 | Revenue vs Expected Baseline | Below baseline + correct math -> `IMPACTED` | Yes |
| G6 | Country-wise Revenue Reconciliation | Per-country revenue matches Silver | Yes |

## Cross-Layer (`src/cross_layer_validator.py`)

| ID | Check | What it verifies | MVP |
|----|-------|------------------|-----|
| X1 | Source to Bronze Completeness | Rolls up B1/B3 | Yes |
| X2 | Bronze to Silver Transformation Quality | Rolls up S1/S8/S9/S10 | Yes |
| X3 | Silver to Gold Metric Correctness | Rolls up G1/G2/G3 | Yes |
| X4 | First Failed Layer Locator | Locates first failed transition | Yes |
| X5 | Root Cause Builder | Builds root cause from failed Silver checks | Yes |
| X6 | Business Impact Builder | Expected vs actual revenue, estimated loss | Yes |

> X5 and X6 are produced as report sections (`root_cause`, `business_impact`)
> rather than as standalone `CheckResult` rows.
