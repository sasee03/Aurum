# Ring 4 Scope Recon

Read-only scoping for the PASS/FAIL/SKIPPED resilience wrap. **Baseline:** committed `main` at `bb7d2df29da9e7292d9dc9f8f0d1aeedbc4478ae` (14-key report, no `coverage`, no `SKIPPED`). **Worktree:** uncommitted Ring 4 code is present under `src/resilience.py`, modified validators, `tests/test_resilience.py`, and `reports/report.json` with a 15th `coverage` key.

---

## 1. THE TWO FAILURE MODES

### Search performed

| Search | Scope | Result |
|--------|-------|--------|
| `Ring 3 verification` + `malformed` + `crash` + `two failure` | `*.py`, `*.md` | **NOT FOUND** as a paired documented list in repo files |
| `crash` + `malformed` + `resilience` + `abort` | `src/`, `tests/` | Hits in Ring 4 code/tests (below) |
| Agent transcript (Ring 3 “Two Small Fixes” task, line 167) | conversation log | Documents **two Ring 3 verification bugs** — but they are **infrastructure**, not malformed-data engine crashes (health check truthfulness, schema leak on `DataLoader` construction) |

**Explicit answer:** The repo does **not** contain a written note that says “Ring 3 verification surfaced two malformed-data crash modes.” Ring 3 independent verification (transcript only — **not** a committed markdown file) documented **two different bugs**: lying `/health` and orphaned Postgres schemas on construction failure.

What **is** evidenced in the repo as concrete **malformed-data / bad-input** failure modes motivating Ring 4:

---

### Failure mode A — Uncaught exception in a check aborts the whole run

**Status:** Documented and reproduced in Ring 4 tests; present on `bb7d2df` without the resilience wrap.

**Where it crashes (committed `bb7d2df`):**

Validators invoke check functions **directly** with no per-check exception boundary. Example — `validate_bronze()`:

```python
# git show bb7d2df:src/bronze_validator.py (validate_bronze)
def validate_bronze(loader: DataLoader) -> list[CheckResult]:
    results = [
        b1_source_to_bronze_count(loader),
        b2_count_band(loader),
        ...
    ]
```

Same pattern on committed `validate_silver`, `run_rule_library`, `run_robust_anomaly_layer`, etc. — no `try/except` at orchestration level.

**Call chain when a check raises:**

```
src/run_demo.py run_validation() (102-114)
  → src/report_builder.py build_report() (85+)
    → validate_bronze / validate_silver / validate_gold / validate_cross_layer
    → run_detection_stack → run_rule_library / run_reconciliation_layer / run_robust_anomaly_layer
      → <individual check fn>()  # exception propagates uncaught
```

**Triggering input (documented test):**

`tests/test_resilience.py` `test_build_report_completes_when_a_check_throws` (141-156) monkeypatches `src.silver_validator.s5_quantity_positive` to raise `ValueError("bad data reached the check")`.

**Exception (without Ring 4 wrap):** `ValueError: bad data reached the check` — aborts `build_report()`; no report returned.

**With uncommitted Ring 4 wrap:** same injection yields `S5` → `SKIPPED`, report completes (`test_resilience.py` 153-156).

**Supporting spec text (Ring 4 task spec, conversation transcript — not a repo file):** “One check hitting bad data must never abort the run.”

---

### Failure mode B — Report assembly outside the check seam crashes on missing tables

**Status:** Documented in Ring 4 worktree comment + discovered during Ring 4 verification (transcript); **crash path exists on committed `bb7d2df`**.

**Where it crashes (committed `bb7d2df`):**

`src/report_builder.py` `build_report()` calls `build_business_impact(loader)` **after** validators, outside any check wrapper:

```python
# git show bb7d2df:src/report_builder.py
verdict = compute_final_verdict(layer_status)
root_cause = build_root_cause(silver_results)
business_impact = build_business_impact(loader)   # direct SQL, no table guard on bb7d2df
```

Committed `build_business_impact()` (`git show bb7d2df:src/cross_layer_validator.py`):

```python
def build_business_impact(loader: DataLoader) -> dict:
    expected = loader.scalar(
        f"SELECT COALESCE(SUM(quantity * unit_price), 0) "
        f"FROM bronze_orders WHERE {VALID_BRONZE_PREDICATE}"
    )
    actual = loader.scalar("SELECT COALESCE(total_revenue, 0) FROM gold_metrics")
```

