# AURUM BACKEND ERROR AND RECONCILIATION CONTRACT

**Version:** 1.0  
**Target:** Aurum Medallion Transformation Pipeline (Bronze, Silver, Gold)

---

## 1. Overview

This document specifies the internal error taxonomy, HTTP status mappings, state transition rules, and reconciliation contract for the Aurum backend.

All exceptions returned to clients are sanitized:
* No raw PostgreSQL exception text, SQL error messages, pool connection strings, or system paths are exposed to HTTP clients.
* Internal errors are logged server-side with context (`logger.error(...)`) while returning standardized HTTP status codes and detail messages.

---

## 2. Sanitized Internal Error Taxonomy

| Error Code / Message | HTTP Status | Pipeline Layer | Description & Handling |
| :--- | :---: | :---: | :--- |
| `LIVE_VALIDATION_UNAVAILABLE` | `503` | Core / Health | Database probe failed during `/health` or `POST /runs`. Client should check `/health`. |
| `DATABASE_UNAVAILABLE` | `503` | Core / Metadata | Postgres instance or connection pool unreachable or timed out (`db_connect_timeout`). |
| `SILVER_GENERATION_UNAVAILABLE` | `503` | Silver | Silver LLM generation disabled or untrusted (`SILVER_GENERATOR_TRUST`). |
| `GOLD_GENERATION_UNAVAILABLE` | `503` | Gold | Gold LLM generation disabled or untrusted (`GOLD_GENERATOR_TRUST`). |
| `UNTRUSTED_GENERATOR_PROVENANCE` | `400` | Silver / Gold | Generator provenance string is not in the trusted allowlist. |
| `RULE_REVISION_MISMATCH` | `400` | Silver | Rule set was modified between review generation and execution claim. |
| `EXECUTION_CLAIM_FAILED` | `409` | Silver / Gold | Atomic claim failed because run is not in `PENDING` state or another runner claimed it. |
| `SQL_SAFETY_VIOLATION` | `422` | Silver / Gold | SQL failed AST security validation (non-CTAS, unsafe DDL/DML, unexpected target schema). |
| `MISSING_REPLACEMENT_AUTHORITY` | `403` | Silver / Gold | Overwrite attempted on existing target table without prior `PROMOTED` identity authority. |
| `PERSISTED_IDENTITY_COORDINATE_MISMATCH` | `403` | Silver / Gold | Live target table OID/schema/kind does not match persisted identity authority. |
| `AMBIGUOUS_PROMOTION` | `409` / `500` | Silver / Gold | Promotion transaction outcome in PostgreSQL was disconnected before SQLite state update. |
| `REPORT_LOAD_FAILED` | `422` | Core | Stored report JSON is corrupted or invalid shape. |
| `CSV_SCHEMA_MISMATCH` | `422` | Datasets | Uploaded CSV headers do not match expected column contract. |

---

## 3. State & Reconciliation Matrix

Each transformation run progresses through an explicit state machine tracked in `generated_sql_review`:

```
 [PENDING] ---> [APPROVED] ---> [EXECUTING] ---> [PROMOTING] ---> [PROMOTED] (Terminal OK)
     |                             |                 |
     v                             v                 v
  [FAILED]                     [FAILED]      [AMBIGUOUS_PROMOTION] (Reconciliation Needed)
```

### State Contract Details

1. **`PENDING`**
   * **Terminal/Reconcilable:** Reconcilable (Initial state).
   * **Behavior:** SQL generated and stored. Awaiting approval or execution claim.
2. **`APPROVED`**
   * **Terminal/Reconcilable:** Reconcilable.
   * **Behavior:** Review revision verified against client payload.
3. **`EXECUTING`**
   * **Terminal/Reconcilable:** Transient / Non-terminal.
   * **Behavior:** Single atomic SQLite claim statement updated status from `PENDING` to `EXECUTING`. Executing candidate CTAS query in PostgreSQL `gold_candidates` / `silver_candidates`.
   * **Reconciliation:** If process crashes during execution, status remains `EXECUTING` or set to `FAILED`. Retrying claim returns `409 Conflict`.
4. **`PROMOTING`**
   * **Terminal/Reconcilable:** Transient / Non-terminal.
   * **Behavior:** Candidate SQL successfully executed; candidate OID and target OID stored. Atomic promotion DDL in progress.
5. **`PROMOTED`**
   * **Terminal/Reconcilable:** Terminal Success (`200 OK`).
   * **Behavior:** PostgreSQL transaction committed, target table created/swapped, and verified target OID persisted in `generated_sql_review`. Re-executing returns `200 OK` with existing attribution log.
6. **`AMBIGUOUS_PROMOTION`**
   * **Terminal/Reconcilable:** Reconciliation Required (`409 Conflict` / `500 Error`).
   * **Behavior:** PostgreSQL transaction may have committed, but client connection lost or SQLite status write failed.
   * **Reconciliation Procedure:**
     1. Query `GET /api/v1/silver/review/{run_id}` or `GET /api/v1/gold/review/{run_id}`.
     2. The endpoint inspects PostgreSQL catalog for `promoted_target_identity_json`.
     3. If target OID matches candidate OID, status is safely recovered to `PROMOTED`.
     4. If target table is missing or uncommitted, manual intervention or explicit `overwrite=true` re-execution is permitted.
7. **`FAILED`**
   * **Terminal/Reconcilable:** Terminal Failure.
   * **Behavior:** Execution or pre-commit promotion failed. Further automated execution attempts are rejected (`400 Bad Request`).
