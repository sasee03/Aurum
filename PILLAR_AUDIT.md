# Aurum Pillar Audit

> **HISTORICAL:** Audited at `bb7d2df` before Ring 4 shipped on `main` @
> `251586c`. Sections below that describe "uncommitted Ring 4" or a 14-key
> contract are outdated. See `docs/API_CONTRACT.md` for the current pin.

Read-only architecture audit against the 11 named diagram pillars. Evidence drawn from repository files at audit time. **HEAD commit:** `bb7d2df29da9e7292d9dc9f8f0d1aeedbc4478ae` (`feat: optional DATABASE_URL for remote SSL Postgres`).

> **Note:** The working tree contains uncommitted Ring 4 changes (`src/resilience.py`, `coverage` key in `src/report_builder.py`, `SKIPPED` in `src/contracts.py`). Part C2 reports the **committed** `build_report()` contract at HEAD unless stated otherwise.

---

## PART A: PER-PILLAR STATUS TABLE

| # | Pillar | STATUS | EVIDENCE | GAPS vs diagram |
|---|--------|--------|----------|-----------------|
| 1 | **Connector Layer** | **PARTIAL** | `src/data_loader.py` — class `DataLoader` (lines 186–221): connects via `psycopg.connect(postgres_conninfo())` (line 195). CSV ingest: `_load_from_disk()` (lines 247–276) reads `data/raw/raw_orders.csv` and `data/historical/historical_runs.csv` via `pd.read_csv`. Query API: `query()` (426–431), `scalar()` (433–437), `count()` (439–440). Remote Postgres: `src/db_config.py` — `postgres_conninfo()` (lines 47+) honors `DATABASE_URL`. | Diagram claims Snowflake/BigQuery/Databricks/DuckDB/S3 connectors with **read-only SQL and no source modification**. **NOT FOUND:** any `snowflake`, `bigquery`, `databricks`, `boto3`, or `s3://` import or connection code under `src/` or `api/` (grep across `*.py` — zero matches; names appear only in `docs/team_briefs.md` lines 72–73 and `docs/integration_reliability.md` line 70 as future/Q&A text). `DataLoader` **writes** session tables (`CREATE OR REPLACE TABLE`, `SILVER_ETL_SQL` lines 41–57, `build_silver()` 278–279, `build_gold()` 281–293) — not read-only. Legacy DuckDB connector exists only at repo root `data_loader.py` line 8 (`import duckdb`) — superseded per `docs/LEGACY.md` lines 3–7. |
| 2 | **Metadata Layer** | **IMPLICIT** | No file/class named Metadata*. Central config: `src/table_specs.py` — `TABLE_SPECS` dict (lines 18–116), `VALID_ROW_PREDICATE` (lines 13–16). Consumed by `src/rule_library.py` line 26 (`from .table_specs import TABLE_SPECS`), `run_rule_library()` iterates specs (394–420). Also consumed by `src/reconciliation_layer.py` line 25 (`VALID_ROW_PREDICATE`). Parallel hardcoded lists: `src/bronze_validator.py` — `REQUIRED_COLUMNS` (19–28), `MANDATORY_NOT_NULL` (30), used in `b4_required_columns()` (101–112) with `loader.columns("bronze_orders")` (102). Revenue metric: `gold_metrics` spec lines 85–99 (`total_revenue`, `reconcile_from: "silver_orders"`). | No discrete “Metadata Layer” module. Schema knowledge is **split** between `table_specs.py` (rule library) and per-validator constants (`bronze_validator.REQUIRED_COLUMNS`). Diagram example columns (`order_id`, `amount`, `discount_flag`, `order_date`, `status`) **do not appear** in `src/` validators — demo uses `invoice_no`, `quantity`, `unit_price`, `net_revenue`, `total_revenue` (grep `order_id` in `src/*.py` — only `src/generate_data.py` uses `order_id` as a loop counter for `invoice_no`, not as a table column). No runtime schema registry beyond `loader.columns()` introspection (462–465). |
| 3 | **Lineage Engine** | **DESIGN-ONLY** | Grep `lineage` across `*.py` — **NOT FOUND** (zero matches). Closest cross-layer logic is reconciliation SQL, not lineage tracing: `src/reconciliation_layer.py` `rec_revenue()` (114–144) compares `SUM(net_revenue)` from `silver_orders` to `total_revenue` from `gold_metrics`. `src/cross_layer_validator.py` `x3_silver_to_gold()` (71–82) rolls up gold check IDs `G1`–`G6` — no column mapping. `src/table_specs.py` `gold_metrics` entry has `"reconcile_from": "silver_orders"` (line 98) — config string only, no trace engine reads it. | Diagram claims `gold.<metric> <- silver.<col> <- bronze.<col>` tracing. **No code** builds or traverses a lineage graph. `first_failed_layer()` (cross_layer_validator 85–95) and `build_root_cause()` (111–151) narrate failure from **check rollups**, not metric lineage. |
| 4 | **Reconciliation Engine** | **MODULE** | `src/reconciliation_layer.py` — `run_reconciliation_layer()` (237–245). Checks: `rec_count_unexplained_loss()` (57–111), `rec_revenue()` (114–144), `rec_key_set()` (147–189), `rec_aggregate_crosscheck()` (192–234). Orchestrated via `src/detection_stack.py` `run_detection_stack()` line 36. Overlap: `src/gold_validator.py` `g1_revenue_reconciliation()` (29+), `g2_order_count_reconciliation()` (56+), etc. — pipeline-layer reconciliations separate from L2 detection IDs (`L2-REC-*`). | Implements bronze-vs-silver count, silver-vs-gold revenue, key-set, aggregate cross-check. Does **not** generalize to arbitrary warehouse tables; hardcoded to demo table names (`bronze_orders`, `silver_orders`, `gold_metrics`). |
| 5 | **Rule Engine** | **MODULE** (+ validators) | Layer 1 rules: `src/rule_library.py` — `run_rule_library()` (394–420), checks completeness/nulls/ranges/dates/uniqueness/FK/freshness/timeliness from `TABLE_SPECS`. Pipeline validators (additional rules): `src/bronze_validator.py` `validate_bronze()` (~218+), `src/silver_validator.py` `validate_silver()` (390+), `src/gold_validator.py` `validate_gold()` (201+). Anomaly rules: `src/robust_anomaly.py` `run_robust_anomaly_layer()`. Orchestration: `src/detection_stack.py` (32–38). | Covers schema/required columns/duplicates/nulls/freshness/valid-row-removal (e.g. `s8_valid_records_removed` silver_validator 253+). Not a single class named “Rule Engine”; split across `rule_library` + B/S/G validators + `robust_anomaly`. |
| 6 | **Root Cause Engine** | **IMPLICIT** | `src/cross_layer_validator.py` — `build_root_cause(silver_results)` (111–151): inspects failed Silver checks (`S8`, `S9`, `S10`), builds `summary`, `failed_check_ids`, `suspected_filter`, `evidence` list. Called from `src/report_builder.py` `build_report()` line 119 (committed HEAD: line 119 in `git show bb7d2df:src/report_builder.py`). `first_failed_layer()` (85–95) + `x4_first_failed_layer()` (98–108) locate first failed transition. Legacy **separate** module at repo root `root_cause.py` `find_root_cause()` (8–26) — superseded per `docs/LEGACY.md`; uses `order_id`/`has_discount` schema not used by `src/`. | No module named `root_cause_engine`. Logic is **Silver-centric** heuristics on check results, not a general causal-inference engine. `suspected_filter` originates from `src/silver_validator.py` `s10_wrong_filter_detection()` extra field (386). |
| 7 | **Business Impact Engine** | **IMPLICIT** | `src/cross_layer_validator.py` — `build_business_impact(loader)` (154–189): SQL `SUM(quantity * unit_price)` on valid bronze vs `total_revenue` from `gold_metrics`; returns `expected_revenue`, `actual_revenue`, `estimated_loss`, `loss_percent`. Called from `build_report()` (report_builder line 120 committed / line 138 worktree). Legacy root `impact.py` — superseded per `docs/LEGACY.md`. | No named module. Quantifies **revenue gap only** (not “orders missing” as a separate metric unless inferred from checks). No multi-metric impact model. |
| 8 | **Verdict Engine** | **MODULE** | `src/verdict_engine.py` — `compute_layer_status()` (35–45), `compute_final_verdict()` (48–56). Returns `TRUSTED` / `WARNING` / `NOT TRUSTED` + `severity`. Docstring line 4: “No LLM, no randomness”. Consumed in `src/report_builder.py` lines 118–120. Constants in `src/contracts.py` lines 32–40 (`TRUSTED`, `WARNING`, `NOT TRUSTED`). Legacy root `verdict_engine.py` `decide_verdict()` — `ALLOW PUBLISH` / `BLOCK PUBLISH` per `docs/LEGACY.md`. | Matches diagram verdict vocabulary on `src/` path. `_suggested_action()` in `report_builder.py` (68–82) is template strings, not verdict logic. |
| 9 | **Evidence Store** | **PARTIAL** | MVP file store: `src/report_builder.py` — `REPORT_PATH = Path("reports/report.json")` (line 33), `write_report()` (175–178). Written by `src/run_demo.py` `main()` line 121. API cache: `api/main.py` — `_last_report` global (32), set in `trigger_run()` (75–76), read in `_load_latest_report()` (39–44). | Diagram “Real: Postgres” **NOT FOUND** — grep `INSERT INTO.*report`, `Quality Store`, persistence layer in `src/*.py` — no Postgres report tables. `api/main.py` lines 96–98 explicitly defer per-run history to “Ring 5's Quality Store”. Evidence **queries** live on each `CheckResult.evidence_query` (`src/contracts.py` `CheckResult` dataclass ~64–83), not a separate evidence DB. Legacy `evidence.py` at repo root — superseded. |
| 10 | **Agent Layer** | **DESIGN-ONLY** | Grep `openai`, `anthropic`, `langchain`, `slack`, `jira`, `llm`, `gpt`, `claude` across `*.py` — **NOT FOUND** (zero matches). `README.md` line 13: “There is **no LLM in the decision path**.” `docs/check_catalogue.md` line 22: “no LLM”. Plain-language output is **deterministic templates**: `report_builder._suggested_action()` (68–82), `build_root_cause()` summary strings (cross_layer_validator 118–135), check `detail` fields from validators. | No agent, no Slack/Jira drafting, no explain-only LLM layer. Diagram requirement “Agent explains evidence; Rules and SQL decide verdict” is **half-implemented**: rules/SQL decide verdict; “explanation” is pre-written strings in report fields, not an agent. |
| 11 | **Aurum UI Dashboard** | **MODULE** | `app/streamlit_app.py` — docstring lines 1–7: reads `reports/report.json`, no detection logic. Field map `FIELDS` (31–58) maps verdict, layers, root cause, impact, checks. Renders pipeline/layer statuses via `layer_status`, `final_verdict`, `root_cause`, `business_impact`, `suggested_action`. Optional in-process run: `run_engine_validation()` (202–210) calls `build_report()` + `write_report()`. HTTP transport for future UI: `api/main.py` (FastAPI). | Single Streamlit file, not a separate “dashboard” package. Does not render Ring 4 `coverage` (not on committed HEAD). No React UI in repo. |

