"""Regression tests for immutable checkpoint provenance manifests."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "checkpoint_manifest.py"
SPEC = importlib.util.spec_from_file_location("checkpoint_manifest", SCRIPT_PATH)
assert SPEC and SPEC.loader
checkpoint_manifest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checkpoint_manifest)

APPROVED_ECC_A = "9453e3c879e29c89f98c5104aac779a1093c61c4"
APPROVED_ECC_B = "1480cce85d764127b7fefa0095a968bbc35dff9f"
TRUSTED_PRE_CHECKPOINT_BASE = "7115d98f0009c360757c16d4425f3ed8b2c463a4"
REVOKED_SHA = "827f0efc002a7f79cc361e44627f952885cd60d5"


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "--all")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def history(tmp_path):
    repo = tmp_path / "repository"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Aurum Test")
    _git(repo, "config", "user.email", "aurum-test@example.invalid")
    (repo / "modified.txt").write_text("before\n", encoding="utf-8")
    (repo / "deleted.txt").write_text("delete me\n", encoding="utf-8")
    (repo / "renamed-from.txt").write_text("rename me\n", encoding="utf-8")
    base = _commit(repo, "base")

    (repo / "modified.txt").write_text("after\n", encoding="utf-8")
    (repo / "deleted.txt").unlink()
    (repo / "added.txt").write_text("new\n", encoding="utf-8")
    (repo / "renamed-from.txt").rename(repo / "renamed-to.txt")
    candidate = _commit(repo, "candidate")
    expected = [
        "added.txt",
        "deleted.txt",
        "modified.txt",
        "renamed-from.txt",
        "renamed-to.txt",
    ]
    manifest = checkpoint_manifest.generate_manifest(
        repo,
        checkpoint_id="TEST-CANDIDATE",
        candidate_sha=candidate,
        trusted_base_sha=base,
        expected_changed_files=expected,
    )
    return {
        "repo": repo,
        "base": base,
        "candidate": candidate,
        "expected": expected,
        "manifest": manifest,
    }


def _validate(history, manifest=None, *, candidate=None, base=None):
    return checkpoint_manifest.validate_manifest(
        manifest or history["manifest"],
        history["repo"],
        expected_candidate_sha=candidate or history["candidate"],
        expected_trusted_base_sha=base or history["base"],
    )


def _passing_evidence():
    return {
        "exact_command": "python -m pytest tests/test_checkpoint_manifest.py",
        "context": "isolated verifier worktree",
        "exit_code": 0,
        "classification": "unit",
        "result_summary": "checkpoint manifest tests passed",
        "test_counts": {
            "collected": 1,
            "executed": 1,
            "passed": 1,
            "failed": 0,
            "skipped": 0,
            "xfailed": 0,
            "xpassed": 0,
        },
    }


def test_valid_manifest_binds_real_git_state(history):
    result = _validate(history)

    assert result == {
        "candidate_sha": history["candidate"],
        "tree_sha": history["manifest"]["repository"]["candidate_tree_sha"],
        "parent_sha": history["base"],
        "trusted_base_sha": history["base"],
        "changed_files": history["expected"],
        "status": "CANDIDATE",
    }
    assert history["manifest"]["scope"]["renamed"] == [
        {"from": "renamed-from.txt", "to": "renamed-to.txt"}
    ]


def test_real_approved_ecc_b_history_validates():
    state = checkpoint_manifest.derive_repository_state(
        REPOSITORY_ROOT,
        APPROVED_ECC_B,
        APPROVED_ECC_A,
    )
    manifest = checkpoint_manifest.generate_manifest(
        REPOSITORY_ROOT,
        checkpoint_id="ECC-B-REAL-HISTORY-REGRESSION",
        candidate_sha=APPROVED_ECC_B,
        trusted_base_sha=APPROVED_ECC_A,
        expected_changed_files=state["classification"]["actual_changed_files"],
    )

    result = checkpoint_manifest.validate_manifest(
        manifest,
        REPOSITORY_ROOT,
        expected_candidate_sha=APPROVED_ECC_B,
        expected_trusted_base_sha=APPROVED_ECC_A,
    )

    assert result["candidate_sha"] == APPROVED_ECC_B
    assert result["tree_sha"] == "336e9e3ceda9dd221f392e1d8575c8a64886c80f"
    assert result["parent_sha"] == APPROVED_ECC_A


def test_wrong_candidate_sha_is_rejected(history):
    manifest = copy.deepcopy(history["manifest"])
    manifest["repository"]["candidate_sha"] = history["base"]

    with pytest.raises(
        checkpoint_manifest.ManifestError,
        match="candidate SHA differs",
    ):
        _validate(history, manifest)


def test_nonexistent_candidate_commit_is_rejected(history):
    missing_sha = "0" * 40
    manifest = copy.deepcopy(history["manifest"])
    manifest["repository"]["candidate_sha"] = missing_sha

    with pytest.raises(checkpoint_manifest.ManifestError, match="Git command failed"):
        _validate(history, manifest, candidate=missing_sha)


def test_wrong_tree_sha_is_rejected(history):
    manifest = copy.deepcopy(history["manifest"])
    manifest["repository"]["candidate_tree_sha"] = "0" * 40

    with pytest.raises(checkpoint_manifest.ManifestError, match="tree SHA differs"):
        _validate(history, manifest)


def test_wrong_parent_sha_is_rejected(history):
    manifest = copy.deepcopy(history["manifest"])
    manifest["repository"]["parent_sha"] = "0" * 40

    with pytest.raises(checkpoint_manifest.ManifestError, match="parent SHA differs"):
        _validate(history, manifest)


def test_invalid_trusted_base_ancestry_is_rejected(history):
    (history["repo"] / "later.txt").write_text("later\n", encoding="utf-8")
    later = _commit(history["repo"], "later")
    manifest = copy.deepcopy(history["manifest"])
    manifest["repository"]["trusted_base_sha"] = later

    with pytest.raises(checkpoint_manifest.ManifestError, match="is not an ancestor"):
        _validate(history, manifest, base=later)


def test_unexpected_changed_file_is_rejected(history):
    manifest = copy.deepcopy(history["manifest"])
    manifest["scope"]["expected_changed_files"].remove("added.txt")

    with pytest.raises(checkpoint_manifest.ManifestError, match="unexpected changed files"):
        _validate(history, manifest)


def test_missing_expected_changed_file_is_rejected(history):
    manifest = copy.deepcopy(history["manifest"])
    manifest["scope"]["expected_changed_files"].append("not-in-candidate.txt")
    manifest["scope"]["expected_changed_files"].sort()

    with pytest.raises(
        checkpoint_manifest.ManifestError,
        match="required expected changed files are missing",
    ):
        _validate(history, manifest)


def test_blob_identity_mismatch_is_rejected(history):
    manifest = copy.deepcopy(history["manifest"])
    identity = next(
        item
        for item in manifest["file_identities"]
        if item["candidate_blob_sha"] is not None
    )
    identity["candidate_blob_sha"] = "0" * 40

    with pytest.raises(checkpoint_manifest.ManifestError, match="blob identities"):
        _validate(history, manifest)


def test_diff_digest_mismatch_is_rejected(history):
    manifest = copy.deepcopy(history["manifest"])
    manifest["diff_identity"]["digest"] = "0" * 64

    with pytest.raises(checkpoint_manifest.ManifestError, match="diff digest"):
        _validate(history, manifest)


@pytest.mark.parametrize("classification", ["added", "modified", "deleted", "renamed"])
def test_change_classification_mismatch_is_rejected(history, classification):
    manifest = copy.deepcopy(history["manifest"])
    manifest["scope"][classification] = []

    with pytest.raises(checkpoint_manifest.ManifestError, match="classification differs"):
        _validate(history, manifest)


def test_known_revoked_real_commit_can_never_validate_as_pass():
    assert _git(REPOSITORY_ROOT, "cat-file", "-t", REVOKED_SHA) == "commit"
    state = checkpoint_manifest.derive_repository_state(
        REPOSITORY_ROOT,
        REVOKED_SHA,
        TRUSTED_PRE_CHECKPOINT_BASE,
    )
    manifest = checkpoint_manifest.generate_manifest(
        REPOSITORY_ROOT,
        checkpoint_id="REVOKED-REAL-HISTORY-REGRESSION",
        candidate_sha=REVOKED_SHA,
        trusted_base_sha=TRUSTED_PRE_CHECKPOINT_BASE,
        expected_changed_files=state["classification"]["actual_changed_files"],
    )
    manifest["status"] = "PASS"
    manifest["verification"]["evidence"] = [_passing_evidence()]
    manifest["decision"] = {
        "verifier_identifier": "independent-verifier",
        "outcome": "PASS",
        "findings_references": [],
        "known_exclusions": [],
        "unresolved_risks": [],
    }

    with pytest.raises(checkpoint_manifest.ManifestError, match="known revoked"):
        checkpoint_manifest.validate_manifest(
            manifest,
            REPOSITORY_ROOT,
            expected_candidate_sha=REVOKED_SHA,
            expected_trusted_base_sha=TRUSTED_PRE_CHECKPOINT_BASE,
        )


def test_malformed_json_is_rejected(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text('{"schema_version": ', encoding="utf-8")

    with pytest.raises(checkpoint_manifest.ManifestError, match="not valid UTF-8 JSON"):
        checkpoint_manifest.load_manifest(manifest_path)


def test_malformed_manifest_shape_is_rejected(history):
    manifest = copy.deepcopy(history["manifest"])
    del manifest["repository"]["candidate_tree_sha"]

    with pytest.raises(checkpoint_manifest.ManifestError, match="missing required keys"):
        _validate(history, manifest)


def test_duplicate_json_keys_are_rejected(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text('{"schema_version": 1, "schema_version": 1}', encoding="utf-8")

    with pytest.raises(checkpoint_manifest.ManifestError, match="duplicate JSON key"):
        checkpoint_manifest.load_manifest(manifest_path)


def test_unsupported_schema_version_is_rejected(history):
    manifest = copy.deepcopy(history["manifest"])
    manifest["schema_version"] = 2

    with pytest.raises(checkpoint_manifest.ManifestError, match="unsupported manifest"):
        _validate(history, manifest)


@pytest.mark.parametrize("malformed_status", [[], {}, True, 1])
def test_malformed_status_type_fails_closed(history, malformed_status):
    manifest = copy.deepcopy(history["manifest"])
    manifest["status"] = malformed_status

    with pytest.raises(checkpoint_manifest.ManifestError, match="status is unsupported"):
        _validate(history, manifest)


def test_abbreviated_manifest_sha_is_rejected(history):
    manifest = copy.deepcopy(history["manifest"])
    manifest["repository"]["candidate_sha"] = history["candidate"][:12]

    with pytest.raises(checkpoint_manifest.ManifestError, match="full 40-character"):
        _validate(history, manifest)


def test_abbreviated_external_trust_anchor_is_rejected(history):
    with pytest.raises(checkpoint_manifest.ManifestError, match="full 40-character"):
        checkpoint_manifest.validate_manifest(
            history["manifest"],
            history["repo"],
            expected_candidate_sha=history["candidate"][:12],
            expected_trusted_base_sha=history["base"],
        )


def test_manifest_command_is_data_and_is_never_executed(history, tmp_path):
    sentinel = tmp_path / "must-not-exist"
    manifest = copy.deepcopy(history["manifest"])
    manifest["verification"]["evidence"] = [
        {
            "exact_command": '{} -c "from pathlib import Path; Path(r\'{}\').touch()"'.format(
                sys.executable,
                sentinel,
            ),
            "context": "hostile manifest regression",
            "exit_code": 0,
            "classification": "security-negative",
            "result_summary": "this command is inert manifest data",
        }
    ]

    _validate(history, manifest)

    assert not sentinel.exists()


def test_path_traversal_in_expected_scope_is_rejected(history):
    manifest = copy.deepcopy(history["manifest"])
    manifest["scope"]["expected_changed_files"][0] = "../outside"

    with pytest.raises(checkpoint_manifest.ManifestError, match="normalized repository"):
        _validate(history, manifest)


def test_likely_secret_in_evidence_is_rejected(history):
    manifest = copy.deepcopy(history["manifest"])
    manifest["verification"]["evidence"] = [
        {
            "exact_command": "tool --password=hunter2",
            "context": "unsafe example",
            "exit_code": 0,
            "classification": "security-negative",
            "result_summary": "must be rejected",
        }
    ]

    with pytest.raises(checkpoint_manifest.ManifestError, match="credential or secret"):
        _validate(history, manifest)


@pytest.mark.parametrize("status", ["PASS", "FAIL", "REVOKED"])
def test_terminal_decisions_are_bound_to_status(history, status):
    evidence = [_passing_evidence()] if status == "PASS" else []
    manifest = checkpoint_manifest.generate_manifest(
        history["repo"],
        checkpoint_id="TEST-{}".format(status),
        candidate_sha=history["candidate"],
        trusted_base_sha=history["base"],
        expected_changed_files=history["expected"],
        status=status,
        verifier="independent-verifier",
        evidence=evidence,
    )

    result = _validate(history, manifest)

    assert result["status"] == status
    assert manifest["decision"]["outcome"] == status


def test_cli_generate_then_validate(history, tmp_path):
    output = tmp_path / "checkpoint.json"
    generate_command = [
        sys.executable,
        str(SCRIPT_PATH),
        "generate",
        "--repo",
        str(history["repo"]),
        "--checkpoint-id",
        "CLI-ROUND-TRIP",
        "--candidate",
        history["candidate"],
        "--trusted-base",
        history["base"],
        "--output",
        str(output),
    ]
    for path in history["expected"]:
        generate_command.extend(["--expected-file", path])

    generated = subprocess.run(
        generate_command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    validated = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "validate",
            str(output),
            "--repo",
            str(history["repo"]),
            "--candidate",
            history["candidate"],
            "--trusted-base",
            history["base"],
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert generated.returncode == 0, generated.stderr
    assert validated.returncode == 0, validated.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["checkpoint_id"] == "CLI-ROUND-TRIP"
