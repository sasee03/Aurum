# Aurum Check Catalogue

Reference list of every data quality check in the cross-layer framework.

- **Status values:** `PASS`, `WARN`, `FAIL`, `IMPACTED`
- **Layer status:** worst check in the layer (`FAIL` > `IMPACTED` > `WARN` > `PASS`)
- **Final verdict:** any `FAIL` -> `NOT TRUSTED`; any `WARN`/`IMPACTED` -> `WARNING`; else `TRUSTED`
- Every check returns the same `CheckResult` shape: `check_id`, `check_name`,
  `layer`, `status`, `observed`, `expected`, `detail`, `evidence_query`.

---

## MVP Priority Checks

Out of the full DQ catalogue, Aurum prioritizes these **five checks** for MVP and
demo. They were ranked by:

| Criterion | Why it matters |
|-----------|----------------|
| **Usage in real projects** | Checks teams actually run in production pipelines |
| **Data availability** | Runnable on our retail dataset without extra sources |
| **Automation scope** | SQL/count logic — no manual review, no LLM |
| **Demo value** | Directly supports the Raw → Bronze → Silver → Gold story |
| **Business impact** | Catches issues that distort revenue, orders, and trust |

### 1. Row Count / Volume Reconciliation

| | |
|---|---|
| **Layers** | Bronze, Silver, Gold, Cross-Layer |
| **Implemented as** | `B1`, `B2`, `S1`, `S2`, `G2`, `G3`, `X1`, `X2` |
| **Status** | Implemented |
| **Automation scope** | High — pure `COUNT(*)` and learned tolerance bands |
| **Demo relevance** | **Primary demo driver.** Bronze passes, but Silver shows an abnormal 28% drop; Aurum flags the failure at Bronze → Silver. `S8`/`S9`/`S10` extend this with wrongly-removed valid records. |

**Why it matters:** The most common DQ check in real projects. Detects missing,
excessive, or wrongly dropped records across layers.

**Expected explanation:** *"This check detects abnormal data loss or excess volume
across layers. In our demo, Bronze passes but Silver has an abnormal drop, so the
issue is detected at Bronze → Silver."*

---

### 2. Schema Arrival / Required Column Check

| | |
|---|---|
| **Layers** | Bronze |
| **Implemented as** | `B4`, `B5` |
| **Status** | Implemented |
| **Automation scope** | High — column list comparison against expected schema |
| **Demo relevance** | Bronze passes — incoming raw data has the expected structure before transformation. |

**Why it matters:** Ensures expected columns are present before any transformation.
Prevents silent downstream failures when a field is missing.

**Expected explanation:** *"This check verifies that incoming raw data has the
expected structure before transformation."*

---

### 3. Null / Required Field Validation

| | |
|---|---|
| **Layers** | Bronze, Silver |
| **Implemented as** | `B6`, `S4` (+ `S5`, `S6` for value constraints on key fields) |
| **Status** | Implemented |
| **Automation scope** | High — `COUNT(*) WHERE col IS NULL` per mandatory column |
| **Demo relevance** | Bronze and Silver pass null checks; the demo failure is record *loss*, not nulls. |

**Important fields:** `invoice_no`, `stock_code`, `quantity`, `unit_price`,
`invoice_date`, `customer_id`, `country`

**Why it matters:** Mandatory fields must be usable before Silver transformation
and Gold metric creation. Nulls in key columns break joins, aggregations, and
business metrics.

**Expected explanation:** *"This check verifies that key business fields are not
missing before they are used for Silver transformation or Gold metric creation."*

---

### 4. Duplicate / Key Uniqueness Check

| | |
|---|---|
| **Layers** | Bronze, Silver |
| **Implemented as** | `B8`, `S3` |
| **Status** | Implemented |
| **Automation scope** | High — composite-key `GROUP BY ... HAVING COUNT(*) > 1` |
| **Demo relevance** | Bronze and Silver pass; no duplicate inflation in the demo dataset. |

**Why it matters:** Duplicates inflate revenue, order count, and customer count in
Gold. A primary/composite key check is standard in ingestion and cleansing pipelines.

**Expected explanation:** *"This check ensures that duplicate records do not inflate
downstream Gold metrics."*

---

### 5. Gold Metric Reconciliation

| | |
|---|---|
| **Layers** | Gold |
| **Implemented as** | `G1`, `G2`, `G3`, `G4`, `G5` |
| **Status** | Implemented |
| **Automation scope** | High — recompute metrics from Silver and compare to Gold tables |
| **Demo relevance** | **Key demo nuance.** `G1`–`G4` pass (Gold math is correct), but `G5` marks Gold **IMPACTED** because Silver data is already damaged. |

**Examples:**
- Silver revenue = Gold revenue (`G1`)
- Silver distinct invoices = Gold total orders (`G2`)
- Silver distinct customers = Gold total customers (`G3`)
- AOV = revenue / orders (`G4`)
- Revenue vs learned baseline (`G5` → IMPACTED when upstream failed)

**Why it matters:** The most business-facing check. Validates whether final Gold
output can be trusted — even when the math reconciles, upstream damage can still
make the output untrustworthy.

**Expected explanation:** *"This check verifies that Gold metrics are correctly
calculated from Silver data. In our demo, Gold math reconciles, but Gold is marked
IMPACTED because Silver data is already damaged."*

---

### Priority → implementation map (quick reference)

| Priority | Theme | Check IDs |
|----------|-------|-----------|
| 1 | Row Count / Volume | `B1`, `B2`, `S1`, `S2`, `S8`, `S9`, `S10`, `G2`, `G3`, `X1`, `X2` |
| 2 | Schema / Required Columns | `B4`, `B5` |
| 3 | Null / Required Fields | `B6`, `S4`, `S5`, `S6` |
| 4 | Duplicate / Key Uniqueness | `B8`, `S3` |
| 5 | Gold Metric Reconciliation | `G1`, `G2`, `G3`, `G4`, `G5` |

> `S8`–`S10` are Silver extensions of Priority 1 — they detect *which* valid
> records were wrongly removed and infer the bad filter. They power the demo root
> cause but are grouped under volume reconciliation for prioritization purposes.

---

## Full catalogue

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