---

## PART B: DEEP DIVES ON THE 3 CONTESTED PILLARS

### B1. METADATA LAYER

**Verdict: IMPLICIT — no discrete metadata component; knowledge is centralized in config for Layer 1 rules and scattered in validators elsewhere.**

#### Where Bronze/Silver/Gold table knowledge is defined

| Location | What it defines | Lines |
|----------|-----------------|-------|
| `src/table_specs.py` | `TABLE_SPECS` entries for `raw_orders`, `bronze_orders`, `silver_orders`, `gold_metrics`, `order_payments` — `layer`, `mandatory_columns`, `primary_key`, `range_checks`, `foreign_keys`, `parent_table`, `reconcile_from` | 18–116 |
| `src/table_specs.py` | `VALID_ROW_PREDICATE` for reconciliation | 13–16 |
| `src/bronze_validator.py` | `REQUIRED_COLUMNS`, `MANDATORY_NOT_NULL`, `DUP_KEY` — **independent** of `TABLE_SPECS` | 19–32 |
| `src/data_loader.py` | ETL defines actual columns: `SILVER_ETL_SQL` selects `invoice_no`, `stock_code`, `quantity`, `unit_price`, `net_revenue`, etc. | 41–57 |
| `src/data_loader.py` | `build_gold()` defines `gold_metrics` columns: `total_revenue`, `total_orders`, `total_customers`, `average_order_value` | 281–293 |