No `loader.table_exists(...)` guard on `bb7d2df`.

**Triggering input:** `DataLoader` / `loader_from(...)` with `bronze_orders` present but **`gold_metrics` absent** (or `bronze_orders` absent). Ring 4 implementation notes this scenario explicitly:

```python
# src/cross_layer_validator.py lines 154-163 (uncommitted Ring 4)
def build_business_impact(loader: DataLoader) -> dict:
    # Report assembly (not a check) reads tables directly, so guard missing
    # tables here: without this an absent bronze/gold would crash the whole run.
    if not (
        loader.table_exists("bronze_orders") and loader.table_exists("gold_metrics")
    ):
        return {
            "status": "NOT_AVAILABLE",
            "detail": "Expected baseline not available (bronze_orders/gold_metrics missing).",
        }
```

**Exception (committed path, inferred from `DataLoader.scalar` → psycopg execute on missing relation):** Postgres error for undefined table (e.g. `psycopg.errors.UndefinedTable` — exact type not asserted in a committed test file; **NOT FOUND** as a pinned exception string in `tests/` on `bb7d2df`).

**Ring 4 verification note (transcript, not committed):** “The full-run on a loader missing `gold_metrics` exposed a gap: `build_business_impact()` … does raw DB I/O, so a missing table crashes the run.”

---

### Count: one or zero documented?

**Neither zero nor exactly the prompt’s framing.**

- **Zero** repo files label “Ring 3 verification → two malformed-data crashes.”
- **Two** concrete crash classes **are** evidenced for Ring 4 scope: **(A)** uncaught per-check exception, **(B)** `build_business_impact` report-assembly SQL on missing tables.
- Ring 3 verification’s **own** “two bugs” are different (health + schema leak) — see transcript, not `RING4_SCOPE` crash modes.

### Related non-crash “lie” mode (not a crash, but Ring 4-motivated)

On `bb7d2df`, committed `src/baseline.py` `classify_robust_anomaly()` with constant history and differing value:

```python
# git show bb7d2df:src/baseline.py
mad_z = modified_z_score(value, history)  # returns float("inf") when mad==0 and value!=median
...
elif abs(mad_z) > 3.5:
    status = "FAIL"   # false FAIL off degenerate math, not a crash
```

Ring 4 addresses this via `src/baseline.py` `classify_robust_anomaly()` (67-113, worktree) + `tests/test_resilience.py` `test_classify_constant_baseline_value_differs_is_warn_not_fail` (45-49).

---

## 2. THE CONTRACT DELTA (what Ring 4 adds to the report)

### Uncommitted Ring 4 code: **YES — present in worktree**

**Modified / new files (git status, not on `bb7d2df`):**

| File | Role |
|------|------|
| `src/resilience.py` | **NEW** — `run_checks`, `build_coverage`, `SKIPPED` helpers |
| `src/contracts.py` | Adds `SKIPPED`, extends `CHECK_STATUSES` |
| `src/verdict_engine.py` | Excludes `SKIPPED` from layer rollup |
| `src/report_builder.py` | Adds `coverage` key + verdict downgrade hook |
| `src/baseline.py`, validators, `rule_library.py`, etc. | Wrapped orchestration + edge guards |
| `tests/test_resilience.py` | **NEW** — 13 tests |
| `reports/report.json` | Regenerated with `coverage` |

---

### `CHECK_STATUSES` delta

**Committed `bb7d2df` (`git show bb7d2df:src/contracts.py`):**

```python
CHECK_STATUSES = (PASS, WARN, FAIL, IMPACTED)
```

**Worktree (`src/contracts.py` lines 14-24):**

```python
SKIPPED = "SKIPPED"
CHECK_STATUSES = (PASS, WARN, FAIL, IMPACTED, SKIPPED)
```

`CheckResult.__post_init__` (lines 77-81) validates against `CHECK_STATUSES` — on `bb7d2df`, emitting `SKIPPED` would raise `ValueError` before any report write.

---

### `SKIPPED` check shape (verbatim from on-disk report)

From `reports/report.json` lines 514-523 (`detection_layers.layer_1_rules` entry; same shape in `checks` sections):

