"""Atomic table promotion helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass

import psycopg
from psycopg import sql


class PromotionError(Exception):
    """Raised when atomic table promotion fails."""
    pass


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_identifier(value: str, label: str) -> None:
    if not _IDENTIFIER_RE.match(value):
        raise PromotionError(f"Unsafe {label}: {value}")


def candidate_table_name(target_table: str, run_id: str) -> str:
    """Return <target>_candidate_<run_id> after validating both identifiers."""
    _validate_identifier(target_table, "target table")
    _validate_identifier(run_id, "run id")
    return f"{target_table}_candidate_{run_id}"


@dataclass(frozen=True)
class PromotionPlan:
    candidate_table: str
    candidate_schema: str
    target_table: str
    target_schema: str


def promote_candidate_table(
    candidate_table: str,
    candidate_schema: str,
    target_table: str,
    target_schema: str,
    promotion_conninfo: str,
    promoted_owner: str | None = None,
) -> None:
    """
    Atomically promote a candidate table to the target schema.
    Uses the promotion connection string to guarantee correct privileges.
    The active table is renamed only after the candidate has been validated and
    moved into the target schema, so a failed candidate cannot remove it.
    """
    plan = PromotionPlan(candidate_table, candidate_schema, target_table, target_schema)
    for value, label in (
        (plan.candidate_table, "candidate table"),
        (plan.candidate_schema, "candidate schema"),
        (plan.target_table, "target table"),
        (plan.target_schema, "target schema"),
    ):
        _validate_identifier(value, label)
    if promoted_owner is not None:
        _validate_identifier(promoted_owner, "promoted owner")

    old_table = f"{target_table}__superseded"
    try:
        with psycopg.connect(promotion_conninfo, autocommit=False) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT to_regclass({})").format(
                        sql.Literal(f"{candidate_schema}.{candidate_table}")
                    )
                )
                if cur.fetchone()[0] is None:
                    raise PromotionError("Candidate table does not exist.")

                cur.execute(
                    sql.SQL("SELECT to_regclass({})").format(
                        sql.Literal(f"{target_schema}.{target_table}")
                    )
                )
                target_exists = cur.fetchone()[0] is not None

                cur.execute(
                    sql.SQL("DROP TABLE IF EXISTS {}.{}").format(
                        sql.Identifier(target_schema), sql.Identifier(old_table)
                    )
                )
                cur.execute(
                    sql.SQL("ALTER TABLE {}.{} SET SCHEMA {}").format(
                        sql.Identifier(candidate_schema),
                        sql.Identifier(candidate_table),
                        sql.Identifier(target_schema),
                    )
                )
                if target_exists:
                    cur.execute(
                        sql.SQL("ALTER TABLE {}.{} RENAME TO {}").format(
                            sql.Identifier(target_schema),
                            sql.Identifier(target_table),
                            sql.Identifier(old_table),
                        )
                    )
                cur.execute(
                    sql.SQL("ALTER TABLE {}.{} RENAME TO {}").format(
                        sql.Identifier(target_schema),
                        sql.Identifier(candidate_table),
                        sql.Identifier(target_table),
                    )
                )
                if promoted_owner is not None:
                    cur.execute(
                        sql.SQL("ALTER TABLE {}.{} OWNER TO {}").format(
                            sql.Identifier(target_schema),
                            sql.Identifier(target_table),
                            sql.Identifier(promoted_owner),
                        )
                    )
                cur.execute(
                    sql.SQL("DROP TABLE IF EXISTS {}.{}").format(
                        sql.Identifier(target_schema), sql.Identifier(old_table)
                    )
                )
    except psycopg.Error as e:
        raise PromotionError(f"Database error during promotion: {e}")
    except PromotionError:
        raise


def discard_candidate_table(candidate_table: str, candidate_schema: str, promotion_conninfo: str) -> None:
    """Drop the candidate table entirely upon validation failure."""
    _validate_identifier(candidate_table, "candidate table")
    _validate_identifier(candidate_schema, "candidate schema")
    try:
        with psycopg.connect(promotion_conninfo, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("DROP TABLE IF EXISTS {}.{}").format(
                        sql.Identifier(candidate_schema), sql.Identifier(candidate_table)
                    )
                )
    except psycopg.Error as e:
        raise PromotionError(f"Failed to discard candidate table: {e}")