#### Where metadata is consumed

| Consumer | Mechanism | Lines |
|----------|-----------|-------|
| `src/rule_library.py` | Iterates `TABLE_SPECS`; uses `spec["mandatory_columns"]`, `spec["layer"]`; introspects via `loader.columns(table)` in `_check_completeness_nulls` (63–64) | 394–420, 60–79 |
| `src/reconciliation_layer.py` | Uses `VALID_ROW_PREDICATE` constant | 25, 60, 67 |
| `src/bronze_validator.py` | `b4_required_columns`: compares `loader.columns("bronze_orders")` to hardcoded `REQUIRED_COLUMNS` | 101–112 |
| `src/gold_validator.py` | Hardcoded SQL against `gold_metrics.total_revenue`, `silver_orders.net_revenue` | 29–51 |
| `src/cross_layer_validator.py` | `build_business_impact`: hardcoded `bronze_orders`, `gold_metrics` | 164–168 |

#### Centralized vs scattered

- **Centralized (config-driven):** Layer 1 rule library only (`table_specs` → `rule_library`).
- **Scattered (hardcoded):** Bronze validator column lists, Silver/Gold validator SQL, cross-layer impact SQL, ETL in `data_loader`.

#### Hardcoded vs introspected

- **Introspected:** `DataLoader.columns(table)` (462–465) used in rule library null checks and bronze `b4`/`b5`.
- **Hardcoded:** Column names in SQL strings throughout validators; demo domain is retail invoices, not diagram’s `order_id` / `discount_flag`.

