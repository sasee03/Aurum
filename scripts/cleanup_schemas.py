import argparse
import sys
from pathlib import Path

import psycopg
from psycopg import sql

# Add the repo root so we can import src
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.app_state.db import get_connection
from src.db_config import postgres_conninfo



def cleanup_orphaned_schemas(dry_run: bool = False) -> None:
    """
    Finds and drops any Postgres schemas named 'aurum_session_%'
    that are NOT referenced by any row in the SQLite validation_runs table.
    """
    # 1. Get referenced schemas from SQLite
    print("Reading SQLite validation_runs...")
    referenced_schemas = set()
    try:
        with get_connection() as sqlite_conn:
            cursor = sqlite_conn.execute(
                "SELECT session_schema FROM validation_runs "
                "WHERE session_schema IS NOT NULL"
            )
            for row in cursor.fetchall():
                referenced_schemas.add(row[0])
        print(f"Found {len(referenced_schemas)} referenced session schemas in SQLite.")
    except Exception as e:
        print(f"Error reading SQLite: {e}", file=sys.stderr)
        sys.exit(1)

    # 2. Get existing schemas from Postgres
    print("Reading Postgres schemata...")
    try:
        with psycopg.connect(postgres_conninfo(), autocommit=True) as pg_conn:
            with pg_conn.cursor() as cur:
                cur.execute(
                    "SELECT schema_name FROM information_schema.schemata "
                    "WHERE schema_name LIKE 'aurum_session_%'"
                )
                pg_schemas = {row[0] for row in cur.fetchall()}

            print(f"Found {len(pg_schemas)} 'aurum_session_%' schemas in Postgres.")

            orphans = pg_schemas - referenced_schemas

            if not orphans:
                print("No orphaned schemas found. System is clean.")
                return

            print(f"Found {len(orphans)} orphaned schemas to drop.")

            if dry_run:
                print("DRY RUN mode enabled. Would drop the following schemas:")
                for schema in sorted(orphans):
                    print(f"  - {schema}")
                return

            for schema in sorted(orphans):
                print(f"Dropping schema {schema}...")
                pg_conn.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                        sql.Identifier(schema)
                    )
                )

            print(f"Successfully dropped {len(orphans)} orphaned schemas.")

    except Exception as e:
        print(f"Error querying Postgres: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Clean up orphaned aurum_session_% Postgres schemas"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print schemas that would be dropped without actually dropping them",
    )
    args = parser.parse_args()
    cleanup_orphaned_schemas(dry_run=args.dry_run)
