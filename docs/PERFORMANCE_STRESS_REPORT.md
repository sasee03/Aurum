# Performance & Stress Report — Olist Harness

Measured on branch `perf/olist-stress-harness` against main baseline `42a8923`.
Harness scripts are standalone; core demo logic was not modified for this work.

## 1. Environment / repo baseline

| Item | Value |
|------|-------|
| Branch | `perf/olist-stress-harness` |
| Main baseline | `42a8923` |
| Dataset | Olist Brazilian E-Commerce |
| Raw rows | 112,650 |
| Pytest | 108 passed |
| Demo verdict | NOT TRUSTED |
| Estimated loss | 13,447,000.57 BRL |

Python 3.8.10 on Windows (`win32`). LLM/Ollama narrative calls were skipped or failed locally (connection refused); the deterministic validation path remained valid and non-fatal.

## 2. Pipeline benchmark

Command:

```bash
python scripts/benchmark_pipeline.py --runs 5 --output benchmark-results/pipeline-olist.json
```

### Repeated runs (5/5)

| Stage | Avg | Min | Max | Contract |
|-------|-----|-----|-----|----------|
| `generate_data` | 2.86s | 2.74s | 2.98s | OK |
| `run_demo` | 19.12s | 18.39s | 19.76s | OK |

All five repeated runs completed successfully (`returncode: 0`). Report contract validation passed on every run at 1× Olist scale.

Output written to `benchmark-results/pipeline-olist.json` (gitignored).

## 3. Scale sweep

In-process scale tests duplicate the Olist raw dataset without re-downloading source CSVs.

| Scale | Rows | Wall time | Contract |
|-------|------|-----------|----------|
| 1× | 112,650 | 6.97s | OK |
| 2× | 225,300 | 13.74s | OK |
| 5× | 563,250 | 32.47s | **Divergence** |

### Finding: 5× Gold layer status divergence

At 5× scale the pipeline completed in 32.47s but the report contract check failed:

- **Observed:** `layer_status.gold = WARN`
- **Expected (1× demo baseline):** `layer_status.gold = IMPACTED`

This is documented as a measurement finding for follow-up investigation. It does **not** indicate a bug to fix in the harness commit, and demo logic was intentionally left unchanged. Do not claim scale-invariant verdict behavior until this is understood.

## 4. API stress

API server:

```bash
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Stress command:

```bash
python scripts/stress_api.py --base-url http://127.0.0.1:8000 --requests 20 --concurrency 5 --output stress-results/api-olist.json
```

| Endpoint | Requests | Failures | Avg | P95 |
|----------|----------|----------|-----|-----|
| `GET /health` | 21 | 0 | 0.036s | 0.055s |
| `POST /runs` | 25 | 0 | 11.27s | 17.00s |
| `GET /reports/latest` | 40 | 0 | 0.011s | 0.026s |
| `GET /reports/stress_seq_*` | 20 | 0 | — | — |

- **Latest report consistency:** 20/20 consistent, 0 failures
- **Contract validations:** all sampled `POST /runs` and report fetches passed
- **Run IDs observed:** `stress_seq_001` … `stress_seq_020`

Output written to `stress-results/api-olist.json` (gitignored).

## 5. Bottlenecks

1. **Repeated report runs reload data into fresh in-memory DuckDB** — each `run_demo` / `POST /runs` cycle pays full load + ETL cost (~19s at 1×).
2. **`POST /runs` is synchronous and expensive under load** — p95 ~17s with concurrency 5; throughput is bounded by full pipeline execution per request.
3. **5× scale changes Gold status** — `IMPACTED` → `WARN` at 563k rows; needs separate investigation before treating verdict layers as scale-invariant.
4. **Ollama narrative path failed locally** — non-fatal; deterministic checks, BRL loss, and NOT TRUSTED verdict remain the valid baseline.

## 6. Recommendations

1. **Keep the deterministic validation path as the benchmark baseline** — contract checks on `reports/report.json` and layer validators, not LLM narrative latency.
2. **Cache or load Olist data more efficiently for repeated API runs** — avoid full DuckDB reload on every `/runs` if API throughput becomes a product requirement.
3. **Consider async or background execution for `POST /runs`** — return a run ID immediately and poll `/reports/{run_id}` to reduce client blocking under concurrency.
4. **Investigate 5× scale divergence separately** — understand why Gold flips from `IMPACTED` to `WARN` before extending scale claims or tuning thresholds.
5. **Do not optimize the demo path preemptively** — current 1× numbers are acceptable for the Olist demo; optimize only when product or CI gates require it.

## Harness files

| File | Role |
|------|------|
| `scripts/perf_contract.py` | Shared report contract assertions for benchmarks and stress |
| `scripts/benchmark_pipeline.py` | Repeated `generate_data` / `run_demo` timing and scale sweep |
| `scripts/stress_api.py` | Concurrent HTTP load against local FastAPI |

Generated artifacts (`benchmark-results/`, `stress-results/`, Olist source CSVs, `raw_orders.csv`, `historical_runs.csv`) are gitignored and must not be committed.
