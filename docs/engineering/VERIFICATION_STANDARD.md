# Aurum Builder and Independent Verification Standard

## Purpose and authority

This document defines the evidence required from Aurum builders and independent
verifiers. Apply it under the authority order in
[`AGENTS.md`](../../AGENTS.md), the
[AI-Assisted Engineering Standards](AI_ENGINEERING_STANDARDS.md), and the
approved [batch specification](templates/BATCH.md).

The normal delivery flow is:

`Planner → bounded batch → Builder → untrusted candidate commit → Independent Verifier → evidence-backed PASS or FAIL → later checkpoint promotion`

Builder testing is evidence. It is not approval. Context is not permission.

## Builder evidence packet

The builder must return a structured packet with the following sections.

### Starting provenance

- Repository root and builder worktree.
- Branch or detached-HEAD state.
- Full starting commit SHA and tree SHA.
- Trusted base full SHA.
- Worktree and index cleanliness.
- Remote identity where relevant to provenance.

The builder must establish this state before editing. A wrong trusted base,
inconsistent repository identity, or unexpected dirty state is a stop condition.

### Approved scope

- Batch ID and approved goal.
- Writable-file allowlist and expected changed files.
- Explicitly out-of-scope behavior.
- Applicable acceptance criteria and authority references.

Anything outside the approved behavioral scope or writable paths remains
unauthorized even when surrounding context discusses it.

### Actual implementation

- Every file added, modified, deleted, or renamed.
- The reason for each changed file.
- Behavior changed and behavior deliberately left unchanged.
- Unexpected findings, including any issue not absorbed into the batch.

### Validation evidence

For every reported command, record:

- the exact command;
- its working directory;
- its exit code; and
- the meaningful result.

When tests are involved, report these independently rather than collapsing them
into a single number:

- collected;
- executed;
- passed;
- failed;
- skipped;
- xfailed; and
- xpassed.

A collection count is not a pass count. Builder output must not imply that
collected, skipped, or unavailable tests executed successfully.

Classify relevant evidence where applicable as:

- static;
- unit;
- mocked integration;
- live PostgreSQL integration;
- concurrency;
- security-negative;
- API contract;
- end-to-end; or
- manual inspection.

### Database evidence

When PostgreSQL behavior is in scope, distinguish real database execution from
mocks. Record safe evidence such as:

- PostgreSQL server version;
- test database identity or a non-secret fingerprint;
- role category used;
- whether real DDL or DML executed; and
- how test state was isolated.

Never record credentials, connection secrets, or sensitive database contents.
When database behavior is out of scope, say that live database evidence was not
required rather than running it for appearance.

### Known limitations

State explicitly:

- tests not run;
- unavailable environments;
- mocked-only coverage;
- unresolved risks; and
- assumptions that affect the evidence.

An omitted limitation is not evidence that the limitation does not exist.

### Candidate handoff

When the batch permits a candidate commit, create one candidate commit and
report:

- full candidate commit SHA;
- tree SHA;
- parent SHA;
- branch or ref;
- complete changed-file list; and
- final worktree and index cleanliness.

Label the handoff:

`UNTRUSTED CANDIDATE — AWAITING INDEPENDENT VERIFICATION`

A builder must not call its candidate a PASS, trusted checkpoint, approved
release, or verified state.

## Independent verifier standard

The independent verifier is an evidence gate, not a second builder. The verifier
must not have built the candidate in the same session and must inspect the exact
candidate commit and tree rather than relying on a mutable branch tip or working
tree.

The verifier independently establishes:

- repository root and remote identity;
- candidate full SHA and tree SHA;
- parent and trusted base full SHA;
- branch or ref, when applicable;
- verifier-worktree cleanliness; and
- the exact changed-file set.

Compare the trusted base directly to the exact candidate and enumerate every
added, modified, deleted, renamed, and unexpected path. Builder-supplied
provenance may guide this work but does not establish it.

### Narrative is not independent proof

None of the following is independent proof:

- builder summaries;
- commit messages;
- pull-request descriptions;
- comments;
- test names;
- documentation claims;
- screenshots without exact provenance;
- copied terminal output;
- model confidence; or
- same-session self-review.

These inputs can identify questions to investigate. They cannot replace direct
inspection or independently executed evidence.

### Risk-based verification

Apply only the categories relevant to the batch and explain omissions where they
would otherwise be surprising:

- **Correctness:** the implementation satisfies the authorized requirement.
- **Scope:** changed behavior and files stay within the approved boundaries.
- **Regression:** existing behavior at risk remains intact.
- **Failure paths:** partial failure cannot silently create a false success.
- **Retry and idempotency:** retries do not duplicate or corrupt durable state.
- **Concurrency:** simultaneous execution does not violate invariants.
- **Stale state:** approvals, revisions, and metadata cannot be reused after
  becoming outdated.
- **Exact relation identity:** database objects are identified without ambiguity
  where relation identity matters.
- **SQL safety:** generated or dynamic SQL cannot escape its intended authority.
- **Recovery:** failed or ambiguous outcomes can be reconciled safely.
- **Production scale:** the implementation does not depend on demo-sized or
  dataset-specific assumptions.

Risk-based verification is preferred over forcing irrelevant checklist items
into every batch.

### Test and evidence review

The verifier assesses what evidence proves, not merely whether a command
returned success. Where relevant, inspect skips, xfails, mocks, monkeypatches,
fixture scope, conditional environment skips, database isolation, whether
PostgreSQL actually executed, and whether a regression test would fail if the
defect returned.

A test that encodes newly invented behavior does not prove that behavior was
authorized.

Independently rerun evidence needed for acceptance criteria and high-risk,
regression-sensitive, security, concurrency, or database behavior. Exact
duplication of every builder command is unnecessary when it adds no evidence.

## Finding contract

Each material finding should include:

- severity;
- exact file and location;
- triggering condition or state;
- actual bad outcome;
- why existing safeguards do not prevent it;
- reproduction steps or direct evidence; and
- confidence, when useful.

Use these severities:

- **CRITICAL:** a trust, provenance, or security failure capable of
  fundamentally invalidating the candidate.
- **HIGH:** a defect that could cause incorrect durable behavior, unsafe SQL or
  database state, approval of the wrong code, data loss, a major security issue,
  or a serious concurrency or recovery failure.
- **MEDIUM:** a real correctness, maintainability, or contract issue with
  meaningful but non-catastrophic impact.
- **LOW:** a minor defect or maintainability issue.

Do not manufacture findings. Zero material findings is valid.

## Verdict and binding

The verifier returns PASS or FAIL only after independently evaluating the exact
candidate.

PASS must state:

`PASS applies only to commit <FULL_SHA>, tree <FULL_TREE_SHA>.`

A branch, pull-request number, short SHA, conversation, or worktree path is not
a sufficient binding. Any later source, test, configuration, or documentation
change invalidates the PASS.

On FAIL, the verifier reports evidence and the minimum required corrections but
does not fix the candidate, weaken tests, or create a replacement candidate in
the verifier session. Corrections require a new builder cycle and independent
verification.

## Builder selection and session separation

Antigravity remains a valid Aurum builder. The normal pattern is:

`Planner/Scope → Antigravity Builder → Independent Codex Verifier`

Codex may be selected as builder for high-risk recovery, provenance repair,
checkpoint tooling, repeated Antigravity failure, or subtle concurrency and
database-correctness work. When Codex builds, a separate Codex session must
perform independent verification. The same model can serve different roles;
the same session cannot supply both builder evidence and independent approval.
