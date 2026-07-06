# Aurum

**Cross-layer data quality validation framework** for a medallion ETL pipeline.

Aurum validates data quality across `Raw -> Bronze -> Silver -> Gold`, identifies
the first failed layer, explains the root cause with evidence, quantifies the
business impact, and returns a deterministic verdict:

```
TRUSTED  /  WARNING  /  NOT TRUSTED
```

There is **no LLM in the decision path**. Every check computes evidence from data
and returns a structured `CheckResult`; the verdict engine rolls those up with
deterministic rules.

## Quick Start

```powershell
python -m pip install -r requirements.txt
docker compose up -d              # Postgres (port 5433)
python -m src.generate_data       # downloads Olist CSVs if needed, writes raw_orders.csv
python -m src.run_demo            # runs all checks, writes reports/report.json
uvicorn api.main:app --port 8000  # HTTP API (POST /runs, GET /reports/latest)
streamlit run app/streamlit_app.py   # demo UI (reads report.json only)
```

`run_demo.py` regenerates data automatically if CSVs are missing. The API on port
8000 avoids clashing with Streamlit (8501); both run against the same Postgres.

**Data source:** [Olist Brazilian E-Commerce Public Dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce). Source CSVs download into `data/olist/` on first `generate_data` run (~120MB). Generated inputs (`data/raw/raw_orders.csv`, `data/historical/historical_runs.csv`) are gitignored.

## Demo result (Olist, frozen at commit `a94a2bb`)

The Olist line-item dataset contains one planted bug: the Silver transformation
also drops valid line items with `unit_price > 20` BRL. Aurum catches it:

```
Dataset:          Olist Brazilian E-Commerce
Bronze rows:      112,650 line items (~98,666 orders)
Bronze Quality:   PASS
Silver Quality:     FAIL
Gold Quality:       IMPACTED
First Failed Layer: Bronze -> Silver
Estimated Loss:     BRL 13.45 M
Final Verdict:      NOT TRUSTED
```

## MVP Check Prioritization

The full framework supports many quality checks, but the MVP focuses on the most
practical and high-impact checks first.

**Top checks:**

1. **Row Count / Volume Reconciliation** — detects missing, excessive, or wrongly
   dropped records across layers (`B1`, `B2`, `S1`, `S2`, `G2`, `G3`)
2. **Schema Arrival / Required Column Check** — verifies incoming raw data structure
   (`B4`, `B5`)
3. **Null / Required Field Validation** — ensures mandatory business fields are
   usable (`B6`, `S4`)
4. **Duplicate / Key Uniqueness Check** — prevents duplicate inflation of Gold
   metrics (`B8`, `S3`)
5. **Gold Metric Reconciliation** — validates final business metrics against Silver
   (`G1`–`G10`)

These checks were selected because they are widely used in real data projects, easy
to automate with available dataset fields, and directly support the Raw → Bronze →
Silver → Gold validation story.

See `docs/check_catalogue.md` for the full priority rationale, automation scope,
demo relevance, and mapping to every check ID.

### Demo story (what the priority checks prove)

```
Olist data lands correctly  →  Bronze passes (schema, nulls, volume OK)
Silver transformation wrongly removes high-price line items  →  Silver fails (S1, S8–S10)
Gold metrics built from damaged Silver  →  Gold IMPACTED (math OK, data not)
Aurum: first failed layer = Bronze → Silver, verdict = NOT TRUSTED
```

## Tests

```powershell
python -m pytest -q    # 101 passed (Olist demo contract)
```

## Architecture

```
src/
  olist_ingest.py         Download + join Olist CSVs → Aurum column model
  contracts.py            CheckResult dataclass + status/verdict constants
  data_loader.py          Postgres ETL: raw -> bronze -> silver(bug) -> gold
  generate_data.py        Build raw_orders.csv + historical_runs.csv from Olist
  baseline.py             Learned tolerance bands (numpy mean/std)
  bronze_validator.py     B1–B10
  silver_validator.py     S1–S10 (S8–S10 detect wrongly-removed valid records)
  gold_validator.py       G1–G10 (reconciliation + revenue-vs-baseline IMPACTED)
  cross_layer_validator.py X1–X4 (first failed layer, root cause, impact)
  verdict_engine.py       compute_layer_status, compute_final_verdict
  report_builder.py       assembles reports/report.json
  run_demo.py             end-to-end runner + terminal summary

tests/                    pytest suite (101 tests)
data/olist/               Olist source CSVs (downloaded, gitignored)
reports/report.json       generated output contract
```

### Status semantics

| Status     | Meaning                                                        |
|------------|---------------------------------------------------------------|
| `PASS`     | Check satisfied.                                               |
| `WARN`     | Outside tolerance but not a hard failure.                     |
| `FAIL`     | Check violated.                                                |
| `IMPACTED` | Layer math is correct but degraded by an upstream failure.    |

Layer status = worst check (FAIL > IMPACTED > WARN > PASS). Final verdict:
any `FAIL` -> `NOT TRUSTED`; any `WARN`/`IMPACTED` -> `WARNING`; else `TRUSTED`.

## Legacy

The previous release-gatekeeping iteration (`ALLOW/BLOCK` publish gate) still has
its modules at the repository root (`anomaly.py`, `verdict_engine.py`,
`streamlit_app.py`, `verify_demo.py`, `CONTRACT.md`, etc.). It is superseded by
the `src/` framework above. Its runner and verifier write `reports/legacy_report.json`;
the current framework exclusively owns `reports/report.json`. See `docs/LEGACY.md`.
