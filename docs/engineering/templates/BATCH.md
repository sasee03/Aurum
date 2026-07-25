# Aurum Batch Specification

## Identity

- **Batch ID:**
- **Goal:**
- **Trusted base full SHA:**
- **Authority references:**
- **Builder:**
- **Independent verifier:**

## Scope

### In-scope behavior

-

### Explicitly out-of-scope behavior

-

### Writable file allowlist

-

### Expected changed files

-

Anything not listed as writable or behaviorally in scope is not implicitly
approved.

## Governing invariants

### Product and engineering invariants

-

### Acceptance criteria

- [ ]

## Evidence

### Required evidence

- Starting branch, full HEAD SHA, tree SHA, and status.
- Changed-file list, diff stat, and full diff.
- Exact validation commands, exit codes, and results.
- Final candidate full commit SHA, tree SHA, parent SHA, branch, and status.

Distinguish tests executed from static validation, searches, collection, and
files inspected. Collection count is not a passing test result.

### PostgreSQL and live-test requirements

- **Required for this batch:** Yes / No
- **Approved test database/environment:**
- **Isolation and cleanup requirements:**
- **Evidence required:**

Do not run live tests against an unapproved database or treat a skipped live test
as execution proof.

## Risk and recovery

### Risk areas

-

Explicitly consider partial failure, retry, idempotency, concurrency, stale
state, recovery, and ambiguous outcomes when durable state is in scope.

### Rollback or recovery

-

## Stop conditions

### Builder stop condition

Stop on an unexpected changed path, unclear authority, missing required evidence,
or a necessary behavior outside approved scope. Do not absorb the issue into the
batch.

### Verifier requirements

- Review the exact candidate commit and tree independently.
- Confirm ancestry from the trusted base.
- Confirm every changed path and behavior is approved.
- Run the required verification independently.
- Return PASS or FAIL bound to the exact candidate state.

Any candidate change after PASS invalidates that PASS. A builder report or
candidate commit is not a trusted checkpoint.
