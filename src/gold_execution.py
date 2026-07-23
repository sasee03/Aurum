"""Contained PostgreSQL candidate execution for approved Gold runs."""

from __future__ import annotations

import logging
from typing import Any

import psycopg

from src.db_config import get_generated_sql_pool
from src.gold_catalog import (
    GoldCatalogResolutionError,
    lock_gold_sources,
    resolve_gold_execution_catalog,
)
from src.gold_security import (
    GoldSecurityState,
    build_approval_snapshot,
    revision_for,
)
from src.sql_safety import validate_generated_sql


logger = logging.getLogger(__name__)

GOLD_SQL_REJECTED = "GOLD_SQL_REJECTED"
GOLD_SOURCE_IDENTITY_CHANGED = "GOLD_SOURCE_IDENTITY_CHANGED"
GOLD_TARGET_IDENTITY_CHANGED = "GOLD_TARGET_IDENTITY_CHANGED"
GOLD_CANDIDATE_CONFLICT = "GOLD_CANDIDATE_CONFLICT"
GOLD_DATABASE_UNAVAILABLE = "GOLD_DATABASE_UNAVAILABLE"
GOLD_EXECUTION_FAILED = "GOLD_EXECUTION_FAILED"


class GoldExecutionRejected(RuntimeError):
    """A deterministic Gold execution failure with a sanitized public code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class GoldCommitOutcomeUnknown(RuntimeError):
    """PostgreSQL stopped acknowledging after CTAS, so commit outcome is unknown."""


def validate_approved_gold_sql(state: GoldSecurityState, sql_text: str) -> str:
    """Validate SQL using only persisted approved source/candidate authority."""
    return validate_generated_sql(
        sql_text,
        expected_schema=state.candidate["schema"],
        expected_table_name=state.target["table"],
        expected_candidate_name=state.candidate["table"],
        run_id=state.run_id,
        mode="gold_ctas",
        selected_sources=tuple(
            (source["schema"], source["table"])
            for source in state.selected_sources
        ),
    )


def _assert_live_approval_identity(
    state: GoldSecurityState,
    snapshot: Any,
) -> None:
    if (
        state.approval_snapshot is None
        or state.approved_revision is None
        or state.source_identities is None
        or state.target_identity is None
        or state.candidate_namespace_identity is None
        or state.overwrite_authorized is None
    ):
        raise GoldExecutionRejected(GOLD_EXECUTION_FAILED)

    approved_database = state.approval_snapshot["database"]
    if (
        snapshot.database_oid != approved_database["oid"]
        or snapshot.database_name != approved_database["name"]
        or tuple(snapshot.source_identities) != state.source_identities
    ):
        raise GoldExecutionRejected(GOLD_SOURCE_IDENTITY_CHANGED)
    if snapshot.target_identity != state.target_identity:
        raise GoldExecutionRejected(GOLD_TARGET_IDENTITY_CHANGED)
    if snapshot.candidate_namespace_identity != state.candidate_namespace_identity:
        raise GoldExecutionRejected(GOLD_TARGET_IDENTITY_CHANGED)

    rebuilt = build_approval_snapshot(
        review_snapshot=state.review_snapshot,
        review_revision=state.review_revision,
        database_oid=snapshot.database_oid,
        database_name=snapshot.database_name,
        source_identities=snapshot.source_identities,
        target_identity=snapshot.target_identity,
        candidate_namespace_identity=snapshot.candidate_namespace_identity,
        overwrite_authorized=state.overwrite_authorized,
    )
    if revision_for(rebuilt) != state.approved_revision:
        raise GoldExecutionRejected(GOLD_SOURCE_IDENTITY_CHANGED)


def _deterministic_transaction_error(exc: Exception) -> GoldExecutionRejected:
    """Map an error raised before commit begins to a sanitized known failure."""
    if isinstance(exc, GoldExecutionRejected):
        return exc
    if isinstance(exc, GoldCatalogResolutionError):
        if exc.area == "source":
            code = GOLD_SOURCE_IDENTITY_CHANGED
        elif exc.area in {"target", "candidate_namespace"}:
            code = GOLD_TARGET_IDENTITY_CHANGED
        elif exc.area == "candidate":
            code = GOLD_CANDIDATE_CONFLICT
        else:
            code = GOLD_DATABASE_UNAVAILABLE
        return GoldExecutionRejected(code)
    if isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError)):
        return GoldExecutionRejected(GOLD_DATABASE_UNAVAILABLE)
    return GoldExecutionRejected(GOLD_EXECUTION_FAILED)


def _execute_candidate_transaction(
    connection: Any,
    state: GoldSecurityState,
    sql_text: str,
) -> dict[str, Any]:
    """Run the transaction with an explicit commit-attempt boundary."""
    transaction = connection.transaction()
    try:
        transaction.__enter__()
    except Exception as exc:
        raise _deterministic_transaction_error(exc) from exc

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_catalog.set_config(%s, %s, true)",
                ("search_path", "pg_catalog"),
            )
            lock_gold_sources(cursor, state.selected_sources)
            live = resolve_gold_execution_catalog(
                cursor,
                selected_sources=state.selected_sources,
                target=state.target,
                candidate=state.candidate,
            )
            _assert_live_approval_identity(state, live)
            if live.candidate_identity is not None:
                raise GoldExecutionRejected(GOLD_CANDIDATE_CONFLICT)

            cursor.execute(sql_text)

            created_snapshot = resolve_gold_execution_catalog(
                cursor,
                selected_sources=state.selected_sources,
                target=state.target,
                candidate=state.candidate,
            )
            _assert_live_approval_identity(state, created_snapshot)
            created = created_snapshot.candidate_identity
            if (
                created is None
                or created["database_oid"]
                != state.candidate_namespace_identity["database_oid"]
                or created["namespace_oid"]
                != state.candidate_namespace_identity["namespace_oid"]
                or created["schema"] != state.candidate["schema"]
                or created["relation_name"] != state.candidate["table"]
                or created["relation_kind"] != "r"
            ):
                raise GoldExecutionRejected(GOLD_EXECUTION_FAILED)
    except Exception as exc:
        try:
            transaction.__exit__(type(exc), exc, exc.__traceback__)
        except Exception:
            logger.warning(
                "Gold candidate rollback cleanup failed after %s",
                type(exc).__name__,
            )
        rejection = _deterministic_transaction_error(exc)
        if rejection is exc:
            raise
        raise rejection from exc

    try:
        # From this call until it returns, commit acknowledgement is unknown.
        transaction.__exit__(None, None, None)
    except Exception as exc:
        raise GoldCommitOutcomeUnknown() from exc
    return created


def execute_gold_candidate(
    state: GoldSecurityState,
    sql_text: str,
    *,
    pool: Any | None = None,
) -> dict[str, Any]:
    """Create the approved candidate in one pooled PostgreSQL transaction.

    The transaction-local search path contains only ``pg_catalog``. All physical
    data relations and the CREATE target must therefore be explicitly qualified;
    PostgreSQL built-ins remain available through the system catalog.
    """
    try:
        validate_approved_gold_sql(state, sql_text)
    except Exception as exc:
        raise GoldExecutionRejected(GOLD_SQL_REJECTED) from exc

    active_pool = pool or get_generated_sql_pool()
    try:
        connection_context = active_pool.connection()
        connection = connection_context.__enter__()
    except Exception as exc:
        raise GoldExecutionRejected(GOLD_DATABASE_UNAVAILABLE) from exc

    committed_candidate: dict[str, Any] | None = None
    pending_error: Exception | None = None
    try:
        committed_candidate = _execute_candidate_transaction(
            connection,
            state,
            sql_text,
        )
    except Exception as exc:
        pending_error = exc

    try:
        connection_context.__exit__(
            type(pending_error) if pending_error is not None else None,
            pending_error,
            pending_error.__traceback__ if pending_error is not None else None,
        )
    except Exception as cleanup_error:
        if committed_candidate is not None:
            logger.warning(
                "Gold candidate committed; pooled connection cleanup raised %s",
                type(cleanup_error).__name__,
            )
            return committed_candidate
        if pending_error is not None:
            raise pending_error from cleanup_error
        raise GoldExecutionRejected(GOLD_DATABASE_UNAVAILABLE) from cleanup_error

    if pending_error is not None:
        raise pending_error
    if committed_candidate is None:
        raise GoldExecutionRejected(GOLD_EXECUTION_FAILED)
    return committed_candidate
