# Aurum Codebase Map

## 1. One-line orientation

Aurum is a **deterministic data-quality engine** for a medallion pipeline (Raw → Bronze → Silver → Gold). It runs SQL-based checks on loaded data, rolls them into layer statuses, and outputs a single `reports/report.json` with a trust verdict: **TRUSTED**, **WARNING**, or **NOT TRUSTED**. **The engine decides** — rules, counts, reconciliation math, and robust statistics only; **there is no LLM in the decision path**. Anything that only displays or narrates that JSON (Streamlit UI, terminal summary, a future explain agent) **explains after** the decision; it never changes the verdict.

---

## 2. The map table

Scanned: `src/` (21 files), `app/` (1 file), `api/` (2 files). Tests, cache, and legacy root modules omitted.

Sorted: **DECIDES** → **EXPLAINS** → **NEITHER**.

| File | One-line: what it does | Role | ~lines |
|------|------------------------|------|--------|
| `src/bronze_validator.py` | Runs Bronze-layer catalogue checks (B1–B8): row counts, schema, nulls, duplicates on `bronze_orders` | **DECIDES** | 206 |
| `src/silver_validator.py` | Runs Silver-layer checks (S1–S10), including detecting valid rows wrongly removed and inferring a bad filter | **DECIDES** | 370 |
| `src/gold_validator.py` | Runs Gold-layer checks (G1–G6): reconciles metrics to Silver and flags IMPACTED when upstream Silver failed | **DECIDES** | 194 |
| `src/cross_layer_validator.py` | Runs cross-layer checks (X1–X4), locates first failed layer, builds `root_cause` and `business_impact` blocks from SQL | **DECIDES** | 176 |
| `src/rule_library.py` | Layer 1 Pain-1 rule library: config-driven completeness, validity, uniqueness, FK, and freshness checks per table | **DECIDES** | 385 |
| `src/reconciliation_layer.py` | Layer 2 Pain-1 reconciliation: unexplained row loss, revenue/key-set/aggregate cross-checks across layers | **DECIDES** | 227 |
| `src/robust_anomaly.py` | Layer 3 Pain-1 anomaly detection using median+IQR and modified Z/MAD on historical metrics | **DECIDES** | 122 |
| `src/verdict_engine.py` | Rolls check statuses into per-layer status and final `TRUSTED` / `WARNING` / `NOT TRUSTED` verdict | **DECIDES** | 48 |
| `app/streamlit_app.py` | 3-screen demo UI that reads `report.json` (or triggers the engine) and displays verdict, layers, impact, evidence — no check logic | **EXPLAINS** | 913 |
| `api/__init__.py` | Empty package marker for the HTTP API | **NEITHER** | 1 |
| `api/main.py` | FastAPI transport: `POST /runs` triggers engine, `GET /reports/latest` returns raw report JSON unchanged | **NEITHER** | 90 |
| `src/__init__.py` | Empty package marker for the engine | **NEITHER** | 1 |
| `src/baseline.py` | Shared math helpers: mean/std bands and robust IQR/MAD statistics used by validators | **NEITHER** | 121 |
| `src/bug_zoo.py` | Test harness that plants synthetic bugs and asserts Pain-1 layers catch them (not used in production runs) | **NEITHER** | 96 |
| `src/contracts.py` | Shared types and constants: `CheckResult` shape, status values (`PASS`/`FAIL`/…), layer names, verdict labels | **NEITHER** | 71 |
| `src/data_loader.py` | Loads CSV into Postgres (session schema), builds Bronze/Silver/Gold tables, exposes `query()` / `scalar()` | **NEITHER** | 442 |
| `src/db_config.py` | Reads Postgres connection settings from `DATABASE_URL` or `AURUM_POSTGRES_*` env vars | **NEITHER** | 45 |
| `src/detection_stack.py` | Orchestrates Layer 1 + 2 + 3 Pain-1 modules in order and groups results by pipeline layer | **NEITHER** | 35 |
| `src/generate_data.py` | Writes deterministic demo CSVs (`raw_orders`, `historical_runs`) with a planted Silver bug | **NEITHER** | 99 |
| `src/report_builder.py` | Wires all validators together, assembles final `report.json`, writes file; applies coverage downgrade rules | **NEITHER** | 159 |
| `src/resilience.py` | Wraps each check so exceptions become `SKIPPED` results; builds the `coverage` block — never aborts a run | **NEITHER** | 124 |
| `src/revenue_tolerance.py` | Named constant and wording for revenue rounding tolerance (float SUM drift) | **NEITHER** | 14 |
| `src/run_demo.py` | CLI entry: `run_validation()` calls engine; `main()` also writes JSON and prints human terminal summary | **NEITHER** | 103 |
| `src/table_specs.py` | Config dict `TABLE_SPECS`: per-table columns, keys, FKs, freshness windows for the rule library | **NEITHER** | 111 |

---

## 3. The 5 files that matter most