#### Diagram column examples vs repo

Grep `discount_flag`, `order_date` as mandatory metadata in `src/table_specs.py`:

- `invoice_date` — **present** (`mandatory_columns` lines 25, 42, 61).
- `order_id` — **NOT FOUND** as a column in `TABLE_SPECS` or bronze `REQUIRED_COLUMNS`.
- `amount` — only in `order_payments` spec (line 105), not core orders pipeline.
- `discount_flag` / `status` — **NOT FOUND** in `src/table_specs.py` or `src/bronze_validator.py`.

---

### B2. LINEAGE ENGINE

**Verdict: DESIGN-ONLY — no lineage engine; cross-layer relationships are enforced by reconciliation checks and check rollups, not by tracing `gold.<metric> <- silver.<col> <- bronze.<col>`.**

#### Search performed

```
grep -i lineage *.py  →  NOT FOUND (0 matches)
```

#### What exists instead (not lineage)

**1. Reconciliation equalities (Pain-1 Layer 2)**

`src/reconciliation_layer.py`:

```python
# rec_revenue() lines 117-118
silver_rev = float(loader.scalar("SELECT SUM(net_revenue) FROM silver_orders") or 0)
gold_rev = float(loader.scalar("SELECT total_revenue FROM gold_metrics") or 0)
```

This compares **aggregates** across layers; it does not record which silver column feeds which gold column.

**2. Config hint never executed as lineage**

`src/table_specs.py` line 98: `"reconcile_from": "silver_orders"` on `gold_metrics`. Grep `reconcile_from` in `src/*.py` — **only defined in `table_specs.py`**, not read by any other module.

**3. Cross-layer check rollups (narration, not trace)**

`src/cross_layer_validator.py`:

- `x2_bronze_to_silver()` (56–68): rolls up Silver check IDs `S1`, `S8`, `S9`, `S10`.
- `x3_silver_to_gold()` (71–82): rolls up Gold check IDs `G1`–`G6`.
- `first_failed_layer()` (85–95): maps `layer_status` dict to transition labels `"Source → Bronze"`, `"Bronze → Silver"`, `"Silver → Gold"`.

**4. Root cause path (failed-check evidence, not lineage)**

`build_root_cause()` (111–151):

```python
failed = [r for r in silver_results if r.status == FAIL]
s8 = _by_id(silver_results, "S8")
# ... builds summary from S8/S9/S10 check outcomes
evidence = [{"check_id": r.check_id, "detail": r.detail, "evidence_query": r.evidence_query} for r in failed]
```

**5. Business impact (two-endpoint SQL, not trace)**

`build_business_impact()` (164–168):

```python
expected = loader.scalar(
    f"SELECT COALESCE(SUM(quantity * unit_price), 0) "
    f"FROM bronze_orders WHERE {VALID_BRONZE_PREDICATE}"
)
actual = loader.scalar("SELECT COALESCE(total_revenue, 0) FROM gold_metrics")
```

Compares bronze-derived revenue expectation to gold `total_revenue` — no intermediate silver column mapping.

