"""Authenticated authority primitives for Gold origin and approval.

This module provides:
  - HMAC-SHA256 computation and verification using the backend-only authority key
  - Versioned deterministic canonical serialization for MAC inputs
  - A strict fail-closed provenance registry
  - Hardened OID validation

Security invariants:
  - AURUM_AUTHORITY_HMAC_KEY is never stored in SQLite, git, the frontend,
    or any API response.
  - All Gold authority paths fail closed when the key is absent.
  - hmac.compare_digest is used for all MAC comparisons.
  - Canonical serialization uses json.dumps with sort_keys and no floats/NaN.
"""

from __future__ import annotations

import hmac
import hashlib
import json
import logging
import os
from typing import Any

from src.gold_security import GoldStateMalformed


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public version tokens
# ---------------------------------------------------------------------------

GOLD_ORIGIN_MAC_PACKAGE_VERSION = "gold-origin-authority-v1"
GOLD_APPROVAL_MAC_PACKAGE_VERSION = "gold-approval-authority-v1"

# ---------------------------------------------------------------------------
# Provenance → snapshot-contract registry
# ---------------------------------------------------------------------------

MANUAL_CONTROLLED_GOLD_PROVENANCE = "manual_controlled_gold_v1"
STRUCTURED_DETERMINISTIC_GOLD_PROVENANCE = "structured_deterministic_gold_v1"

# The only legal mappings.  Anything else is rejected.
_PROVENANCE_SNAPSHOT_REGISTRY: dict[str, str] = {
    MANUAL_CONTROLLED_GOLD_PROVENANCE: "gold-review-snapshot-v1",
    STRUCTURED_DETERMINISTIC_GOLD_PROVENANCE: "gold-review-snapshot-v2",
}


class GoldProvenanceMismatch(GoldStateMalformed):
    """Provenance / snapshot-contract pairing is not in the registry."""


def validate_provenance_snapshot_contract(
    provenance: str,
    snapshot_version: str,
) -> None:
    """Fail closed if (provenance, snapshot_version) is not an exact registered pair.

    Rejects:
      - unknown provenances
      - cross-version pairings (manual+v2, structured+v1)
      - near-miss / whitespace / case variants
      - null / empty values
    No trimming.  No aliases.  No permissive fallback.
    """
    if not isinstance(provenance, str) or not isinstance(snapshot_version, str):
        raise GoldProvenanceMismatch(
            "provenance and snapshot version must be non-empty strings"
        )
    expected = _PROVENANCE_SNAPSHOT_REGISTRY.get(provenance)
    if expected is None:
        raise GoldProvenanceMismatch(
            f"unknown generator provenance: provenance is not registered"
        )
    if snapshot_version != expected:
        raise GoldProvenanceMismatch(
            f"provenance/snapshot contract mismatch: "
            f"provenance requires snapshot {expected!r}"
        )


# ---------------------------------------------------------------------------
# OID validation
# ---------------------------------------------------------------------------

_OID_MAX = 2 ** 32  # exclusive upper bound


def require_oid_strict(value: Any, *, field: str) -> int:
    """Return value as a valid PostgreSQL OID or raise GoldStateMalformed.

    Accepts only plain Python int in range (0, 2**32).
    Rejects: bool (subclass of int), string, zero, negative, >= 2**32.
    """
    # bool is a subclass of int in Python — must be checked first.
    if isinstance(value, bool):
        raise GoldStateMalformed(f"{field} is not a valid PostgreSQL OID (bool)")
    if not isinstance(value, int):
        raise GoldStateMalformed(f"{field} is not a valid PostgreSQL OID (not int)")
    if value <= 0:
        raise GoldStateMalformed(
            f"{field} is not a valid PostgreSQL OID (must be > 0)"
        )
    if value >= _OID_MAX:
        raise GoldStateMalformed(
            f"{field} is not a valid PostgreSQL OID (must be < 2**32)"
        )
    return value


# ---------------------------------------------------------------------------
# Backend authority key
# ---------------------------------------------------------------------------

_KEY_ENV_VAR = "AURUM_AUTHORITY_HMAC_KEY"


class GoldAuthorityKeyMissing(GoldStateMalformed):
    """AURUM_AUTHORITY_HMAC_KEY is not configured; Gold authority paths fail closed."""