```json
{
  "check_id": "L1-SIL-CONS-FK-CUST",
  "check_name": "Foreign Key Integrity: customer_id -> customers.customer_id",
  "layer": "Silver",
  "status": "SKIPPED",
  "observed": null,
  "expected": "check could not be evaluated",
  "detail": "table 'customers' not present -- FK check not applicable.",
  "evidence_query": ""
}
```

Programmatic builder — `src/resilience.py` `skipped_result()` (59-76):

```python
return CheckResult(
    check_id=check_id,
    check_name=check_name,
    layer=layer,
    status=SKIPPED,
    observed=None,
    expected="check could not be evaluated",
    detail=reason,
    evidence_query=evidence_query,
)
```

---

### `coverage` block shape (every key + type)

**Producer:** `src/resilience.py` `build_coverage()` (125-149).

**Attached in:** `src/report_builder.py` `build_report()` return dict key `"coverage"` (line 156).

**Verbatim from `reports/report.json` lines 79-93 (demo run — no `verdict_caveat` because `final_verdict` is `NOT TRUSTED`, not downgraded `TRUSTED`):**

```json
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
}
```

| Key | Type | Source lines |
|-----|------|--------------|
| `total_checks` | `int` | `len(results)` — resilience.py:141 |
| `passed` | `int` | `counts.get(PASS, 0)` — 142 |
| `warned` | `int` | `counts.get(WARN, 0)` — 143 |
| `failed` | `int` | `counts.get(FAIL, 0)` — 144 |
| `impacted` | `int` | `counts.get(IMPACTED, 0)` — 145 |
| `skipped` | `int` | `counts.get(SKIPPED, 0)` — 146 |
| `skipped_details` | `list[object]` | Each `{"check_id": str, "reason": str}` from `r.detail` — 134-137 |
| `full_coverage` | `bool` | `skipped == 0` — 148 |
| `verdict_caveat` | `str` (optional) | **Not in demo report.** Added at runtime only when downgrade fires — `report_builder.py` 132-135 |

**`verdict_caveat` template (worktree, conditional):**

```python
coverage["verdict_caveat"] = (
    f"Coverage incomplete: {coverage['skipped']} check(s) skipped; "
    "verdict downgraded from TRUSTED."
)
```

---

### Full `build_report()` return delta

**Committed `bb7d2df` — 14 top-level keys** (order from `git show bb7d2df:src/report_builder.py` return dict):

`project`, `description`, `pipeline`, `dataset`, `run_id`, `layer_status`, `final_verdict`, `severity`, `first_failed_layer`, `root_cause`, `business_impact`, `suggested_action`, `detection_layers`, `checks`

**Worktree — 15 top-level keys:** same 14 + **`coverage`** (inserted before `detection_layers` at `report_builder.py` line 156).

---

### If Ring 4 code did not exist (baseline only)

**NOT FOUND** for `coverage` / `SKIPPED` on `bb7d2df`.

Natural attachment point for a coverage summary (by call order in committed `build_report`):

```python
# git show bb7d2df:src/report_builder.py
verdict = compute_final_verdict(layer_status)          # line ~118
root_cause = build_root_cause(silver_results)        # ~119
business_impact = build_business_impact(loader)      # ~120
suggested_action = _suggested_action(...)            # ~121-123
return { ... }                                       # ~125 — coverage would slot here
```

All check results are in scope at that point: `bronze_results`, `silver_results`, `gold_results`, `cross_results` (assembled lines 88-116).

---

## 3. THE VERDICT-HONESTY PATH

### `compute_final_verdict()` — committed baseline (`bb7d2df`)

```python
# git show bb7d2df:src/verdict_engine.py
def compute_final_verdict(layer_status: dict) -> dict:
    values = list(layer_status.values())
    if FAIL in values:
        verdict, severity = NOT_TRUSTED, "HIGH"
    elif IMPACTED in values or WARN in values:
        verdict, severity = WARNING, "MEDIUM"
    else:
        verdict, severity = TRUSTED, "LOW"
    return {"final_verdict": verdict, "severity": severity}
```

**Worktree addition** — `compute_layer_status()` only (verdict function body unchanged):

```python
# src/verdict_engine.py lines 35-45
def compute_layer_status(check_results: Iterable) -> str:
    statuses = [s for s in _statuses(check_results) if s != SKIPPED]
    if not statuses:
        return PASS
    ...
```

