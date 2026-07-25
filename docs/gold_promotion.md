# Gold promotion contract (Batch 4.5C)

Batch 4.5C promotes only the exact ordinary PostgreSQL table captured by the
approved Batch 4.5B execution into the exact approved Gold target. Production
Gold generator trust remains disabled; this contract is exercised only through
the existing injectable test trust seam until Batch 5.

## State and mutation authority

`PROMOTING` initially contains the immutable approval, execution claim, and
exact candidate identity. A SQLite `BEGIN IMMEDIATE` compare-and-set adds one
server-generated `promotion_claim_id` and timestamp. A second request cannot
replace that claim. Claimed `PROMOTING` and `AMBIGUOUS_PROMOTION` requests run
read-first reconciliation; they never launch another DDL attempt.

Legal terminal metadata is:

- `PROMOTED`: claim, exact candidate-derived final target identity, proof
  timestamp, no failure code, and (for overwrite) the exact backup identity.
- `PROMOTION_FAILED`: claim and sanitized deterministic failure code, with no
  final or backup identity and no commit proof.
- `AMBIGUOUS_PROMOTION`: claim, no success/failure assertion, and optional
  pre-commit-observed backup identity sufficient for reconciliation.

`promotion_committed_at` records when Aurum received commit acknowledgement or
proved the committed result through reconciliation. It does not claim to be
the PostgreSQL server's physical commit instant.

## Target advisory lock

Every promotion and reconciliation takes
`pg_advisory_xact_lock(bigint)` for its logical target. The signed 64-bit key is
the first eight bytes of SHA-256 over this canonical tuple:

```text
[
  "aurum-gold-promotion-lock-v1",
  approved database OID,
  approved target namespace OID,
  approved target schema,
  approved target relation name
]
```

The derivation is deterministic across processes and independent of Python
`hash()`. A 64-bit collision can only over-serialize unrelated targets:
candidate and target authority is revalidated independently after the lock, so
the key is never ownership proof. The transaction-scoped lock is released by
commit/rollback and cannot leak through a pooled session.

## PostgreSQL transaction and lock order

Promotion uses one connection from the bounded `aurum_promotion` pool and one
transaction:

```text
transaction-local search_path = pg_catalog
→ target advisory lock
→ database and namespace OID revalidation
→ candidate resolution
→ candidate ACCESS EXCLUSIVE lock
→ candidate full identity revalidation
→ target resolution
→ existing target ACCESS EXCLUSIVE lock (when approved)
→ target full identity revalidation
→ identifier-safe metadata DDL
→ final target and backup OID verification
→ COMMIT
```

All identifiers use `psycopg.sql.Identifier`. The candidate comparison binds
database, namespace, relation OID, schema, name, and `relkind = 'r'`. An
approved absent target must remain absent. An approved existing target must
remain the same ordinary table and overwrite must be explicitly persisted.

## Metadata sequences and OID lineage

Absent target:

```text
ALTER TABLE candidate SET SCHEMA target_schema  # only when schemas differ
ALTER TABLE target_schema.candidate RENAME TO target_name
```

Existing target with explicit overwrite:

```text
ALTER TABLE target RENAME TO unique_server_backup
ALTER TABLE candidate SET SCHEMA target_schema  # only when schemas differ
ALTER TABLE target_schema.candidate RENAME TO target_name
```

