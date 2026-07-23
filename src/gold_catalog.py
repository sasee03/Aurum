"""Read-only PostgreSQL catalog resolution for Gold approval snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from src.db_config import get_generated_sql_pool


ALLOWED_GOLD_RELATION_KINDS = frozenset({"r", "p"})


class GoldCatalogResolutionError(RuntimeError):
    """A required configured relation identity could not be safely resolved."""

    def __init__(self, area: str, reason: str):
        super().__init__(reason)
        self.area = area


@dataclass(frozen=True)
class GoldCatalogSnapshot:
    database_oid: int
    database_name: str
    source_identities: tuple[dict[str, Any], ...]
    target_identity: dict[str, Any]


def _database_identity(cursor: Any) -> tuple[int, str]:
    cursor.execute(
        """
        SELECT oid, datname
        FROM pg_catalog.pg_database
        WHERE datname = pg_catalog.current_database()
        """
    )
    row = cursor.fetchone()
    if row is None:
        raise GoldCatalogResolutionError("database", "current database is unresolved")
    return int(row[0]), str(row[1])


def _namespace_oid(cursor: Any, schema: str, *, area: str) -> int:
    cursor.execute(
        """
        SELECT oid
        FROM pg_catalog.pg_namespace
        WHERE nspname = %s
        """,
        (schema,),
    )
    row = cursor.fetchone()
    if row is None:
        raise GoldCatalogResolutionError(area, "configured namespace is unresolved")
    return int(row[0])


def _relation_identity(
    cursor: Any,
    *,
    database_oid: int,
    namespace_oid: int,
    schema: str,
    relation_name: str,
    area: str,
) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT oid, relname, relkind
        FROM pg_catalog.pg_class
        WHERE relnamespace = %s
          AND relname = %s
        """,
        (namespace_oid, relation_name),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    relation_kind = str(row[2])
    if relation_kind not in ALLOWED_GOLD_RELATION_KINDS:
        raise GoldCatalogResolutionError(area, "relation kind is not approvable")
    return {
        "database_oid": database_oid,
        "namespace_oid": namespace_oid,
        "relation_oid": int(row[0]),
        "schema": schema,
        "relation_name": str(row[1]),
        "relation_kind": relation_kind,
    }


def resolve_gold_approval_catalog(
    *,
    selected_sources: Sequence[Mapping[str, str]],
    target: Mapping[str, str],
) -> GoldCatalogSnapshot:
    """Capture source and target identities in one read-only catalog transaction."""
    with get_generated_sql_pool().connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                database_oid, database_name = _database_identity(cursor)
                namespace_oids: dict[str, int] = {}
                for schema in sorted(
                    {item["schema"] for item in selected_sources}
                    | {target["schema"]}
                ):
                    area = "target" if schema == target["schema"] else "source"
                    namespace_oids[schema] = _namespace_oid(
                        cursor,
                        schema,
                        area=area,
                    )

                source_identities: list[dict[str, Any]] = []
                for source in selected_sources:
                    identity = _relation_identity(
                        cursor,
                        database_oid=database_oid,
                        namespace_oid=namespace_oids[source["schema"]],
                        schema=source["schema"],
                        relation_name=source["table"],
                        area="source",
                    )
                    if identity is None:
                        raise GoldCatalogResolutionError(
                            "source",
                            "selected source relation is unresolved",
                        )
                    source_identities.append(identity)

                target_identity = _relation_identity(
                    cursor,
                    database_oid=database_oid,
                    namespace_oid=namespace_oids[target["schema"]],
                    schema=target["schema"],
                    relation_name=target["table"],
                    area="target",
                )
                if target_identity is None:
                    target_identity = {
                        "state": "absent",
                        "database_oid": database_oid,
                        "namespace_oid": namespace_oids[target["schema"]],
                        "schema": target["schema"],
                        "relation_name": target["table"],
                    }
                else:
                    target_identity = {
                        "state": "existing",
                        **target_identity,
                    }

    return GoldCatalogSnapshot(
        database_oid=database_oid,
        database_name=database_name,
        source_identities=tuple(source_identities),
        target_identity=target_identity,
    )
