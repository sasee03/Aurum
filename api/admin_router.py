"""API Router for Aurum system administration and maintenance."""

from __future__ import annotations

import hmac
import os
from typing import Optional
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from src.candidate_cleanup import cleanup_orphaned_candidate_tables
from src.gold_backup_cleanup import (
    GOLD_BACKUP_IDENTITY_MISMATCH,
    GoldBackupCleanupOutcomeUnknown,
    GoldBackupCleanupRejected,
    GoldBackupCleanupStateRecordingFailed,
    authorize_gold_backup_cleanup,
    cleanup_gold_backup,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

DESTRUCTIVE_ADMIN_ENABLE_ENV = "AURUM_ENABLE_DESTRUCTIVE_ADMIN"
DESTRUCTIVE_ADMIN_TOKEN_ENV = "AURUM_DESTRUCTIVE_ADMIN_TOKEN"
DESTRUCTIVE_ADMIN_TOKEN_HEADER = "X-Aurum-Operator-Token"


def require_destructive_admin_operator(
    operator_token: Optional[str] = Header(
        None,
        alias=DESTRUCTIVE_ADMIN_TOKEN_HEADER,
        description="Server-configured operator credential.",
    ),
) -> None:
    """Fail closed unless this deployment and caller authorize destruction."""
    enabled = (
        os.getenv(DESTRUCTIVE_ADMIN_ENABLE_ENV, "").strip().lower()
        == "true"
    )
    expected_token = os.getenv(DESTRUCTIVE_ADMIN_TOKEN_ENV, "")
    if not enabled or not expected_token.strip():
        raise HTTPException(
            status_code=404,
            detail="Destructive administrative operations are unavailable.",
        )
    supplied = operator_token or ""
    if not hmac.compare_digest(
        supplied.encode("utf-8"),
        expected_token.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=403,
            detail="Valid operator authorization is required.",
        )


@router.post("/candidate-cleanup")
def trigger_candidate_cleanup(
    confirm: bool = Query(
        False,
        description="Must be explicitly set to True to execute destructive candidate table cleanup."
    ),
    age_threshold_seconds: int = Query(
        3600, 
        ge=0, 
        description="Candidate table age threshold in seconds (default: 3600s / 1 hour)"
    )
):
    """Trigger manual candidate table hygiene cleanup."""
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Action requires explicit confirmation. Pass '?confirm=true' to proceed with candidate cleanup."
        )
    try:
        res = cleanup_orphaned_candidate_tables(age_threshold_seconds=age_threshold_seconds)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to perform candidate cleanup: {e}")


@router.post(
    "/gold-backup-cleanup/{run_id}",
    dependencies=[Depends(require_destructive_admin_operator)],
)
def trigger_gold_backup_cleanup(
    run_id: str,
    confirm: bool = Query(
        False,
        description=(
            "Must be explicitly true to authorize cleanup of this run's "
            "exact persisted Gold backup."
        ),
    ),
):
    """Explicitly authorize and clean one strictly promoted Gold backup."""
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail=(
                "Action requires explicit confirmation. Pass '?confirm=true' "
                "to authorize exact-identity Gold backup cleanup."
            ),
        )
    try:
        authorize_gold_backup_cleanup(run_id)
        result = cleanup_gold_backup(run_id)
    except GoldBackupCleanupOutcomeUnknown:
        raise HTTPException(
            status_code=500,
            detail=(
                "Gold backup cleanup commit outcome is unknown. "
                "Retry exact-identity reconciliation before further action."
            ),
        ) from None
    except GoldBackupCleanupStateRecordingFailed:
        raise HTTPException(
            status_code=500,
            detail=(
                "Gold backup cleanup database outcome is known, but app-state "
                "recording failed. Retry reconciliation before further action."
            ),
        ) from None
    except GoldBackupCleanupRejected as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if result.outcome == GOLD_BACKUP_IDENTITY_MISMATCH:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "GOLD_BACKUP_IDENTITY_MISMATCH",
                "message": (
                    "The live relation does not match the exact persisted "
                    "backup identity. It was preserved."
                ),
                "backup_identity": result.backup_identity,
            },
        )
    return {
        "status": result.outcome,
        "run_id": result.run_id,
        "outcome": result.outcome,
        "backup_identity": result.backup_identity,
    }


@router.post(
    "/gold-backup-cleanup/{run_id}/reconcile",
    dependencies=[Depends(require_destructive_admin_operator)],
)
def trigger_gold_backup_cleanup_reconciliation(run_id: str):
    """Read-first exact-OID cleanup reconciliation; never issues DROP."""
    try:
        return reconcile_gold_backup_cleanup(run_id)
    except GoldBackupCleanupNotEligible as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except (
        GoldBackupCleanupReconciliationRequired,
        GoldCandidateCleanupError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None

reconcile_gold_backup_cleanup = trigger_gold_backup_cleanup_reconciliation