PostgreSQL documents `RENAME` and `SET SCHEMA` as `ALTER TABLE` operations on
an existing table, while `pg_class.oid` is the relation catalog row identifier:
[ALTER TABLE](https://www.postgresql.org/docs/current/sql-altertable.html) and
[pg_class](https://www.postgresql.org/docs/current/catalog-pg-class.html).
The implementation does not rely on documentation alone: before commit it
re-resolves the final name and requires the original candidate OID, and for an
overwrite it requires the original target OID at the exact backup location.
This is code/static and isolated-test proof, not live mutating PostgreSQL proof.

## Commit classification and reconciliation

The implementation distinguishes `PRE_MUTATION`, `TRANSACTION_BODY`,
`COMMIT_IN_PROGRESS`, `COMMIT_ACKNOWLEDGED`, and
`POST_COMMIT_POOL_CLEANUP`.

- Any error before `COMMIT` is sent is known not committed and becomes
  `PROMOTION_FAILED` after SQLite persistence.
- Any error while `COMMIT` acknowledgement is pending becomes
  `AMBIGUOUS_PROMOTION`.
- A successful commit remains successful if only later pool return fails.
- A proven PostgreSQL commit followed by SQLite failure leaves the durable
  claim in place and records ambiguity where possible. A retry reconciles; it
  does not rerun DDL.

Reconciliation obtains the same target advisory lock and resolves the original
candidate and target OIDs directly from `pg_class`. It proves:

- promoted only when the candidate OID is the exact final target, and, for
  overwrite, the original target OID is the exact backup;
- not committed only when the exact candidate and approved target state are
  both intact;
- otherwise ambiguous, with no DROP, rename, restore, overwrite, or retry.

## Least privilege & role topology

Batch 4.5B and 4.5C transfer candidate ownership to `aurum_promotion` inside the CTAS
transaction using `SET LOCAL ROLE aurum_generated_sql` for creation and `RESET ROLE`
for single-transaction ownership handoff. `aurum_generated_sql` remains `NOINHERIT`. Role membership uses
the live-proven single-deployment topology:
`GRANT aurum_generated_sql TO aurum_promotion WITH ADMIN OPTION FALSE, INHERIT TRUE, SET OPTION TRUE;`.

`INHERIT TRUE` is required so `aurum_promotion` can assume candidate table ownership during single-transaction ownership handoffs (`ALTER TABLE ... OWNER TO aurum_promotion`) without requiring elevated superuser permissions or secondary connection pools. Direct `SET ROLE aurum_promotion` from `aurum_generated_sql` is rejected by PostgreSQL.

Furthermore, the AST structural safety gate enforces catalog-backed source-type checking and strict built-in function policies:
- Physical source relations in both Silver and Gold execution paths are verified against `pg_catalog` before CTAS execution.
- Source columns must be built-in base types (`typtype = 'b'` in `pg_catalog`, e.g. `int4`, `text`, `bool`). Custom domains, enums, composites, ranges, and extension types fail closed.
- All session-altering (`set_config`, `set_user`, etc.), privilege-probing, advisory-locking, and server side-effect function calls are strictly forbidden.

`python -m src.db_config` is the sole executable schema, role, membership, and
grant authority. It invokes `src.db_config.apply_role_setup()` using dynamic
`aurum.schema_*` parameters. `scripts/setup_roles.sql` is pointer/comment-only
and intentionally contains no independent deployment SQL.

Promotion and CTAS handoff operations exclusively consume connections from the bounded
`get_promotion_pool()`. Existing candidate object collisions fail closed without dropping
pre-existing relations. Exact candidate identity (namespace OID, relation OID, relation name,
relkind) is captured atomically within the handoff transaction.

## Silver pipeline lineage & post-commit identity persistence

Production Silver generation remains intentionally unavailable: its generation
endpoint returns HTTP 503. Batch 4.5C hardens only the contained execution and
promotion machinery. A future generator must bind complete authority
server-side before its output can be eligible for execution.

`silver_lineage_id` is the SHA-256 digest of compact, key-sorted JSON with this
exact payload:

```json
{
  "version": "silver-lineage-v2",
  "project_id": "<explicit non-empty value>",
  "connection_id": "<explicit non-empty value>",
  "database_name": "<explicit non-empty value>",
  "bronze_schema": "<explicit non-empty value>",
  "bronze_relation": "<explicit non-empty value>",
  "silver_schema": "<explicit non-empty value>",
  "silver_target_relation": "<explicit non-empty value>"
}
```

All seven authority inputs are required and trimmed. The lineage function has
no project, connection, database, Bronze, or Silver defaults. Missing or empty
input rejects; it never fabricates historical authority.

Silver candidate cleanup uses a positive lifecycle allowlist:

```text
FAILED
+ strict persisted six-field candidate identity
+ same live database/namespace/relation OID, schema, name, and kind
+ ACCESS EXCLUSIVE lock and identity re-resolution
→ cleanup eligible
```

State remains necessary but never sufficient. `PENDING`, `EXECUTING`,
`PROMOTING`, `PROMOTED`, `AMBIGUOUS_PROMOTION`, malformed status, and unknown
or future status are never automatic Silver candidate cleanup authority.
Candidate names, prefixes, run IDs, and age are not ownership proof. A
same-name relation with a different OID is preserved.

Silver promotion distinguishes:

```text
PRE_TRANSACTION
→ TRANSACTION_ACTIVE
→ COMMIT_IN_PROGRESS immediately before the commit call
→ COMMIT_ACKNOWLEDGED only after the commit returns successfully
```

Pool checkout, transaction entry, or transaction-body failure before the
commit attempt is deterministic. A body failure with acknowledged rollback is
reported separately from rollback acknowledgement failure. An exception from
the commit attempt is `SilverPromotionCommitUnknown` and persists
`AMBIGUOUS_PROMOTION`, with no DDL retry.

Commit acknowledgement is monotonic. A later connection/pool reset or context
cleanup exception does not change the known PostgreSQL outcome: the verified
committed result continues to SQLite final-state persistence. A durable
`PROMOTED` write includes strict `promoted_target_identity_json`. If that write
fails, Aurum attempts `AMBIGUOUS_PROMOTION` and does not issue a second
PostgreSQL promotion.

Silver backup names are deterministically bounded to 63 UTF-8 bytes. Collision
checks, old-target OID continuity, lock retention, and exact pre-drop OID
verification remain inside the promotion transaction.

## Backup cleanup boundary

Overwrite promotion intentionally retains the old exact target as a backup.
The backup name is derived from the promotion claim and respects PostgreSQL's
63-byte identifier limit, but its name is not authority. Exact database,
namespace, relation OID, schema, name, kind, run, and promotion claim are
persisted or derivable from immutable approved/claimed state.
`backup_cleanup_eligible` is persisted as false whenever a backup identity
exists; Batch 4.5C has no transition that can set it true.

Batch 4.5C never automatically deletes a backup. `PROMOTING` and
`AMBIGUOUS_PROMOTION` artifacts remain protected.

Production-safe backup-artifact cleanup remains a required follow-up before
Gold is enabled for real users. It must receive its own implementation and
independent verification, analogous to the hardened Gold candidate-cleanup
work. Backup ownership must be proven through exact
database/namespace/relation identity and OID, never through names or prefixes.