| # | File | Why a newcomer starts here |
|---|------|----------------------------|
| 1 | `src/report_builder.py` | **The spine** — `build_report()` is the only place that runs everything and defines what goes into `report.json`. |
| 2 | `src/verdict_engine.py` | **The final decision** — `compute_final_verdict()` turns layer statuses into TRUSTED / WARNING / NOT TRUSTED. |
| 3 | `src/silver_validator.py` | **The demo story** — S8–S10 detect the planted bug (24k wrongly dropped orders); most failures surface here. |
| 4 | `src/reconciliation_layer.py` | **Unknown-bug catching** — Layer 2 math (row loss, revenue, keys) flags problems without a bug-specific check. |
| 5 | `api/main.py` | **How the outside world calls the engine** — `POST /runs` → `run_validation()` → full report dict (same shape as the file). |

---

## 4. Where things live (quick reference)

| Want to change… | Look in… |
|-----------------|----------|
| **Final trust verdict** (TRUSTED / WARNING / NOT TRUSTED) | `src/verdict_engine.py` (`compute_final_verdict`); coverage downgrade in `src/report_builder.py` |
| **Report shape / JSON keys** | `src/report_builder.py` (`build_report` return dict); field types in `src/contracts.py` (`CheckResult`) |
| **Catalogue check rules** (B/S/G/X ids) | `src/bronze_validator.py`, `src/silver_validator.py`, `src/gold_validator.py`, `src/cross_layer_validator.py` |
| **Pain-1 rule library** (Layer 1) | `src/rule_library.py` + config in `src/table_specs.py` |
| **Cross-layer reconciliation** (Layer 2) | `src/reconciliation_layer.py` |
| **Robust anomaly detection** (Layer 3) | `src/robust_anomaly.py` + math in `src/baseline.py` |
| **Table/column/FK/freshness config** | `src/table_specs.py` |
| **Root cause / business impact text** | `src/cross_layer_validator.py` (`build_root_cause`, `build_business_impact`) |
| **Revenue rounding tolerance** | `src/revenue_tolerance.py` (used by `reconciliation_layer.py`, `gold_validator.py`) |
| **Data load + ETL + planted bug** | `src/data_loader.py` (`SILVER_ETL_SQL`), demo CSVs in `src/generate_data.py` |
| **Postgres connection** | `src/db_config.py`, env vars `DATABASE_URL` / `AURUM_POSTGRES_*` |
| **Check crash safety / SKIPPED** | `src/resilience.py` (`run_checks`, `build_coverage`) |
| **API endpoints** | `api/main.py` — `/health`, `POST /runs`, `GET /reports/latest`, `GET /reports/{run_id}` |
| **Demo UI** | `app/streamlit_app.py` (field paths in `FIELDS` dict at top of file) |
| **CLI run + terminal summary** | `src/run_demo.py` (`run_validation`, `print_summary`) |
| **On-disk report output** | `reports/report.json` (path constant `REPORT_PATH` in `src/report_builder.py`) |

---

## 5. Where an LLM would plug in

**Seam:** After `build_report()` finishes — consume the completed `report.json` dict.

- **Primary hook:** `GET /reports/latest` in `api/main.py` (returns the dict unchanged), or read `reports/report.json` from disk.
- **What an explain-only agent would read:** `final_verdict`, `layer_status`, `root_cause`, `business_impact`, `suggested_action`, `checks`, `detection_layers`, `coverage` — all already assembled; no re-running SQL required for narration.
- **What it must NOT do:** Import or call `validate_*`, `run_detection_stack`, `compute_final_verdict`, or any validator — those sit entirely upstream in `src/report_builder.py` → `run_validation()`.

**Confirmed from structure:** `app/streamlit_app.py` imports only `build_report` / `DataLoader` for the "Run Validation" button; display logic uses `get_field(report, …)` with no check math. `api/main.py` imports `run_validation` and returns the dict verbatim. No file under `src/` imports any LLM library. The decision path ends at `build_report()`; everything after is transport or display.

---

## 6. Is the file count a problem?

The split is **mostly reasonable**: each medallion layer has its own validator, Pain-1 has three clear layers plus a thin orchestrator, and shared concerns (`contracts`, `baseline`, `resilience`, `table_specs`) are separated from check logic. That matches the decide/explain boundary — validators decide; UI and API do not.

It can feel like "a lot of files" because the **same pattern repeats** (Bronze / Silver / Gold / cross-layer / rule library / reconciliation / anomaly), which is intentional for a framework, not accidental sprawl. The genuinely thin files are config/constants, not hidden logic.

**Optional merge suggestions only** (do not change without team agreement):

| Files | Note |
|-------|------|
| `src/revenue_tolerance.py` (14 lines) | Could live inside `reconciliation_layer.py` or `gold_validator.py` — purely a named constant + one helper string. |
| `src/detection_stack.py` (35 lines) | Could be inlined into `report_builder.py`, but keeping it separate documents the Pain-1 three-layer stack clearly. |
| `app/streamlit_app.py` (913 lines) | Large for one file; could split into `app/screens/` later for maintainability — still EXPLAINS-only either way. |

Do **not** merge validators across layers (e.g. Bronze + Silver into one file) — that would blur the medallion model without reducing real complexity.
