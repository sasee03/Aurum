# Aurum API Contract

**Baseline commit:** `251586c` (`main`)

This document is the frontend pin for the React app. The engine decides; the API
returns the report dict verbatim with no reshaping.

## Endpoints

| Method | Path | Response | Notes |
|--------|------|----------|-------|
| `GET` | `/health` | `{ "status", "database" }` | **Not report-shaped.** Returns HTTP `503` with `status: "degraded"` when Postgres is unreachable. |
| `POST` | `/runs` | Full report dict (15 keys) | Body optional: `{ "run_id": "demo_run_001" }`. Synchronous (~5s). Does not write `reports/report.json`. |
| `GET` | `/reports/latest` | Full report dict | In-memory cache from last `POST /runs`, else on-disk `reports/report.json`. |
| `GET` | `/reports/{run_id}` | Full report dict | Returns latest only when `run_id` matches. Otherwise `404`. **Ring 5 history not built.** |

**Dev server:** `uvicorn api.main:app --port 8000`

**CORS (React/Vite):** `http://localhost:5173`, `http://127.0.0.1:5173`

## Report top-level keys (15)

```
project
description
pipeline
dataset
run_id
layer_status
final_verdict
severity
first_failed_layer
root_cause
business_impact
suggested_action
coverage
detection_layers
checks
```

## Check statuses

Allowed per-check `status` values:

- `PASS`
- `WARN`
- `FAIL`
- `IMPACTED`
- `SKIPPED`

Defined in `src/contracts.py` as `CHECK_STATUSES`.

## `coverage` shape

```json
{
  "total_checks": 0,
  "passed": 0,
  "warned": 0,
  "failed": 0,
  "impacted": 0,
  "skipped": 0,
  "skipped_details": [
    { "check_id": "...", "reason": "..." }
  ],
  "full_coverage": true
}
```

Optional when `final_verdict` was `TRUSTED` but checks were skipped:

```json
"verdict_caveat": "Coverage incomplete: N check(s) skipped; verdict downgraded from TRUSTED."
```

## `checks` nesting

```json
{
  "bronze": [ /* CheckResult dicts */ ],
  "silver": [ /* ... */ ],
  "gold": [ /* ... */ ],
  "cross_layer": [ /* ... */ ]
}
```

Each check dict includes at minimum: `check_id`, `check_name`, `layer`, `status`,
`observed`, `expected`, `detail`, and usually `evidence_query`.

## Ring 5 limitation

There is no Postgres report store. `GET /reports/{run_id}` only serves the
latest in-process (or disk fallback) report when the id matches.