**Plain statement:** There is **no** code path that traces a metric across layers like `total_revenue (gold) ← net_revenue (silver) ← quantity * unit_price (bronze)`. Lineage is **implied** only by pipeline order and human-readable report fields (`first_failed_layer`, `root_cause.summary`).

---

### B3. CONNECTOR LAYER

**Verdict: PARTIAL — Postgres + local CSV are wired in `src/data_loader.py`; all other diagram sources are NOT CONNECTED in implementing code.**

| Diagram source | Status | Evidence |
|----------------|--------|----------|
| **Postgres** | **CONNECTED** | `src/data_loader.py` line 195: `psycopg.connect(postgres_conninfo(), autocommit=True)`. `src/db_config.py` `postgres_conninfo()` — local `AURUM_POSTGRES_*` or `DATABASE_URL`. `api/main.py` `health()` lines 56–58 probes Postgres. |
| **CSV** | **CONNECTED** | `src/data_loader.py` `_load_from_disk()` lines 261–266, 272–275: `pd.read_csv` on `data/raw/raw_orders.csv`, `data/historical/historical_runs.csv`. Materialized into Postgres session schema via `_materialize_frame()`. |
| **DuckDB** | **NOT CONNECTED (current `src/`)** | Root `data_loader.py` line 18: `duckdb.connect(database=":memory:")` — **legacy** per `docs/LEGACY.md`. `src/data_loader.py` line 122 docstring: `_translate_sql()` “Translate the small DuckDB SQL surface … to Postgres” — compatibility shim only, no DuckDB connection in `src/`. |
| **Snowflake** | **NOT CONNECTED** | Grep `snowflake` in `*.py` — **NOT FOUND**. Mentioned only in `docs/team_briefs.md` line 72, `docs/integration_reliability.md` line 70. |
| **BigQuery** | **NOT CONNECTED** | Grep `bigquery` in `*.py` — **NOT FOUND**. Same docs-only mentions. |
| **Databricks** | **NOT CONNECTED** | Grep `databricks` in `*.py` — **NOT FOUND**. Same docs-only mentions. |
| **S3** | **NOT CONNECTED** | Grep `s3://`, `boto3`, `aws` in `*.py` — **NOT FOUND**. |

#### Read-only vs modification

Diagram: “runs read-only SQL; no modification to source data.”

Actual `DataLoader` behavior:

- Creates ephemeral session schema (`_create_session_schema()` lines 224–227).
- Runs mutating DDL/DML on **session tables**: `CREATE OR REPLACE TABLE bronze_orders` (267), `SILVER_ETL_SQL` (278–279), `build_gold()` (281–293).
- Does not write back to CSV files or external warehouse — but connector is **not read-only** relative to the engine’s Postgres session.

#### Query surface

Validators call `loader.scalar()`, `loader.query()`, `loader.count()` — all execute SQL against the session schema (426–440). No federated query to external warehouses.

---

## PART C: BOUNDARY & CONTRACT CHECKS

### C1. Verdict decided by rules/SQL; no agent on decision path

#### Verdict computation site (authoritative `src/` path)

```
src/report_builder.py build_report()
  → compute_layer_status() per layer (lines 96-109 committed)
  → compute_final_verdict(layer_status) (lines 118-120 committed)
```

`src/verdict_engine.py` `compute_final_verdict()` (48–56):

```python
if FAIL in values:
    verdict, severity = NOT_TRUSTED, "HIGH"
elif IMPACTED in values or WARN in values:
    verdict, severity = WARNING, "MEDIUM"
else:
    verdict, severity = TRUSTED, "LOW"
return {"final_verdict": verdict, "severity": severity}
```

Pure function of `layer_status` dict derived from `CheckResult.status` values produced by SQL-backed validators.

#### Check → status path (examples)

| Step | File | Symbol | Lines |
|------|------|--------|-------|
| SQL evidence | `src/reconciliation_layer.py` | `rec_count_unexplained_loss()` | 59–84 |
| Status assignment | same | `status = PASS if unexplained == 0 else FAIL` | 84 |
| Layer rollup | `src/verdict_engine.py` | `compute_layer_status()` | 35–45 |
| Final verdict | `src/verdict_engine.py` | `compute_final_verdict()` | 48–56 |

#### LLM / agent influence on verdict

Grep across `*.py` for `openai`, `anthropic`, `langchain`, `llm`, `gpt`, `claude`, `slack`, `jira` — **NOT FOUND**.

