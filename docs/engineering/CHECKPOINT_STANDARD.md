# Aurum Immutable Checkpoint Provenance Standard

## Purpose and authority

This standard defines the machine-verifiable record that binds an Aurum
checkpoint decision to one exact Git state. Apply it under
[`AGENTS.md`](../../AGENTS.md), the
[AI-Assisted Engineering Standards](AI_ENGINEERING_STANDARDS.md), and the
[Builder and Independent Verification Standard](VERIFICATION_STANDARD.md).

> A valid manifest proves that its recorded scope and evidence refer to the
> exact Git commit, tree, parent, trusted base, file identities, and deterministic
> change identity in the manifest. It does **not** prove that the implementation
> is logically correct. Logical correctness still requires an independent
> verifier to inspect and test the exact candidate.

The manifest is provenance binding, not automatic approval, promotion, tagging,
or release machinery.

## Candidate and trusted checkpoint

A **candidate** is an exact, immutable commit proposed by a builder. It remains
untrusted even when builder-side tests pass.

A **trusted checkpoint** is an exact candidate for which an independent
verifier:

1. checks out or otherwise inspects the exact full candidate SHA;
2. validates its Git identity and ancestry against the approved trusted base;
3. independently performs the required verification;
4. records complete, classified evidence; and
5. issues a `PASS` manifest bound to the exact candidate SHA and tree SHA.

A branch, tag, pull request, worktree, commit message, or copied test output is
not an immutable checkpoint identity. The manifest's `repository.ref` is
informational only.

The workflow is:

`Builder candidate → exact candidate commit → independent verifier checkout → Git identity validation → required verification → PASS decision → PASS manifest for exact SHA/tree → trusted checkpoint`

Any later change to source, tests, configuration, documentation, evidence, or
the candidate commit requires a new candidate and new independent verification.
An earlier `PASS` does not transfer to a descendant, amended commit, rebased
commit, or mutable ref.

A `PASS` always remains bound to its exact full commit SHA and tree SHA. A
checkpoint tag or ref is only an optional human- or automation-friendly pointer;
it must be immutable and must never be force-moved or reused for another
candidate. Moving the pointer does not transfer the earlier `PASS`. Trusting a
new commit requires a new candidate, independent verification, `PASS` manifest,
and checkpoint identity or ref.

## Manifest format

Checkpoint manifests are UTF-8 JSON objects with no duplicate keys. Version 1
has these top-level fields:

| Field | Required content |
| --- | --- |
| `schema_version` | Integer `1`. Unsupported versions fail closed. |
| `checkpoint_id` | Stable human-readable identifier. |
| `status` | `CANDIDATE`, `PASS`, `FAIL`, or `REVOKED`. |
| `repository` | Remote identity and exact Git commit provenance. |
| `scope` | Expected and independently derived changed paths and classifications. |
| `file_identities` | Base and candidate Git blob SHAs for every changed path, where the path resolves to a blob. |
| `diff_identity` | Versioned deterministic SHA-256 change identity. |
| `verification` | Classified command evidence and optional safe PostgreSQL metadata. |
| `decision` | Verifier identity, terminal outcome, findings, exclusions, and risks. |

### Repository identity

`repository` contains:

- `remote`: the sanitized `origin` URL, or `null` when no origin exists;
- `candidate_sha`: the full candidate commit SHA;
- `candidate_tree_sha`: the candidate commit's full tree SHA;
- `parent_sha`: the candidate's single full parent SHA;
- `trusted_base_sha`: the externally approved full trust anchor; and
- `ref`: an optional informational branch or ref.

The validator detects the repository's Git object format and requires the
complete lowercase SHA length for that format. Abbreviations are invalid.
Version 1 requires a single-parent candidate and requires the trusted base to be
an ancestor of the candidate.

Validation requires the verifier to supply both the expected candidate SHA and
the expected trusted-base SHA outside the manifest. This prevents an untrusted
manifest from choosing its own candidate or trust anchor.

### Changed scope and rename treatment

`scope` contains sorted, duplicate-free:

- `expected_changed_files`;
- `actual_changed_files`;
- `added`;
- `modified`;
- `deleted`; and
- `renamed`, represented as sorted `{ "from": ..., "to": ... }` pairs.

Git rename detection uses `git diff-tree -r -z -M50% --name-status`. Both the
source and destination of a detected rename appear in
`actual_changed_files` and must appear in `expected_changed_files`. Type changes
are classified as modified.

The validator derives the actual set and classifications directly from Git.
Expected and actual paths must be identical. It rejects every unexpected actual
path, every missing expected path, and every classification or rename mismatch.
Paths must be normalized, repository-relative POSIX paths; absolute paths,
backslashes, empty components, `.` components, `..` components, and NUL bytes
are invalid.

### File identities

`file_identities` contains one path-sorted object for every actual changed path:

```json
{
  "path": "scripts/example.py",
  "base_blob_sha": null,
  "candidate_blob_sha": "full-git-blob-sha"
}
```

The base or candidate value is `null` when the path does not exist in that tree
or the Git object is not a blob. This records both sides of additions, changes,
deletions, and renames without reading worktree files. Validation independently
re-derives these identities with `git ls-tree`.

## Deterministic diff identity

Version 1 uses:

- `algorithm`: `sha256`;
- `canonicalization`: `aurum-git-tree-delta-json-v1`; and
- `digest`: a lowercase 64-character SHA-256 digest.

The canonical payload is built from Git objects, not displayed terminal text:

```json
{
  "candidate_sha": "<full candidate SHA>",
  "changes": [
    {
      "path": "<repository-relative path>",
      "base": {
        "mode": "<Git mode>",
        "object_type": "<Git object type>",
        "object_sha": "<full object SHA>"
      },
      "candidate": {
        "mode": "<Git mode>",
        "object_type": "<Git object type>",
        "object_sha": "<full object SHA>"
      }
    }
  ],
  "trusted_base_sha": "<full trusted base SHA>"
}
```

For an absent side, `base` or `candidate` is JSON `null`. `changes` includes
every path whose recursive Git tree entry differs and is sorted by UTF-8 path
bytes. Objects use lexicographically sorted keys. Serialization is UTF-8 JSON
with no insignificant whitespace (`ensure_ascii=false`, separators `,` and
`:`). The digest is SHA-256 over those exact serialized bytes.

This binds path, mode, object type, Git object identity, candidate, and trusted
base. It never hashes color, pager output, quoting, line endings added by a
terminal, localized messages, or other terminal formatting. Rename
classification is verified separately because a rename is a Git comparison
interpretation; the digest binds the underlying removal and addition.

## Verification evidence

Each `verification.evidence` record contains:

- `exact_command`: the command that the verifier ran;
- `context`: its working directory or safe execution context;
- `exit_code`: the integer exit code;
- `classification`: one of `static`, `unit`, `mocked integration`,
  `live PostgreSQL integration`, `concurrency`, `security-negative`,
  `API contract`, `end-to-end`, or `manual inspection`;
- `result_summary`: a concise result; and
- optional `test_counts` and `artifact`.

When `test_counts` is present it must separately record `collected`, `executed`,
`passed`, `failed`, `skipped`, `xfailed`, and `xpassed`. All counts are
non-negative; executed equals the sum of reported outcomes and cannot exceed
collected.

An artifact may record a SHA-256 digest, a reference, or both. Artifact
references are data only. The validator never opens them.

`verification.postgresql` may be `null` or contain:

- server version;
- a safe test-database fingerprint;
- role category;
- `live` or `mocked`;
- isolation status.

Do not record credentials, passwords, tokens, secret-bearing connection
strings, production data, or sensitive database contents. Likely secret
assignments and credential-bearing HTTP/PostgreSQL URLs fail validation. The
generator strips URL user information from the recorded origin remote.

Commands stored in a manifest are untrusted strings. Generation and validation
never execute them.

## Decision states

### `CANDIDATE`

The builder may create this state. `decision.outcome` and
`decision.verifier_identifier` are `null`. A valid candidate manifest is not a
PASS and not a trusted checkpoint.

### `PASS`

Only an independent verifier may issue this state. The decision outcome must be
`PASS`, the verifier identifier must be non-empty, and at least one evidence
record is required. PASS binds only to the exact commit and tree in the
manifest. Known revoked SHA
`827f0efc002a7f79cc361e44627f952885cd60d5` can never validate as PASS.

### `FAIL`

The decision outcome must be `FAIL` and identify the verifier. Findings or
references should state the failed acceptance criteria and required correction.
FAIL does not modify, promote, tag, or repair the candidate. Correction requires
a new builder candidate.

### `REVOKED`

The decision outcome must be `REVOKED` and identify the revoking verifier or
authority. Findings or references should identify the reason and superseding
authority when applicable. Revocation is explicit negative provenance; it never
becomes PASS through retries.

All terminal decisions may record known exclusions and unresolved risks.

## Validator security properties

[`scripts/checkpoint_manifest.py`](../../scripts/checkpoint_manifest.py) treats
manifest JSON as untrusted input. It:

- accepts at most 1 MiB of UTF-8 JSON and rejects duplicate keys, unsupported
  keys, malformed values, and non-standard numbers;
- requires external full-SHA candidate and trusted-base bindings;
- invokes Git with argument arrays and `shell=False`;
- executes only internally allowlisted, read-only Git inspection operations and
  disables replacement objects;
- reads Git trees and objects, not manifest-controlled worktree paths;
- never executes evidence commands or follows artifact references;
- rejects traversal and malformed repository paths;
- never checks out manifest paths, changes refs, creates tags, modifies history,
  promotes a candidate, or writes to the repository; and
- fails closed on inconsistent provenance.

The `generate` operation writes only the explicitly requested output manifest.
The `validate` operation is read-only.

## CLI

Generate a candidate manifest from the current `HEAD`:

```text
python scripts/checkpoint_manifest.py generate \
  --repo . \
  --checkpoint-id ECC-C-CANDIDATE-1 \
  --trusted-base <FULL_TRUSTED_BASE_SHA> \
  --expected-file docs/engineering/CHECKPOINT_STANDARD.md \
  --expected-file scripts/checkpoint_manifest.py \
  --expected-file tests/test_checkpoint_manifest.py \
  --output checkpoint.json
```

Validate it against independently supplied trust anchors:

```text
python scripts/checkpoint_manifest.py validate checkpoint.json \
  --repo . \
  --candidate <FULL_CANDIDATE_SHA> \
  --trusted-base <FULL_TRUSTED_BASE_SHA>
```

`generate` accepts repeated JSON evidence objects and optional safe PostgreSQL
JSON for verifier-authored terminal manifests. It validates the complete result
before writing. Neither operation performs checkpoint promotion.

## What mutation invalidates

Changing the candidate changes at least its commit SHA and normally its tree,
parent relation, changed-file identities, blob SHAs, or diff digest. Editing a
manifest after verification also requires revalidation, and changing recorded
evidence requires a new verifier decision artifact. A `PASS` is never inherited
by a branch tip or later commit.

The manifest establishes exact provenance and detects scope substitution. It
does not establish requirement authority, code quality, business correctness,
security correctness, database correctness, test adequacy, or truthful command
execution by itself. Those remain independent-verifier responsibilities.