def _load_authority_key() -> bytes:
    """Load the backend HMAC key from the environment.

    Raises GoldAuthorityKeyMissing if the variable is absent or empty.
    The key value is never logged, never returned to callers outside this
    module, and never stored in SQLite.
    """
    raw = os.environ.get(_KEY_ENV_VAR, "")
    if not raw:
        raise GoldAuthorityKeyMissing(
            f"{_KEY_ENV_VAR} is not set; Gold authority operations are disabled"
        )
    return raw.encode("utf-8")


# ---------------------------------------------------------------------------
# Deterministic canonical serialization
# ---------------------------------------------------------------------------

def _canonical_mac_input(package: dict[str, Any]) -> bytes:
    """Serialize a MAC input package to canonical UTF-8 JSON bytes.

    Rules:
      - sort_keys=True for determinism across key insertion order
      - ensure_ascii=False (UTF-8 safe)
      - allow_nan=False (NaN/Inf are rejected — they are not canonical)
      - compact separators (",", ":")
    """
    try:
        return json.dumps(
            package,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise GoldStateMalformed(
            "MAC input package is not canonicalizable"
        ) from exc


# ---------------------------------------------------------------------------
# HMAC-SHA256 computation and verification
# ---------------------------------------------------------------------------

def _compute_mac(key: bytes, data: bytes) -> str:
    """Return hex-encoded HMAC-SHA256 of data under key."""
    return hmac.new(key, data, hashlib.sha256).hexdigest()


def compute_origin_mac(package: dict[str, Any]) -> str:
    """Compute the authenticated origin MAC for a new Gold run.

    Raises GoldAuthorityKeyMissing if the key is not configured.
    """
    key = _load_authority_key()
    data = _canonical_mac_input(package)
    return _compute_mac(key, data)


def verify_origin_mac(package: dict[str, Any], expected_mac: str) -> None:
    """Verify origin_mac against the canonical package.

    Raises GoldStateMalformed on any failure so callers can fail closed.
    Uses hmac.compare_digest to prevent timing side-channels.
    """
    if not isinstance(expected_mac, str) or not expected_mac:
        raise GoldStateMalformed("origin_mac is missing or not a string")
    try:
        key = _load_authority_key()
    except GoldAuthorityKeyMissing:
        raise
    data = _canonical_mac_input(package)
    actual = _compute_mac(key, data)
    if not hmac.compare_digest(actual, expected_mac):
        raise GoldStateMalformed("origin MAC verification failed")


def compute_approval_mac(package: dict[str, Any]) -> str:
    """Compute the authenticated approval MAC after successful explicit approval.

    Raises GoldAuthorityKeyMissing if the key is not configured.
    """
    key = _load_authority_key()
    data = _canonical_mac_input(package)
    return _compute_mac(key, data)


def verify_approval_mac(package: dict[str, Any], expected_mac: str) -> None:
    """Verify approval_mac against the canonical package.

    Raises GoldStateMalformed on any failure so callers can fail closed.
    Uses hmac.compare_digest to prevent timing side-channels.
    """
    if not isinstance(expected_mac, str) or not expected_mac:
        raise GoldStateMalformed("approval_mac is missing or not a string")
    try:
        key = _load_authority_key()
    except GoldAuthorityKeyMissing:
        raise
    data = _canonical_mac_input(package)
    actual = _compute_mac(key, data)
    if not hmac.compare_digest(actual, expected_mac):
        raise GoldStateMalformed("approval MAC verification failed")


# ---------------------------------------------------------------------------
# Origin MAC package builder
# ---------------------------------------------------------------------------

def build_origin_mac_package(
    *,
    run_id: str,
    origin_provenance: str,
    snapshot_contract_version: str,
    generator_family: str,
    generator_model: str | None,
    database_oid: int,
    database_name: str,
    source_namespace_oid: int,
    source_relation_oid: int,
    source_schema: str,
    source_relation_name: str,
    source_relation_kind: str,
    created_at: str,
) -> dict[str, Any]:
    """Return the canonical origin MAC input package.

    All fields are validated for type / non-emptiness before inclusion.
    The package_version pins the serialization contract so future format
    changes can coexist.
    """
    if not isinstance(run_id, str) or not run_id:
        raise GoldStateMalformed("origin run_id must be a non-empty string")
    if not isinstance(origin_provenance, str) or not origin_provenance:
        raise GoldStateMalformed("origin_provenance must be a non-empty string")
    if not isinstance(snapshot_contract_version, str) or not snapshot_contract_version:
        raise GoldStateMalformed(
            "snapshot_contract_version must be a non-empty string"
        )
    if not isinstance(generator_family, str) or not generator_family:
        raise GoldStateMalformed("generator_family must be a non-empty string")
    if generator_model is not None and not isinstance(generator_model, str):
        raise GoldStateMalformed("generator_model must be a string or None")
    if not isinstance(database_name, str) or not database_name:
        raise GoldStateMalformed("database_name must be a non-empty string")
    if not isinstance(source_schema, str) or not source_schema:
        raise GoldStateMalformed("source_schema must be a non-empty string")
    if not isinstance(source_relation_name, str) or not source_relation_name:
        raise GoldStateMalformed("source_relation_name must be a non-empty string")
    if not isinstance(source_relation_kind, str) or not source_relation_kind:
        raise GoldStateMalformed("source_relation_kind must be a non-empty string")
    if not isinstance(created_at, str) or not created_at:
        raise GoldStateMalformed("created_at must be a non-empty string")

    # OID fields use the strict validator
    database_oid = require_oid_strict(database_oid, field="origin.database_oid")
    source_namespace_oid = require_oid_strict(
        source_namespace_oid, field="origin.source_namespace_oid"
    )
    source_relation_oid = require_oid_strict(
        source_relation_oid, field="origin.source_relation_oid"
    )

    return {
        "package_version": GOLD_ORIGIN_MAC_PACKAGE_VERSION,
        "run_id": run_id,
        "origin_provenance": origin_provenance,
        "snapshot_contract_version": snapshot_contract_version,
        "generator_family": generator_family,
        "generator_model": generator_model,
        "database": {
            "oid": database_oid,
            "name": database_name,
        },
        "source": {
            "namespace_oid": source_namespace_oid,
            "relation_oid": source_relation_oid,
            "schema": source_schema,
            "relation_name": source_relation_name,
            "relation_kind": source_relation_kind,
        },
        "created_at": created_at,
    }


# ---------------------------------------------------------------------------
# Approval MAC package builder
# ---------------------------------------------------------------------------

def build_approval_mac_package(
    *,
    run_id: str,
    origin_mac: str,
    review_revision: str,
    approved_revision: str,
    approval_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Return the canonical approval MAC input package.

    The package authenticates the complete authority bundle consumed by
    execution and promotion:
      - run_id (binds to the exact run)
      - origin_mac (authenticated generation identity)
      - review_revision (CAS staleness token that was current at approval)
      - approved_revision (revision of the approval_snapshot)
      - approval_snapshot (canonical complete snapshot: SQL, sources, target,
        candidate, overwrite_authorized, database, review_snapshot)

    Fields consumed by execute/promote that are not already in
    approval_snapshot (sql_text, source_identities, target_identity,
    candidate_namespace_identity, overwrite_authorized, database OID/name,
    review_snapshot containing generator_provenance and candidate schema) are
    all captured inside approval_snapshot, so no duplication is needed.
    """
    if not isinstance(run_id, str) or not run_id:
        raise GoldStateMalformed("approval run_id must be a non-empty string")
    if not isinstance(origin_mac, str) or not origin_mac:
        raise GoldStateMalformed("origin_mac must be a non-empty string")
    if not isinstance(review_revision, str) or len(review_revision) != 64:
        raise GoldStateMalformed(
            "review_revision must be a 64-character hex string"
        )
    if not isinstance(approved_revision, str) or len(approved_revision) != 64:
        raise GoldStateMalformed(
            "approved_revision must be a 64-character hex string"
        )
    if not isinstance(approval_snapshot, dict):
        raise GoldStateMalformed("approval_snapshot must be a dict")

    return {
        "package_version": GOLD_APPROVAL_MAC_PACKAGE_VERSION,
        "run_id": run_id,
        "origin_mac": origin_mac,
        "review_revision": review_revision,
        "approved_revision": approved_revision,
        "approval_snapshot": approval_snapshot,
    }
