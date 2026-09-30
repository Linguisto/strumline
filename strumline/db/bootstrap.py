"""Bootstrap script: create the least-privilege ingest database role.

Run once after migrations:

    uv run python -m strumline.db.bootstrap

Or via Compose:

    docker compose run --rm strumline-cli python -m strumline.db.bootstrap

Creates ``strumline_ingest`` with SELECT-only access to the tables required for
auth token resolution. The password must already be present in the environment.
"""

from __future__ import annotations

import argparse
import sys

import psycopg2
from psycopg2 import sql

from strumline.config import DatabaseSettings

INGEST_ROLE = "strumline_ingest"
READABLE_TABLES = ("auth_tokens", "apps", "projects")


def bootstrap(*, rotate: bool = False) -> None:
    settings = DatabaseSettings()
    password = settings.ingest_db_password
    if not password:
        print("INGEST_DB_PASSWORD must be set before bootstrapping", file=sys.stderr)
        raise SystemExit(2)

    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    conn.autocommit = True

    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (INGEST_ROLE,))
        if cur.fetchone() is None:
            cur.execute(
                sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD %s").format(
                    sql.Identifier(INGEST_ROLE)
                ),
                (password,),
            )
            print(f"Created role: {INGEST_ROLE}")
        elif rotate:
            cur.execute(
                sql.SQL("ALTER ROLE {} WITH PASSWORD %s").format(sql.Identifier(INGEST_ROLE)),
                (password,),
            )
            print(f"Updated password for role: {INGEST_ROLE}")
        else:
            print(f"Role already exists: {INGEST_ROLE} (password unchanged)")

        role = sql.Identifier(INGEST_ROLE)
        cur.execute(
            sql.SQL(
                "ALTER ROLE {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
            ).format(role)
        )
        cur.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(settings.db_name), role
            )
        )
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
        cur.execute(sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(role))
        for table in READABLE_TABLES:
            cur.execute(sql.SQL("GRANT SELECT ON {} TO {}").format(sql.Identifier(table), role))

        cur.execute(
            """
            SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls
            FROM pg_roles
            WHERE rolname = %s
            """,
            (INGEST_ROLE,),
        )
        attributes = cur.fetchone()
        if attributes is None or any(attributes):
            print(f"ERROR: {INGEST_ROLE} has elevated attributes", file=sys.stderr)
            raise SystemExit(1)

        cur.execute(
            "SELECT has_schema_privilege(%s, 'public', 'CREATE')",
            (INGEST_ROLE,),
        )
        if cur.fetchone() != (False,):
            print(
                f"ERROR: {INGEST_ROLE} can create objects in schema public",
                file=sys.stderr,
            )
            raise SystemExit(1)

        for table in READABLE_TABLES:
            cur.execute(
                """
                SELECT has_table_privilege(%s, %s, 'SELECT'),
                       has_table_privilege(%s, %s, 'INSERT'),
                       has_table_privilege(%s, %s, 'UPDATE'),
                       has_table_privilege(%s, %s, 'DELETE'),
                       has_table_privilege(%s, %s, 'TRUNCATE'),
                       has_table_privilege(%s, %s, 'REFERENCES'),
                       has_table_privilege(%s, %s, 'TRIGGER')
                """,
                (INGEST_ROLE, table) * 7,
            )
            row = cur.fetchone()
            if row is None or not row[0] or any(row[1:]):
                print(
                    f"ERROR: unexpected privileges for {INGEST_ROLE} on {table}",
                    file=sys.stderr,
                )
                raise SystemExit(1)

    conn.close()

    print("Bootstrap complete: ingest has SELECT-only access to required tables.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="replace the existing role password with INGEST_DB_PASSWORD",
    )
    bootstrap(rotate=parser.parse_args().rotate)
