# Aurum — Frozen Output Contract

> **LEGACY / SUPERSEDED:** This contract belongs to the old release-gatekeeping
> implementation at the repository root. The current `src/` framework and
> `reports/report.json` use the TRUSTED / WARNING / NOT TRUSTED contract.
> Legacy commands write `reports/legacy_report.json`.

**Status: FROZEN.** This is the single source of truth for the backend output.
Every module emits into this shape; the dashboard reads only from this shape;
the Integration Lead validates against this shape.

- **Prakhar owns the DEFINITION** of this contract.
- **Haasya builds the dashboard to CONSUME** it.
- **Integration Lead validates CONFORMANCE** to it.

Authority rule: when a mismatch is found, the question is always *"which side disagrees with this contract?"* — never *"let's change the contract to match the code."* No field is renamed, added, or removed without Prakhar + Haasya sign-off.

This documents what `run_demo.py` already produces today (it matches
`docs/output_contract.md` line-for-line). It freezes reality; it does not invent
a new shape.

---

## The contract

```json
{
  "run_id": "today",
  "profile": {
    "bronze_count": 100000,
    "silver_count": 72000,
    "drop_pct": 28.0
  },
  "baseline": {
    "normal_drop_pct": 3.81,
    "std_dev": 0.032,
    "lower_bound": 3.71,
    "upper_bound": 3.91,
    "method": "mean +/- 3 std"
  },
  "anomaly": {
    "is_anomaly": true,
    "drop_today": 28.0,
    "deviation_sigma": 755.9,
    "severity": "CRITICAL"
  },
  "root_cause": {
    "cause": "Silver transformation wrongly filtered valid discounted orders",
    "dropped_rows": 24000,
    "evidence_ref": "missing_discounted_orders"
  },
  "impact": {
    "expected_revenue_cr": 10.18,
    "actual_revenue_cr": 9.7,
    "impact_cr": 0.48,
    "risk_level": "HIGH"
  },
  "evidence": [
    {
      "name": "Bronze order count",
      "sql": "SELECT COUNT(*) FROM bronze_orders;",
      "result": "100,000 rows",
      "meaning": "Total orders ingested in the raw layer."
    },
    {
      "name": "Silver valid count (today)",
      "sql": "SELECT COUNT(*) FROM silver_orders_buggy;",
      "result": "72,000 rows",
      "meaning": "Valid orders surviving the Silver transformation today."
    },
    {
      "name": "Gold revenue delta",
      "sql": "SELECT SUM(net_amount) FROM silver_orders_buggy;",
      "result": "Rs 9.70 Cr",
      "meaning": "Today's Gold revenue vs Rs 10.18 Cr expected = Rs 0.48 Cr short."
    }
  ],
  "verdict": {
    "decision": "BLOCK PUBLISH",
    "reasons": [
      "Bronze->Silver drop 28% vs learned normal 3.81% (+/- 3 std)",
      "Gold revenue Rs 0.48 Cr below expected",
      "Finance Board Dashboard impacted"
    ],
    "suggested_action": "Review the Silver transformation filter. The likely issue is that valid discounted orders are being excluded by the condition is_discounted == 0."
  }
}
```

---

## Field reference (who produces each block)

| Block | Owner | Notes |
|---|---|---|
| `run_id` | Prakhar | Run identifier. `"today"` for the demo run. |
| `profile` | Prakhar | Live counts + computed drop %. Never hardcoded. |
| `baseline` | Haasya | Learned from 15 historical runs (mean ± 3σ). Never hardcoded. |
| `anomaly` | Prakhar | Computed from profile vs baseline. `deviation_sigma` is derived (755.9), not a constant. |
| `root_cause` | Prakhar | `dropped_rows` derived by diffing correct vs buggy Silver. |
| `impact` | Haasya | Revenue values read from gold summary; `impact_cr` computed. `risk_level` set by impact size, not by the verdict (avoid circular dependency). |
| `evidence` | Haasya | Each block: `name`, `sql`, `result` (computed by running the SQL), `meaning`. |
| `verdict` | Prakhar | Deterministic decision + business-readable reasons. Includes `suggested_action`, a derived fix hint built from `root_cause` (not a hardcoded demo number). |

---

## Rules for consumers

**Dashboard (Haasya):**
- Read every value from this JSON. Never type a demo number into the UI.
- If a field is missing or the file won't parse, **fail loudly** (show an error) — never silently render stale or wrong values.
- Render order suggestion: verdict banner → profile (Bronze/Silver/drop) → normal-vs-today → root cause → impact → evidence table.

**Integration Lead:**
- Validate the dashboard reads each field above and that names match exactly.
- Validate every number appears identically in backend output AND dashboard.
- Report mismatches; do not fix field names yourself.

**Everyone:**
- No measured value (count, drop %, revenue, sigma, impact, dropped_rows) is a
  hardcoded literal anywhere — engine, dashboard, or evidence `result` strings.
  All are computed or read from CSV.

---

## Known cosmetic note (not a bug)

`deviation_sigma: 755.9` is the honest computed value `(28.0 - 3.81) / 0.032 ≈ 755.9`.
It is correct. In the **dashboard wording**, lead with the plain-English version
("today's 28% drop is far outside the normal 3.7–3.9% range") and keep the sigma
as supporting detail — 755σ reads as extreme to a non-technical viewer even though
it is mathematically right (the historical std is very small).
