"""Contained PostgreSQL candidate execution for approved Gold runs."""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from psycopg import sql

from src.db_config import POSTGRES_PROMOTION_ROLE, get_generated_sql_pool
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
from src.sql_safety import validate_generated_sql, extract_gold_physical_sources


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


def _validate_approved_gold_plan(
    state: GoldSecurityState,
    sql_text: str,
) -> tuple[str, tuple[dict[str, str], ...]]:
    """Internal core for validating approved Gold SQL and extracting used physical sources."""
    val_sql = validate_generated_sql(
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
    raw_used = extract_gold_physical_sources(
        sql_text,
        selected_sources=tuple(
            (source["schema"], source["table"])
            for source in state.selected_sources
        ),
    )
    used_sources = tuple({"schema": s, "table": t} for s, t in raw_used)
    return val_sql, used_sources


def validate_approved_gold_sql(
    state: GoldSecurityState,
    sql_text: str,
) -> str:
    """Validate approved Gold SQL and return normalized SQL text string."""
    val_sql, _ = _validate_approved_gold_plan(state, sql_text)
    return val_sql


def validate_approved_gold_execution_plan(
    state: GoldSecurityState,
    sql_text: str,
) -> tuple[str, tuple[dict[str, str], ...]]:
    """Validate approved Gold SQL and return (normalized_sql, used_physical_sources)."""
    return _validate_approved_gold_plan(state, sql_text)


def _assert_live_approval_identity(
    state: GoldSecurityState,
    snapshot: Any,
    expected_source_identities: tuple[dict[str, Any], ...] | None = None,
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
    target_expected_sources = (
        expected_source_identities
        if expected_source_identities is not None
        else state.source_identities
    )
    if (
        snapshot.database_oid != approved_database["oid"]
        or snapshot.database_name != approved_database["name"]
        or tuple(snapshot.source_identities) != target_expected_sources
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
        source_identities=state.source_identities,
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
    physical_used_sources: tuple[dict[str, str], ...],
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
            # Scope untrusted candidate CTAS execution strictly to aurum_generated_sql privileges
            cursor.execute("SET LOCAL ROLE aurum_generated_sql")

            lock_gold_sources(cursor, physical_used_sources)
            live = resolve_gold_execution_catalog(
                cursor,
                selected_sources=physical_used_sources,
                target=state.target,
                candidate=state.candidate,
            )
            used_refs = {(s["schema"], s["table"]) for s in physical_used_sources}
            expected_used_identities = tuple(
                ident for ident in (state.source_identities or ())
                if (ident["schema"], ident["relation_name"]) in used_refs
            )
            _assert_live_approval_identity(state, live, expected_source_identities=expected_used_identities)
            if live.candidate_identity is not None:
                raise GoldExecutionRejected(GOLD_CANDIDATE_CONFLICT)

            # Validate catalog source-type capability for all non-dropped columns on physical used Silver sources
            from src.sql_safety import validate_catalog_source_types
            used_sources_tuple = tuple((s["schema"], s["table"]) for s in physical_used_sources)
            validate_catalog_source_types(cursor, used_sources_tuple)

            cursor.execute(sql_text)

            # Revert role to session_user (aurum_promotion) for single-transaction ownership handoff
            cursor.execute("RESET ROLE")
            cursor.execute(
                sql.SQL("ALTER TABLE {}.{} OWNER TO {}").format(
                    sql.Identifier(state.candidate["schema"]),
                    sql.Identifier(state.candidate["table"]),
                    sql.Identifier(POSTGRES_PROMOTION_ROLE),
                )
            )
            cursor.execute(
                sql.SQL("GRANT SELECT ON {}.{} TO aurum_generated_sql").format(
                    sql.Identifier(state.candidate["schema"]),
                    sql.Identifier(state.candidate["table"]),
                )
            )

            created_snapshot = resolve_gold_execution_catalog(
                cursor,
                selected_sources=physical_used_sources,
                target=state.target,
                candidate=state.candidate,
            )
            _assert_live_approval_identity(state, created_snapshot, expected_source_identities=expected_used_identities)
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
        _, physical_used_sources = validate_approved_gold_execution_plan(state, sql_text)
    except Exception as exc:
        raise GoldExecutionRejected(GOLD_SQL_REJECTED) from exc

    from src.db_config import get_promotion_pool
    if pool is None:
        pool = get_promotion_pool()

    try:
        connection_context = pool.connection()
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
            physical_used_sources,
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