`SKIPPED` is excluded from layer rollup; it does not flow into `compute_final_verdict()` inputs directly.

---

### Can skipped / incomplete coverage still yield a clean verdict today?

#### On committed `bb7d2df` (no Ring 4)

**Yes — multiple honesty gaps, no coverage signal.**

1. **Silent omission:** `git show bb7d2df:src/rule_library.py` `_check_consistency_fk` — missing FK target table → `continue` (no check row, no skip, no fail):

   ```python
   if not ref_table or not loader.table_exists(ref_table):
       continue
   ```

2. **No `SKIPPED` status** — cannot represent “could not evaluate” in the contract.

3. **No `coverage` block** — nothing in the 14-key report counts skipped/omitted checks.

4. **`compute_final_verdict`** only sees `layer_status` `{bronze, silver, gold}` — if remaining checks are all `PASS`, verdict is **`TRUSTED`** regardless of how many checks never ran.

5. **Anomaly insufficient history** on `bb7d2df` emits a **WARN** check (`L3-ANO-NOHIST`), not a skip — can yield `WARNING` verdict, not a coverage caveat.

**Nothing on `bb7d2df` prevents a half-evaluated run from looking clean** when omitted/skipped work leaves all layer rollups as `PASS`.

#### On uncommitted Ring 4 worktree

**Partially fixed — still possible to get `TRUSTED` with skips unless downgrade hook fires.**

Path:

1. Skipped checks excluded from `compute_layer_status` (verdict_engine.py 39).
2. If all non-skipped checks in a layer are `PASS`, layer status is `PASS` even when many checks were `SKIPPED`.
3. If all three layers `PASS` → `compute_final_verdict` → **`TRUSTED`** (report_builder.py 119-121).
4. **Downgrade hook** (report_builder.py **129-135**) — only when `final_verdict == TRUSTED` **and** `not coverage["full_coverage"]`:

   ```python
   if final_verdict == TRUSTED and not coverage["full_coverage"]:
       final_verdict = WARNING
       severity = "MEDIUM"
       coverage["verdict_caveat"] = (...)
   ```

5. If any non-skipped check is `FAIL`/`WARN`/`IMPACTED`, verdict is already `NOT TRUSTED` / `WARNING` — downgrade hook does not run; **`coverage.full_coverage: false` can coexist with `NOT TRUSTED`** (demo report: lines 12 vs 92).

**Remaining honesty gap on worktree:** skips with concurrent real `FAIL`s do not add `verdict_caveat`; reader must inspect `coverage` separately. Skips with all other checks `PASS` → downgraded to `WARNING` + caveat.

---

### Exact line where coverage caveat hooks in

**File:** `src/report_builder.py`  
**Function:** `build_report()`  
**Lines:** **129-135** (after `compute_final_verdict` / `build_coverage`, before `build_root_cause`)

```python
119:    verdict = compute_final_verdict(layer_status)
120:    final_verdict = verdict["final_verdict"]
121:    severity = verdict["severity"]
123:    coverage = build_coverage(
124:        bronze_results + silver_results + gold_results + cross_results
125:    )
129:    if final_verdict == TRUSTED and not coverage["full_coverage"]:
130:        final_verdict = WARNING
131:        severity = "MEDIUM"
132:        coverage["verdict_caveat"] = (
133:            f"Coverage incomplete: {coverage['skipped']} check(s) skipped; "
134:            "verdict downgraded from TRUSTED."
135:        )
```

**Not in `compute_final_verdict()` itself** — honesty downgrade is report-assembly policy in `report_builder`, not verdict-engine logic.

---

## Quick reference

| Question | Answer |
|----------|--------|
| Ring 3 verification “two malformed-data crashes” in repo? | **NOT FOUND** as stated; Ring 3’s two bugs were health + schema leak (transcript only) |
| Two crash modes evidenced for Ring 4? | **(A)** uncaught check exception aborts `build_report`; **(B)** `build_business_impact` SQL on missing tables |
| Ring 4 code in worktree? | **YES** — `src/resilience.py` + 15-key report |
| 15th key | `coverage` (+ optional `verdict_caveat` inside it) |
| New status | `SKIPPED` on `CheckResult.status` |
| Verdict honesty on `bb7d2df` | **No** — silent FK omit + no coverage |
| Verdict honesty hook (worktree) | `report_builder.py` **129-135** |
