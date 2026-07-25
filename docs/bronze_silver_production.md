# Production Bronze to Silver

## Public flow

1. Create a project with `POST /projects`.
2. Test and persist a same-database PostgreSQL connection with
   `POST /connectors/postgres/test`.
3. Ingest an allow-listed source table with
   `POST /api/v1/source/ingest-to-bronze`.
4. Save an explicit deterministic rule plan with
   `POST /api/v1/transform/rules`.
5. Materialize the server-issued ingest and exact current rule revision:

```json
{
  "ingest_id": "bronze_<server value>",
  "rule_revision": "<64-character server revision>"
}
```

`POST /api/v1/transform/materialize` accepts no physical relation, project,
connection, lineage, candidate, OID, or executable-SQL authority.

## Deterministic configured Silver rules

Production materialization reuses `table_rules`, canonical `rule_revision`,
the immutable `generated_sql_review` snapshot, the `p2_silver` AST policy,
reduced-role candidate execution, and exact-OID promotion.

Supported schema-agnostic rule objects are:

```json
{"type": "not_null", "column": "configured_column"}
{"type": "compare", "column": "configured_column", "operator": ">=", "value": 0}
{"type": "distinct"}
```

Configured columns are checked against the exact Bronze relation catalog.
The compiler adds no dataset or business-column assumptions.

Rule storage is intentionally schema-independent. When `ingest_id` binds a
plan to exact Bronze authority, materialization reads `pg_attribute`,
`pg_type`, and the type namespace for every non-dropped column before it
persists an executable run. The deterministic comparison contract is:

| PostgreSQL built-in type | JSON value | Operators |
| --- | --- | --- |
| `int2`, `int4`, `int8`, `numeric`, `float4`, `float8` | number, excluding boolean | `= != <> < <= > >=` |
| `text`, `varchar`, `bpchar` | string | `= != <> < <= > >=` |
| `bool` | boolean | `= != <>` |
| `uuid` | syntactically valid UUID string | `= != <> < <= > >=` |

Date/time, JSON/JSONB, arrays, domains, enums, and other custom or unsupported
types are rejected for `compare`. Aurum does not use implicit PostgreSQL casts
as rule validation. A structurally valid generic rule may therefore be saved,
but an incompatible exact Bronze binding returns HTTP 422 before creation of
`generated_sql_review`, execution claim, or candidate CTAS.

An explicit saved empty list is the zero-transformation plan. It compiles
through the same deterministic compiler, revision, review, AST, execution,
and promotion path. Absence of a saved plan is not treated as an empty plan.

The server persists the exact rule snapshot, revision, deterministic SQL,
project, connection, lineage, ingest ID, and six-field Bronze identity before
candidate mutation. A changed `table_rules` revision makes the old request
stale, and the atomic `PENDING → EXECUTING` claim rechecks the live revision.

Model/LLM Silver generation remains unavailable with HTTP 503. No LLM or
Ollama dependency participates in deterministic materialization.

## Bronze ingest operation lifecycle

`bronze_ingest_operations` truthfully records:

```text
CLAIMED
→ CREATING
→ COMMIT_IN_PROGRESS
→ READY
```

Failure outcomes are:

```text
FAILED_RETRYABLE
RECONCILIATION_REQUIRED
```

Ordering is:

```text
SQLite CLAIMED
  (database OID and source/Bronze namespace OIDs are immutable)
→ PostgreSQL source lock and exact source identity
→ SQLite CREATING
→ exact-authority replacement check
→ PostgreSQL Bronze create
→ exact provisional Bronze identity resolved inside the transaction
→ SQLite COMMIT_IN_PROGRESS with the six-field provisional identity
→ PostgreSQL commit attempt
→ SQLite READY publication
```

The previous READY authority is superseded only in the final atomic SQLite
READY publication. A failed new ingest therefore does not invalidate the
previous authority.

Before that transaction begins, persisted source and provisional Bronze
identities are validated against the immutable operation database OID,
namespace OIDs, schema names, relation names, and supported relation kinds.
Any structurally valid but coordinate-inconsistent evidence moves the new
operation to `RECONCILIATION_REQUIRED`; the prior READY authority remains
untouched. Reconciliation applies the same validation before catalog access or
READY publication.

Known rollback becomes `FAILED_RETRYABLE`. Commit acknowledgement uncertainty
or rollback acknowledgement uncertainty becomes `RECONCILIATION_REQUIRED`.
Failure to persist READY after an acknowledged PostgreSQL commit leaves
`COMMIT_IN_PROGRESS` with the exact provisional OID.

`POST /api/v1/source/ingest-reconcile/{ingest_id}` is read-first:

- exact provisional OID exists and matches after lock: publish `READY`;
- exact OID is absent: `FAILED_RETRYABLE`;
- same name with another OID: preserve it and remain
  `RECONCILIATION_REQUIRED`.

Names are never adopted as ownership proof.

## Execution and idempotency

Candidate execution performs:

```text
exact Bronze lock/revalidation
→ whole-relation type validation
→ SET LOCAL search_path = pg_catalog
→ SET LOCAL ROLE aurum_generated_sql
→ deterministic CTAS
→ RESET ROLE
→ trusted ownership handoff
→ exact candidate identity
→ exact-OID promotion
→ strict PROMOTED final identity
```

`(ingest_id, rule_revision, server deterministic provenance)` identifies one
materialization request. Concurrent duplicate calls create at most one run.
An in-progress duplicate receives a non-destructive conflict; a repeated
PROMOTED request returns the existing result. `FAILED` is terminal for that
exact request, and `AMBIGUOUS_PROMOTION` requires reconciliation rather than
blind DDL retry.