**No LLM call sits on the verdict path.** Confirmed in `README.md` line 13 and `src/verdict_engine.py` docstring line 4.

#### Non-verdict “explanation” outputs (deterministic, not agent)

| Output | Producer | Verdict influence? |
|--------|----------|-------------------|
| `root_cause` | `build_root_cause()` cross_layer_validator 111–151 | **No** — assembled after `compute_final_verdict()` in `build_report()` |
| `suggested_action` | `_suggested_action()` report_builder 68–82 | **No** — template strings from `final_verdict` + `layer_status` |
| `business_impact` | `build_business_impact()` cross_layer_validator 154–189 | **No** — separate dict; not an input to `compute_final_verdict()` |
| Check `detail` strings | Individual validators | **Indirect only** — via check `status` (PASS/FAIL/WARN), not free-text override |

#### Streamlit boundary

`app/streamlit_app.py` lines 5–7: “This app NEVER implements detection logic.” `run_engine_validation()` (202–210) delegates to `build_report()` — same verdict path.

**Flag:** Legacy root modules (`verdict_engine.py`, `root_cause.py`, `impact.py`, `evidence.py`) implement a **different** prototype contract (`ALLOW PUBLISH` / `BLOCK PUBLISH`) per `docs/LEGACY.md`. They are **not** imported by `src/report_builder.py` or `api/main.py`.

**Worktree note:** Uncommitted `src/report_builder.py` lines 129–135 can **downgrade** `TRUSTED` → `WARNING` when `coverage["full_coverage"]` is false — still deterministic, not LLM.

---

### C2. Report keys from `build_report()` at HEAD `bb7d2df`

Source: `git show bb7d2df:src/report_builder.py` return dict (lines 125–153).

**14 top-level keys (committed contract):**

1. `project`
2. `description`
3. `pipeline`
4. `dataset`
5. `run_id`
6. `layer_status`
7. `final_verdict`
8. `severity`
9. `first_failed_layer`
10. `root_cause`
11. `business_impact`
12. `suggested_action`
13. `detection_layers` (nested: `layer_1_rules`, `layer_2_reconciliation`, `layer_3_robust_anomaly`)
14. `checks` (nested: `bronze`, `silver`, `gold`, `cross_layer`)

**Pillar mapping (informative):**

| Key(s) | Pillar(s) |
|--------|-----------|
| `checks`, `detection_layers` | Rule Engine, Reconciliation Engine (L2), robust anomaly |
| `layer_status`, `final_verdict`, `severity` | Verdict Engine |
| `first_failed_layer`, `root_cause` | Root Cause Engine (implicit) |
| `business_impact` | Business Impact Engine (implicit) |
| `suggested_action` | Agent-like text — **not** an agent; template in report_builder |
| (file write `reports/report.json`) | Evidence Store (MVP) |

**Not in committed contract:** `coverage` (uncommitted Ring 4 adds 15th key in worktree `src/report_builder.py` line 156).

`api/main.py` line 4 comment: “14 top-level keys” — matches HEAD.

---

## PART D: DIAGRAM-VS-REPO SUMMARY

**Real named modules:** Reconciliation Engine (`reconciliation_layer.py`), Rule Engine (`rule_library.py` plus B/S/G validators), Verdict Engine (`verdict_engine.py`), and Aurum UI Dashboard (`app/streamlit_app.py`). **Implicit capabilities folded into other files:** Metadata (`table_specs.py` + scattered validator constants), Root Cause and Business Impact (`cross_layer_validator.py`), and Connector behavior (`data_loader.py` as Postgres+CSV loader, not a multi-warehouse connector layer).

**Design-only on the diagram:** Lineage Engine (zero `lineage` references in code), Agent Layer (no LLM/Slack/Jira anywhere in `*.py`), and the “Real: Postgres” evidence store (only `report.json` plus an in-memory API cache exist today).

**Partial:** Connector Layer connects Postgres and local CSV only; Snowflake, BigQuery, Databricks, DuckDB (in `src/`), and S3 are documentation aspirations. Evidence Store is MVP file/json only.

**Single biggest gap:** The diagram’s **multi-warehouse read-only Connector Layer** and **Lineage Engine** do not exist in code — the repo runs a **Postgres session sandbox** fed from CSV, with cross-layer reasoning done via **SQL reconciliation checks and check-ID rollups**, not metric lineage graphs or external warehouse federation.
