#!/usr/bin/env python3
"""Generate and validate immutable Aurum checkpoint provenance manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit, urlunsplit


SCHEMA_VERSION = 1
DIFF_CANONICALIZATION = "aurum-git-tree-delta-json-v1"
KNOWN_REVOKED_SHAS = {
    "827f0efc002a7f79cc361e44627f952885cd60d5",
}
STATUSES = {"CANDIDATE", "PASS", "FAIL", "REVOKED"}
EVIDENCE_CLASSIFICATIONS = {
    "static",
    "unit",
    "mocked integration",
    "live PostgreSQL integration",
    "concurrency",
    "security-negative",
    "API contract",
    "end-to-end",
    "manual inspection",
}
TEST_COUNT_KEYS = {
    "collected",
    "executed",
    "passed",
    "failed",
    "skipped",
    "xfailed",
    "xpassed",
}
MAX_MANIFEST_BYTES = 1024 * 1024
_CHECKPOINT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(?:password|passwd|pwd|token|api[_-]?key|secret|credential)"
    r"\b\s*[:=]\s*[^\s,;]+"
)
_CREDENTIAL_URL_RE = re.compile(
    r"(?i)\b(?:https?|postgres|postgresql)://[^\s/@:]+(?::[^\s/@]*)?@"
)
_READ_ONLY_GIT_PREFIXES = (
    ("rev-parse", "--show-toplevel"),
    ("rev-parse", "--show-object-format"),
    ("rev-parse", "--verify"),
    ("cat-file", "-t"),
    ("show", "-s"),
    ("merge-base", "--is-ancestor"),
    ("remote", "get-url"),
    ("branch", "--show-current"),
    ("ls-tree",),
    ("diff-tree",),
)


class ManifestError(ValueError):
    """Raised when provenance cannot be derived or a manifest is invalid."""


TreeEntry = Tuple[str, str, str]


def _decode(data: bytes, context: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ManifestError(
            "{} is not valid UTF-8; this manifest format cannot represent it".format(
                context
            )
        ) from exc


def _git(
    repo: Path,
    args: Sequence[str],
    *,
    allowed_exit_codes: Iterable[int] = (0,),
) -> subprocess.CompletedProcess:
    """Run one fixed Git operation without a shell."""

    if not any(
        tuple(args[: len(prefix)]) == prefix for prefix in _READ_ONLY_GIT_PREFIXES
    ):
        raise ManifestError("refusing non-read-only Git operation")
    command = ["git", "--no-replace-objects", "-C", str(repo)] + list(args)
    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        check=False,
    )
    if completed.returncode not in set(allowed_exit_codes):
        detail = _decode(completed.stderr, "Git error output").strip()
        raise ManifestError(
            "Git command failed (exit {}): {}{}".format(
                completed.returncode,
                " ".join(args),
                ": {}".format(detail) if detail else "",
            )
        )
    return completed


def _repository_root(repo: Path) -> Path:
    candidate = Path(repo).resolve()
    if not candidate.is_dir():
        raise ManifestError("repository path is not a directory: {}".format(candidate))
    completed = _git(candidate, ["rev-parse", "--show-toplevel"])
    return Path(_decode(completed.stdout, "repository root").strip()).resolve()


def _object_format(repo: Path) -> Tuple[str, int]:
    output = _decode(
        _git(repo, ["rev-parse", "--show-object-format"]).stdout,
        "Git object format",
    ).strip()
    if output == "sha1":
        return output, 40
    if output == "sha256":
        return output, 64
    raise ManifestError("unsupported Git object format: {!r}".format(output))


def _require_full_sha(value: Any, field: str, length: int) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9a-f]{{{}}}".format(length), value
    ):
        raise ManifestError(
            "{} must be a lowercase full {}-character Git SHA".format(field, length)
        )
    return value


def _resolve_generation_candidate(repo: Path, value: str, sha_length: int) -> str:
    if value == "HEAD":
        return _decode(
            _git(repo, ["rev-parse", "--verify", "HEAD"]).stdout,
            "candidate SHA",
        ).strip()
    return _require_full_sha(value, "candidate", sha_length)


def _commit_identity(repo: Path, sha: str, sha_length: int) -> Tuple[str, List[str]]:
    object_type = _decode(
        _git(repo, ["cat-file", "-t", sha]).stdout,
        "Git object type",
    ).strip()
    if object_type != "commit":
        raise ManifestError("{} is not a commit object".format(sha))
    fields = _decode(
        _git(repo, ["show", "-s", "--format=%T%n%P", sha]).stdout,
        "commit identity",
    ).splitlines()
    if not fields:
        raise ManifestError("Git did not return a tree for commit {}".format(sha))
    tree_sha = _require_full_sha(fields[0], "derived tree SHA", sha_length)
    parents = [
        _require_full_sha(parent, "derived parent SHA", sha_length)
        for parent in (fields[1].split() if len(fields) > 1 else [])
    ]
    return tree_sha, parents


def _assert_ancestor(repo: Path, trusted_base: str, candidate: str) -> None:
    completed = _git(
        repo,
        ["merge-base", "--is-ancestor", trusted_base, candidate],
        allowed_exit_codes=(0, 1),
    )
    if completed.returncode != 0:
        raise ManifestError(
            "trusted base {} is not an ancestor of candidate {}".format(
                trusted_base, candidate
            )
        )


def _sanitize_remote(remote: str) -> str:
    remote = remote.strip()
    if not remote:
        raise ManifestError("origin remote is empty")
    parsed = urlsplit(remote)
    if parsed.scheme and parsed.netloc:
        host = parsed.hostname or ""
        if parsed.port:
            host = "{}:{}".format(host, parsed.port)
        return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))
    scp_style = re.fullmatch(r"[^/@:\s]+@([^:\s]+):(.+)", remote)
    if scp_style:
        return "{}:{}".format(scp_style.group(1), scp_style.group(2))
    return remote


def _repository_remote(repo: Path) -> Optional[str]:
    completed = _git(
        repo,
        ["remote", "get-url", "origin"],
        allowed_exit_codes=(0, 2),
    )
    if completed.returncode == 2:
        return None
    return _sanitize_remote(_decode(completed.stdout, "origin remote"))


def _informational_ref(repo: Path, candidate: str) -> Optional[str]:
    head = _decode(
        _git(repo, ["rev-parse", "--verify", "HEAD"]).stdout,
        "HEAD SHA",
    ).strip()
    if head != candidate:
        return None
    ref = _decode(
        _git(repo, ["branch", "--show-current"]).stdout,
        "branch name",
    ).strip()
    return ref or None


def _validate_path(value: Any, field: str = "path") -> str:
    if not isinstance(value, str) or not value:
        raise ManifestError("{} must be a non-empty string".format(field))
    if "\x00" in value or "\\" in value:
        raise ManifestError("{} contains an unsafe path separator".format(field))
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ManifestError("{} must be a normalized repository-relative path".format(field))
    if value != path.as_posix():
        raise ManifestError("{} must be a normalized repository-relative path".format(field))
    return value


def _path_sort(values: Iterable[str]) -> List[str]:
    return sorted(values, key=lambda item: item.encode("utf-8"))


def _ls_tree(repo: Path, commit_sha: str, sha_length: int) -> Dict[str, TreeEntry]:
    output = _git(repo, ["ls-tree", "-rz", "--full-tree", commit_sha]).stdout
    entries: Dict[str, TreeEntry] = {}
    for raw_record in output.split(b"\x00"):
        if not raw_record:
            continue
        try:
            raw_metadata, raw_path = raw_record.split(b"\t", 1)
            mode, object_type, object_sha = raw_metadata.decode("ascii").split(" ")
        except (UnicodeDecodeError, ValueError) as exc:
            raise ManifestError("Git returned a malformed tree entry") from exc
        path = _validate_path(_decode(raw_path, "Git path"), "Git path")
        _require_full_sha(object_sha, "tree object SHA", sha_length)
        entries[path] = (mode, object_type, object_sha)
    return entries


def _name_status(
    repo: Path,
    trusted_base: str,
    candidate: str,
) -> Dict[str, Any]:
    output = _git(
        repo,
        [
            "diff-tree",
            "--no-commit-id",
            "--name-status",
            "-r",
            "-z",
            "-M50%",
            "--no-ext-diff",
            trusted_base,
            candidate,
        ],
    ).stdout
    parts = output.split(b"\x00")
    if parts and parts[-1] == b"":
        parts.pop()
    added: List[str] = []
    modified: List[str] = []
    deleted: List[str] = []
    renamed: List[Dict[str, str]] = []
    index = 0
    while index < len(parts):
        status = _decode(parts[index], "Git change status")
        index += 1
        if not status:
            raise ManifestError("Git returned an empty change status")
        if status.startswith("R"):
            if index + 1 >= len(parts):
                raise ManifestError("Git returned a malformed rename entry")
            old_path = _validate_path(_decode(parts[index], "rename source"), "rename source")
            new_path = _validate_path(
                _decode(parts[index + 1], "rename destination"),
                "rename destination",
            )
            index += 2
            renamed.append({"from": old_path, "to": new_path})
            continue
        if index >= len(parts):
            raise ManifestError("Git returned a malformed change entry")
        path = _validate_path(_decode(parts[index], "Git path"), "Git path")
        index += 1
        code = status[0]
        if code == "A":
            added.append(path)
        elif code == "D":
            deleted.append(path)
        elif code in {"M", "T"}:
            modified.append(path)
        else:
            raise ManifestError("unsupported Git change status: {!r}".format(status))
    renamed.sort(key=lambda item: (item["from"].encode("utf-8"), item["to"].encode("utf-8")))
    actual = set(added) | set(modified) | set(deleted)
    for rename in renamed:
        actual.add(rename["from"])
        actual.add(rename["to"])
    return {
        "actual_changed_files": _path_sort(actual),
        "added": _path_sort(added),
        "modified": _path_sort(modified),
        "deleted": _path_sort(deleted),
        "renamed": renamed,
    }


def _tree_record(entry: Optional[TreeEntry]) -> Optional[Dict[str, str]]:
    if entry is None:
        return None
    mode, object_type, object_sha = entry
    return {
        "mode": mode,
        "object_type": object_type,
        "object_sha": object_sha,
    }


def _derive_change_identity(
    base_tree: Mapping[str, TreeEntry],
    candidate_tree: Mapping[str, TreeEntry],
    trusted_base: str,
    candidate: str,
    classified_paths: Sequence[str],
) -> Tuple[List[Dict[str, Optional[str]]], str]:
    changed_paths = _path_sort(
        path
        for path in set(base_tree) | set(candidate_tree)
        if base_tree.get(path) != candidate_tree.get(path)
    )
    if changed_paths != list(classified_paths):
        raise ManifestError(
            "Git changed-file classification did not match the exact tree delta"
        )
    identities: List[Dict[str, Optional[str]]] = []
    canonical_changes: List[Dict[str, Any]] = []
    for path in changed_paths:
        base_entry = base_tree.get(path)
        candidate_entry = candidate_tree.get(path)
        identities.append(
            {
                "path": path,
                "base_blob_sha": (
                    base_entry[2] if base_entry and base_entry[1] == "blob" else None
                ),
                "candidate_blob_sha": (
                    candidate_entry[2]
                    if candidate_entry and candidate_entry[1] == "blob"
                    else None
                ),
            }
        )
        canonical_changes.append(
            {
                "path": path,
                "base": _tree_record(base_entry),
                "candidate": _tree_record(candidate_entry),
            }
        )
    canonical_payload = {
        "candidate_sha": candidate,
        "changes": canonical_changes,
        "trusted_base_sha": trusted_base,
    }
    canonical_bytes = json.dumps(
        canonical_payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return identities, hashlib.sha256(canonical_bytes).hexdigest()


def derive_repository_state(
    repo: Path,
    candidate_sha: str,
    trusted_base_sha: str,
) -> Dict[str, Any]:
    """Derive immutable provenance only from Git objects."""

    root = _repository_root(repo)
    _, sha_length = _object_format(root)
    candidate_sha = _require_full_sha(candidate_sha, "candidate SHA", sha_length)
    trusted_base_sha = _require_full_sha(
        trusted_base_sha, "trusted base SHA", sha_length
    )
    candidate_tree_sha, parents = _commit_identity(root, candidate_sha, sha_length)
    _commit_identity(root, trusted_base_sha, sha_length)
    if len(parents) != 1:
        raise ManifestError(
            "candidate commit must have exactly one parent; found {}".format(len(parents))
        )
    _assert_ancestor(root, trusted_base_sha, candidate_sha)
    classification = _name_status(root, trusted_base_sha, candidate_sha)
    base_tree = _ls_tree(root, trusted_base_sha, sha_length)
    candidate_tree = _ls_tree(root, candidate_sha, sha_length)
    identities, digest = _derive_change_identity(
        base_tree,
        candidate_tree,
        trusted_base_sha,
        candidate_sha,
        classification["actual_changed_files"],
    )
    return {
        "root": root,
        "sha_length": sha_length,
        "remote": _repository_remote(root),
        "candidate_sha": candidate_sha,
        "candidate_tree_sha": candidate_tree_sha,
        "parent_sha": parents[0],
        "trusted_base_sha": trusted_base_sha,
        "ref": _informational_ref(root, candidate_sha),
        "classification": classification,
        "file_identities": identities,
        "diff_digest": digest,
    }


def _decision_for(
    status: str,
    verifier: Optional[str],
    findings_references: Sequence[str],
    known_exclusions: Sequence[str],
    unresolved_risks: Sequence[str],
) -> Dict[str, Any]:
    return {
        "verifier_identifier": verifier,
        "outcome": None if status == "CANDIDATE" else status,
        "findings_references": list(findings_references),
        "known_exclusions": list(known_exclusions),
        "unresolved_risks": list(unresolved_risks),
    }


def generate_manifest(
    repo: Path,
    *,
    checkpoint_id: str,
    candidate_sha: str,
    trusted_base_sha: str,
    expected_changed_files: Sequence[str],
    status: str = "CANDIDATE",
    verifier: Optional[str] = None,
    evidence: Optional[Sequence[Mapping[str, Any]]] = None,
    postgresql: Optional[Mapping[str, Any]] = None,
    findings_references: Sequence[str] = (),
    known_exclusions: Sequence[str] = (),
    unresolved_risks: Sequence[str] = (),
) -> Dict[str, Any]:
    """Generate a manifest and validate it before returning it."""

    root = _repository_root(repo)
    _, sha_length = _object_format(root)
    resolved_candidate = _resolve_generation_candidate(root, candidate_sha, sha_length)
    trusted_base_sha = _require_full_sha(
        trusted_base_sha, "trusted base SHA", sha_length
    )
    state = derive_repository_state(root, resolved_candidate, trusted_base_sha)
    expected = _path_sort(
        _validate_path(path, "expected changed file")
        for path in expected_changed_files
    )
    if len(expected) != len(set(expected)):
        raise ManifestError("expected changed files must not contain duplicates")
    manifest: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "checkpoint_id": checkpoint_id,
        "status": status,
        "repository": {
            "remote": state["remote"],
            "candidate_sha": state["candidate_sha"],
            "candidate_tree_sha": state["candidate_tree_sha"],
            "parent_sha": state["parent_sha"],
            "trusted_base_sha": state["trusted_base_sha"],
            "ref": state["ref"],
        },
        "scope": {
            "expected_changed_files": expected,
            **state["classification"],
        },
        "file_identities": state["file_identities"],
        "diff_identity": {
            "algorithm": "sha256",
            "canonicalization": DIFF_CANONICALIZATION,
            "digest": state["diff_digest"],
        },
        "verification": {
            "evidence": [dict(item) for item in (evidence or ())],
            "postgresql": dict(postgresql) if postgresql is not None else None,
        },
        "decision": _decision_for(
            status,
            verifier,
            findings_references,
            known_exclusions,
            unresolved_risks,
        ),
    }
    validate_manifest(
        manifest,
        root,
        expected_candidate_sha=resolved_candidate,
        expected_trusted_base_sha=trusted_base_sha,
    )
    return manifest


def _require_exact_keys(
    value: Any,
    field: str,
    required: Iterable[str],
    optional: Iterable[str] = (),
) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError("{} must be an object".format(field))
    required_set = set(required)
    allowed = required_set | set(optional)
    missing = required_set - set(value)
    unexpected = set(value) - allowed
    if missing:
        raise ManifestError(
            "{} is missing required keys: {}".format(field, sorted(missing))
        )
    if unexpected:
        raise ManifestError(
            "{} contains unsupported keys: {}".format(field, sorted(unexpected))
        )
    return value


def _require_string(
    value: Any,
    field: str,
    *,
    nullable: bool = False,
    nonempty: bool = True,
) -> Optional[str]:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or (nonempty and not value):
        raise ManifestError("{} must be {}string".format(field, "a non-empty " if nonempty else "a "))
    if len(value) > 8192:
        raise ManifestError("{} is too long".format(field))
    return value


def _require_string_list(value: Any, field: str) -> List[str]:
    if not isinstance(value, list):
        raise ManifestError("{} must be an array".format(field))
    result = []
    for index, item in enumerate(value):
        result.append(
            _require_string(item, "{}[{}]".format(field, index))  # type: ignore[arg-type]
        )
    return result


def _validate_no_likely_secrets(value: Any, field: str = "manifest") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _validate_no_likely_secrets(item, "{}.{}".format(field, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_no_likely_secrets(item, "{}[{}]".format(field, index))
    elif isinstance(value, str):
        if _SECRET_ASSIGNMENT_RE.search(value) or _CREDENTIAL_URL_RE.search(value):
            raise ManifestError("{} appears to contain a credential or secret".format(field))


def _validate_evidence(value: Any) -> None:
    if not isinstance(value, list):
        raise ManifestError("verification.evidence must be an array")
    for index, item in enumerate(value):
        field = "verification.evidence[{}]".format(index)
        evidence = _require_exact_keys(
            item,
            field,
            {
                "exact_command",
                "context",
                "exit_code",
                "classification",
                "result_summary",
            },
            {"test_counts", "artifact"},
        )
        _require_string(evidence["exact_command"], "{}.exact_command".format(field))
        _require_string(evidence["context"], "{}.context".format(field))
        exit_code = evidence["exit_code"]
        if isinstance(exit_code, bool) or not isinstance(exit_code, int):
            raise ManifestError("{}.exit_code must be an integer".format(field))
        if (
            not isinstance(evidence["classification"], str)
            or evidence["classification"] not in EVIDENCE_CLASSIFICATIONS
        ):
            raise ManifestError("{}.classification is unsupported".format(field))
        _require_string(evidence["result_summary"], "{}.result_summary".format(field))
        if "test_counts" in evidence:
            counts = _require_exact_keys(
                evidence["test_counts"],
                "{}.test_counts".format(field),
                TEST_COUNT_KEYS,
            )
            for key, count in counts.items():
                if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                    raise ManifestError(
                        "{}.test_counts.{} must be a non-negative integer".format(
                            field, key
                        )
                    )
            outcomes = sum(
                counts[key]
                for key in ("passed", "failed", "skipped", "xfailed", "xpassed")
            )
            if counts["executed"] != outcomes:
                raise ManifestError(
                    "{}.test_counts.executed must equal all reported outcomes".format(
                        field
                    )
                )
            if counts["collected"] < counts["executed"]:
                raise ManifestError(
                    "{}.test_counts.collected cannot be less than executed".format(
                        field
                    )
                )
        if "artifact" in evidence:
            artifact = _require_exact_keys(
                evidence["artifact"],
                "{}.artifact".format(field),
                set(),
                {"sha256", "reference"},
            )
            if not artifact:
                raise ManifestError("{}.artifact must not be empty".format(field))
            if "sha256" in artifact and (
                not isinstance(artifact["sha256"], str)
                or not _SHA256_RE.fullmatch(artifact["sha256"])
            ):
                raise ManifestError("{}.artifact.sha256 is invalid".format(field))
            if "reference" in artifact:
                _require_string(
                    artifact["reference"], "{}.artifact.reference".format(field)
                )


def _validate_postgresql(value: Any) -> None:
    if value is None:
        return
    evidence = _require_exact_keys(
        value,
        "verification.postgresql",
        {
            "server_version",
            "database_fingerprint",
            "role_category",
            "live_or_mocked",
            "isolation_status",
        },
    )
    for key in (
        "server_version",
        "database_fingerprint",
        "role_category",
        "isolation_status",
    ):
        _require_string(evidence[key], "verification.postgresql.{}".format(key))
    if (
        not isinstance(evidence["live_or_mocked"], str)
        or evidence["live_or_mocked"] not in {"live", "mocked"}
    ):
        raise ManifestError(
            "verification.postgresql.live_or_mocked must be live or mocked"
        )


def _validate_decision(value: Any, status: str) -> None:
    decision = _require_exact_keys(
        value,
        "decision",
        {
            "verifier_identifier",
            "outcome",
            "findings_references",
            "known_exclusions",
            "unresolved_risks",
        },
    )
    verifier = _require_string(
        decision["verifier_identifier"],
        "decision.verifier_identifier",
        nullable=True,
    )
    outcome = decision["outcome"]
    for key in ("findings_references", "known_exclusions", "unresolved_risks"):
        _require_string_list(decision[key], "decision.{}".format(key))
    if status == "CANDIDATE":
        if outcome is not None or verifier is not None:
            raise ManifestError(
                "CANDIDATE decision must have null outcome and verifier identifier"
            )
        return
    if outcome != status:
        raise ManifestError("decision outcome must match manifest status")
    if not verifier:
        raise ManifestError("{} requires a verifier identifier".format(status))


def _validate_manifest_shape(
    manifest: Any,
    sha_length: int,
) -> Tuple[Mapping[str, Any], Mapping[str, Any]]:
    top = _require_exact_keys(
        manifest,
        "manifest",
        {
            "schema_version",
            "checkpoint_id",
            "status",
            "repository",
            "scope",
            "file_identities",
            "diff_identity",
            "verification",
            "decision",
        },
    )
    if (
        isinstance(top["schema_version"], bool)
        or not isinstance(top["schema_version"], int)
        or top["schema_version"] != SCHEMA_VERSION
    ):
        raise ManifestError(
            "unsupported manifest schema version: {!r}".format(top["schema_version"])
        )
    if not isinstance(top["checkpoint_id"], str) or not _CHECKPOINT_ID_RE.fullmatch(
        top["checkpoint_id"]
    ):
        raise ManifestError("checkpoint_id is malformed")
    status = top["status"]
    if not isinstance(status, str) or status not in STATUSES:
        raise ManifestError("manifest status is unsupported")
    repository = _require_exact_keys(
        top["repository"],
        "repository",
        {
            "remote",
            "candidate_sha",
            "candidate_tree_sha",
            "parent_sha",
            "trusted_base_sha",
            "ref",
        },
    )
    if repository["remote"] is not None:
        _require_string(repository["remote"], "repository.remote")
    _require_string(repository["ref"], "repository.ref", nullable=True)
    for key in (
        "candidate_sha",
        "candidate_tree_sha",
        "parent_sha",
        "trusted_base_sha",
    ):
        _require_full_sha(repository[key], "repository.{}".format(key), sha_length)
    scope = _require_exact_keys(
        top["scope"],
        "scope",
        {
            "expected_changed_files",
            "actual_changed_files",
            "added",
            "modified",
            "deleted",
            "renamed",
        },
    )
    for key in (
        "expected_changed_files",
        "actual_changed_files",
        "added",
        "modified",
        "deleted",
    ):
        values = scope[key]
        if not isinstance(values, list):
            raise ManifestError("scope.{} must be an array".format(key))
        checked = [
            _validate_path(path, "scope.{} path".format(key)) for path in values
        ]
        if checked != _path_sort(checked) or len(checked) != len(set(checked)):
            raise ManifestError(
                "scope.{} must be sorted and contain no duplicates".format(key)
            )
    if not isinstance(scope["renamed"], list):
        raise ManifestError("scope.renamed must be an array")
    checked_renames = []
    for index, item in enumerate(scope["renamed"]):
        rename = _require_exact_keys(
            item,
            "scope.renamed[{}]".format(index),
            {"from", "to"},
        )
        checked_renames.append(
            {
                "from": _validate_path(rename["from"], "rename source"),
                "to": _validate_path(rename["to"], "rename destination"),
            }
        )
    sorted_renames = sorted(
        checked_renames,
        key=lambda item: (item["from"].encode("utf-8"), item["to"].encode("utf-8")),
    )
    if checked_renames != sorted_renames:
        raise ManifestError("scope.renamed must be sorted")
    rename_pairs = [(item["from"], item["to"]) for item in checked_renames]
    if len(rename_pairs) != len(set(rename_pairs)):
        raise ManifestError("scope.renamed must not contain duplicates")
    if not isinstance(top["file_identities"], list):
        raise ManifestError("file_identities must be an array")
    identity_paths = []
    for index, item in enumerate(top["file_identities"]):
        identity = _require_exact_keys(
            item,
            "file_identities[{}]".format(index),
            {"path", "base_blob_sha", "candidate_blob_sha"},
        )
        identity_paths.append(
            _validate_path(identity["path"], "file identity path")
        )
        for key in ("base_blob_sha", "candidate_blob_sha"):
            if identity[key] is not None:
                _require_full_sha(
                    identity[key],
                    "file_identities[{}].{}".format(index, key),
                    sha_length,
                )
    if identity_paths != _path_sort(identity_paths) or len(identity_paths) != len(
        set(identity_paths)
    ):
        raise ManifestError("file_identities must be path-sorted without duplicates")
    diff_identity = _require_exact_keys(
        top["diff_identity"],
        "diff_identity",
        {"algorithm", "canonicalization", "digest"},
    )
    if (
        not isinstance(diff_identity["algorithm"], str)
        or diff_identity["algorithm"] != "sha256"
    ):
        raise ManifestError("diff_identity.algorithm must be sha256")
    if (
        not isinstance(diff_identity["canonicalization"], str)
        or diff_identity["canonicalization"] != DIFF_CANONICALIZATION
    ):
        raise ManifestError("diff_identity.canonicalization is unsupported")
    if not isinstance(diff_identity["digest"], str) or not _SHA256_RE.fullmatch(
        diff_identity["digest"]
    ):
        raise ManifestError("diff_identity.digest must be a lowercase SHA-256 digest")
    verification = _require_exact_keys(
        top["verification"],
        "verification",
        {"evidence", "postgresql"},
    )
    _validate_evidence(verification["evidence"])
    _validate_postgresql(verification["postgresql"])
    if status == "PASS" and not verification["evidence"]:
        raise ManifestError("PASS requires at least one verification evidence record")
    _validate_decision(top["decision"], status)
    _validate_no_likely_secrets(top)
    return repository, scope


def validate_manifest(
    manifest: Mapping[str, Any],
    repo: Path,
    *,
    expected_candidate_sha: str,
    expected_trusted_base_sha: str,
) -> Dict[str, Any]:
    """Validate a manifest against externally supplied trust anchors and Git."""

    root = _repository_root(repo)
    _, sha_length = _object_format(root)
    expected_candidate_sha = _require_full_sha(
        expected_candidate_sha, "expected candidate SHA", sha_length
    )
    expected_trusted_base_sha = _require_full_sha(
        expected_trusted_base_sha, "expected trusted base SHA", sha_length
    )
    repository, scope = _validate_manifest_shape(manifest, sha_length)
    if repository["candidate_sha"] != expected_candidate_sha:
        raise ManifestError("manifest candidate SHA differs from expected candidate SHA")
    if repository["trusted_base_sha"] != expected_trusted_base_sha:
        raise ManifestError(
            "manifest trusted base SHA differs from expected trusted base SHA"
        )
    candidate_tree, parents = _commit_identity(root, expected_candidate_sha, sha_length)
    _commit_identity(root, expected_trusted_base_sha, sha_length)
    if manifest["status"] == "PASS" and expected_candidate_sha in KNOWN_REVOKED_SHAS:
        raise ManifestError("known revoked candidate can never validate as PASS")
    if len(parents) != 1:
        raise ManifestError(
            "candidate commit must have exactly one parent; found {}".format(len(parents))
        )
    _assert_ancestor(root, expected_trusted_base_sha, expected_candidate_sha)
    if repository["candidate_tree_sha"] != candidate_tree:
        raise ManifestError("manifest tree SHA differs from candidate tree SHA")
    if repository["parent_sha"] != parents[0]:
        raise ManifestError("manifest parent SHA differs from candidate parent SHA")
    state = derive_repository_state(
        root,
        expected_candidate_sha,
        expected_trusted_base_sha,
    )
    if repository["remote"] != state["remote"]:
        raise ManifestError("manifest repository remote differs from repository origin")
    expected_files = set(scope["expected_changed_files"])
    actual_files = set(state["classification"]["actual_changed_files"])
    unexpected = _path_sort(actual_files - expected_files)
    missing = _path_sort(expected_files - actual_files)
    if unexpected:
        raise ManifestError(
            "unexpected changed files exist: {}".format(", ".join(unexpected))
        )
    if missing:
        raise ManifestError(
            "required expected changed files are missing: {}".format(", ".join(missing))
        )
    for key in ("actual_changed_files", "added", "modified", "deleted", "renamed"):
        if scope[key] != state["classification"][key]:
            raise ManifestError(
                "manifest {} classification differs from Git".format(key)
            )
    if manifest["file_identities"] != state["file_identities"]:
        raise ManifestError("manifest Git blob identities differ from Git")
    if manifest["diff_identity"]["digest"] != state["diff_digest"]:
        raise ManifestError("manifest deterministic diff digest differs from Git")
    return {
        "candidate_sha": expected_candidate_sha,
        "tree_sha": candidate_tree,
        "parent_sha": parents[0],
        "trusted_base_sha": expected_trusted_base_sha,
        "changed_files": state["classification"]["actual_changed_files"],
        "status": manifest["status"],
    }


def _reject_duplicate_keys(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError("manifest contains duplicate JSON key: {!r}".format(key))
        result[key] = value
    return result


def _reject_nonstandard_number(value: str) -> None:
    raise ManifestError("manifest contains a non-standard JSON number: {}".format(value))


def load_manifest(path: Path) -> Mapping[str, Any]:
    """Read one explicitly selected JSON manifest with bounded input size."""

    manifest_path = Path(path)
    try:
        size = manifest_path.stat().st_size
    except OSError as exc:
        raise ManifestError("cannot read manifest: {}".format(exc)) from exc
    if size > MAX_MANIFEST_BYTES:
        raise ManifestError("manifest exceeds {} bytes".format(MAX_MANIFEST_BYTES))
    try:
        raw = manifest_path.read_text(encoding="utf-8")
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonstandard_number,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError("manifest is not valid UTF-8 JSON: {}".format(exc)) from exc
    if not isinstance(value, dict):
        raise ManifestError("manifest root must be a JSON object")
    return value


def _parse_json_object(value: str, field: str) -> Mapping[str, Any]:
    try:
        parsed = json.loads(
            value,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonstandard_number,
        )
    except json.JSONDecodeError as exc:
        raise ManifestError("{} is not valid JSON: {}".format(field, exc)) from exc
    if not isinstance(parsed, dict):
        raise ManifestError("{} must be a JSON object".format(field))
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate or validate immutable Aurum checkpoint provenance."
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)

    generate = subparsers.add_parser("generate", help="derive a manifest from Git")
    generate.add_argument("--repo", default=".")
    generate.add_argument("--checkpoint-id", required=True)
    generate.add_argument("--candidate", default="HEAD")
    generate.add_argument("--trusted-base", required=True)
    generate.add_argument("--expected-file", action="append", required=True)
    generate.add_argument("--status", choices=sorted(STATUSES), default="CANDIDATE")
    generate.add_argument("--verifier")
    generate.add_argument("--evidence-json", action="append", default=[])
    generate.add_argument("--postgresql-json")
    generate.add_argument("--finding-reference", action="append", default=[])
    generate.add_argument("--known-exclusion", action="append", default=[])
    generate.add_argument("--unresolved-risk", action="append", default=[])
    generate.add_argument("--output", required=True)

    validate = subparsers.add_parser(
        "validate", help="re-derive Git state and compare a manifest"
    )
    validate.add_argument("manifest")
    validate.add_argument("--repo", default=".")
    validate.add_argument("--candidate", required=True)
    validate.add_argument("--trusted-base", required=True)
    return parser


def _main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.operation == "generate":
        evidence = [
            _parse_json_object(value, "--evidence-json")
            for value in args.evidence_json
        ]
        postgresql = (
            _parse_json_object(args.postgresql_json, "--postgresql-json")
            if args.postgresql_json
            else None
        )
        manifest = generate_manifest(
            Path(args.repo),
            checkpoint_id=args.checkpoint_id,
            candidate_sha=args.candidate,
            trusted_base_sha=args.trusted_base,
            expected_changed_files=args.expected_file,
            status=args.status,
            verifier=args.verifier,
            evidence=evidence,
            postgresql=postgresql,
            findings_references=args.finding_reference,
            known_exclusions=args.known_exclusion,
            unresolved_risks=args.unresolved_risk,
        )
        output = Path(args.output)
        try:
            output.write_text(
                json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            raise ManifestError("cannot write manifest: {}".format(exc)) from exc
        print(
            "generated {} manifest for commit {}".format(
                manifest["status"], manifest["repository"]["candidate_sha"]
            )
        )
        return 0

    manifest = load_manifest(Path(args.manifest))
    result = validate_manifest(
        manifest,
        Path(args.repo),
        expected_candidate_sha=args.candidate,
        expected_trusted_base_sha=args.trusted_base,
    )
    print(
        "valid {} manifest for commit {}, tree {}".format(
            result["status"], result["candidate_sha"], result["tree_sha"]
        )
    )
    return 0


def main() -> None:
    try:
        raise SystemExit(_main())
    except ManifestError as exc:
        print("checkpoint manifest error: {}".format(exc), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
