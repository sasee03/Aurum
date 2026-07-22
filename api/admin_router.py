"""API Router for Aurum system administration and maintenance."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from src.candidate_cleanup import cleanup_orphaned_candidate_tables

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


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
