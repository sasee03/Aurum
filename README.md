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
python src/generate_data.py     # writes synthetic retail data
python src/run_demo.py          # runs all checks, writes reports/report.json
```

`run_demo.py` regenerates data automatically if it is missing.

## Demo result

The synthetic dataset contains one planted bug: the Silver transformation also
drops valid high-quantity (wholesale) orders. Aurum catches it:

```
Bronze Quality: PASS
Silver Quality: FAIL
Gold Quality:   IMPACTED
First Failed Layer: Bronze -> Silver
Estimated Loss: Rs 0.48 Cr
Final Verdict: NOT TRUSTED
```

## Tests

```powershell
python -m pytest -q
```

## Architecture

```
src/
  contracts.py            CheckResult dataclass + status/verdict constants
  data_loader.py          DuckDB ETL: raw -> bronze -> silver(bug) -> gold
  generate_data.py        Deterministic synthetic retail dataset
  baseline.py             Learned tolerance bands (numpy mean/std)
  bronze_validator.py     B1-B8
  silver_validator.py     S1-S10 (S8-S10 detect wrongly-removed valid records)
  gold_validator.py       G1-G6 (reconciliation + revenue-vs-baseline IMPACTED)
  cross_layer_validator.py X1-X6 (first failed layer, root cause, impact)
  verdict_engine.py       compute_layer_status, compute_final_verdict
  report_builder.py       assembles reports/report.json
  run_demo.py             end-to-end runner + terminal summary

tests/                    pytest suite for every validator + the verdict engine
data/raw, data/historical synthetic CSV inputs
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
its modules at the repo root (`anomaly.py`, `verdict_engine.py`, `streamlit_app.py`,
`verify_demo.py`, `CONTRACT.md`, etc.). It is superseded by the `src/` framework
above and can be removed once the new direction is confirmed.
