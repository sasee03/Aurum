"""API Router for Aurum system administration and maintenance."""

from __future__ import annotations

import hmac
import os
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from src.candidate_cleanup import cleanup_orphaned_candidate_tables

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
    """Fail closed before destructive cleanup code can acquire authority."""
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


@router.post(
    "/candidate-cleanup",
    dependencies=[Depends(require_destructive_admin_operator)],
)
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
