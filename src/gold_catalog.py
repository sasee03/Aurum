"""Read-only PostgreSQL catalog resolution for Gold approval snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from psycopg import sql

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
    candidate_namespace_identity: dict[str, Any]


@dataclass(frozen=True)
class GoldExecutionCatalogSnapshot:
    database_oid: int
    database_name: str
    source_identities: tuple[dict[str, Any], ...]
    target_identity: dict[str, Any]
    candidate_namespace_identity: dict[str, Any]
    candidate_identity: dict[str, Any] | None


@dataclass(frozen=True)
class GoldCatalogColumn:
    """Exact PostgreSQL catalog metadata for one authorized Gold source column."""

    name: str
    type_oid: int
    type_schema: str
    type_name: str
    type_kind: str
    supported_aggregations: frozenset[str]


@dataclass(frozen=True)
class StructuredGoldSourceCatalogSnapshot:
    """Exact relation identity and columns used to bind a structured proposal."""

    database_oid: int
    database_name: str
    source_identity: dict[str, Any]
    columns: tuple[GoldCatalogColumn, ...]


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


def _namespace_identity(
    *,
    database_oid: int,
    namespace_oid: int,
    schema: str,
) -> dict[str, Any]:
    return {
        "database_oid": database_oid,
        "namespace_oid": namespace_oid,
        "schema": schema,
    }


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


def _relation_columns(
    cursor: Any,
    *,
    relation_oid: int,
) -> tuple[GoldCatalogColumn, ...]:
    cursor.execute(
        """
        SELECT
            attribute.attname,
            column_type.oid,
            type_namespace.nspname,
            column_type.typname,
            column_type.typtype,
            ARRAY(
                SELECT aggregate.proname
                FROM pg_catalog.pg_proc AS aggregate
                JOIN pg_catalog.pg_namespace AS aggregate_namespace
                  ON aggregate_namespace.oid = aggregate.pronamespace
                WHERE aggregate.prokind = 'a'
                  AND aggregate_namespace.nspname = 'pg_catalog'
                  AND aggregate.proname IN ('sum', 'avg', 'min', 'max')
                  AND aggregate.pronargs = 1
                  AND aggregate.proargtypes[0] = attribute.atttypid
                ORDER BY aggregate.proname
            ) AS supported_aggregations
        FROM pg_catalog.pg_attribute AS attribute
        JOIN pg_catalog.pg_type AS column_type
          ON column_type.oid = attribute.atttypid
        JOIN pg_catalog.pg_namespace AS type_namespace
          ON type_namespace.oid = column_type.typnamespace
        WHERE attribute.attrelid = %s
          AND attribute.attnum > 0
          AND NOT attribute.attisdropped
        ORDER BY attribute.attnum
        """,
        (relation_oid,),
    )
    return tuple(
        GoldCatalogColumn(
            name=str(row[0]),
            type_oid=int(row[1]),
            type_schema=str(row[2]),
            type_name=str(row[3]),
            type_kind=str(row[4]),
            supported_aggregations=frozenset(str(value) for value in row[5]),
        )
        for row in cursor.fetchall()
    )


def resolve_structured_gold_source(
    *,
    schema: str,
    relation_name: str,
) -> StructuredGoldSourceCatalogSnapshot:
    """Resolve one exact Structured Gold source and its columns atomically."""
    with get_generated_sql_pool().connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                database_oid, database_name = _database_identity(cursor)
                namespace_oid = _namespace_oid(cursor, schema, area="source")
                source_identity = _relation_identity(
                    cursor,
                    database_oid=database_oid,
                    namespace_oid=namespace_oid,
                    schema=schema,
                    relation_name=relation_name,
                    area="source",
                )
                if source_identity is None:
                    raise GoldCatalogResolutionError(
                        "source",
                        "selected source relation is unresolved",
                    )
                columns = _relation_columns(
                    cursor,
                    relation_oid=source_identity["relation_oid"],
                )
    return StructuredGoldSourceCatalogSnapshot(
        database_oid=database_oid,
        database_name=database_name,
        source_identity=source_identity,
        columns=columns,
    )


def resolve_gold_approval_catalog(
    *,
    selected_sources: Sequence[Mapping[str, str]],
    target: Mapping[str, str],
    candidate: Mapping[str, str],
) -> GoldCatalogSnapshot:
    """Capture all approval identities in one read-only catalog transaction."""
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
                    | {target["schema"], candidate["schema"]}
                ):
                    area = "target" if schema == target["schema"] else "source"
                    if schema == candidate["schema"]:
                        area = "candidate_namespace"
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
                candidate_namespace_identity = _namespace_identity(
                    database_oid=database_oid,
                    namespace_oid=namespace_oids[candidate["schema"]],
                    schema=candidate["schema"],
                )

    return GoldCatalogSnapshot(
        database_oid=database_oid,
        database_name=database_name,
        source_identities=tuple(source_identities),
        target_identity=target_identity,
        candidate_namespace_identity=candidate_namespace_identity,
    )


def lock_gold_sources(
    cursor: Any,
    selected_sources: Sequence[Mapping[str, str]],
) -> None:
    """Acquire deterministic, identifier-safe ACCESS SHARE locks."""
    for source in sorted(
        selected_sources,
        key=lambda item: (item["schema"], item["table"]),
    ):
        cursor.execute(
            sql.SQL("LOCK TABLE {}.{} IN ACCESS SHARE MODE").format(
                sql.Identifier(source["schema"]),
                sql.Identifier(source["table"]),
            )
        )


def resolve_gold_execution_catalog(
    cursor: Any,
    *,
    selected_sources: Sequence[Mapping[str, str]],
    target: Mapping[str, str],
    candidate: Mapping[str, str],
) -> GoldExecutionCatalogSnapshot:
    """Resolve all execution identities after source locks are held."""
    database_oid, database_name = _database_identity(cursor)
    namespace_oids: dict[str, int] = {}
    source_schemas = {item["schema"] for item in selected_sources}
    for schema in sorted(source_schemas | {target["schema"], candidate["schema"]}):
        if schema == target["schema"]:
            area = "target"
        elif schema == candidate["schema"]:
            area = "candidate_namespace"
        else:
            area = "source"
        namespace_oids[schema] = _namespace_oid(cursor, schema, area=area)

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
        target_identity = {"state": "existing", **target_identity}

    candidate_identity = _relation_identity(
        cursor,
        database_oid=database_oid,
        namespace_oid=namespace_oids[candidate["schema"]],
        schema=candidate["schema"],
        relation_name=candidate["table"],
        area="candidate",
    )
    candidate_namespace_identity = _namespace_identity(
        database_oid=database_oid,
        namespace_oid=namespace_oids[candidate["schema"]],
        schema=candidate["schema"],
    )
    return GoldExecutionCatalogSnapshot(
        database_oid=database_oid,
        database_name=database_name,
        source_identities=tuple(source_identities),
        target_identity=target_identity,
        candidate_namespace_identity=candidate_namespace_identity,
        candidate_identity=candidate_identity,
    )
