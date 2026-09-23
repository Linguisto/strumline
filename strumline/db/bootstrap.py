"""Bootstrap script: create the least-privilege ingest database role.

Run once after migrations:

    uv run python -m strumline.db.bootstrap

Or via Compose:

    docker compose run --rm strumline-cli python -m strumline.db.bootstrap

Creates ``strumline_ingest`` with SELECT-only access to the ``auth_tokens`` and
``apps`` tables (sufficient for auth token resolution). Sets a random password and
prints the vars to add to ``.env``.
"""

from __future__ import annotations

import secrets
import sys

import psycopg2

from strumline.config import DatabaseSettings

INGEST_ROLE = "strumline_ingest"


def bootstrap() -> None:
    settings = DatabaseSettings()
    password = secrets.token_urlsafe(32)

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
            cur.execute(f"CREATE ROLE {INGEST_ROLE} WITH LOGIN PASSWORD %s", (password,))
            print(f"Created role: {INGEST_ROLE}")
        else:
            cur.execute(f"ALTER ROLE {INGEST_ROLE} WITH PASSWORD %s", (password,))
            print(f"Updated password for role: {INGEST_ROLE}")

        db = settings.db_name

        cur.execute(f"GRANT CONNECT ON DATABASE {db} TO {INGEST_ROLE}")
        cur.execute(f"GRANT USAGE ON SCHEMA public TO {INGEST_ROLE}")
        cur.execute(f"GRANT SELECT ON auth_tokens TO {INGEST_ROLE}")
        cur.execute(f"GRANT SELECT ON apps TO {INGEST_ROLE}")

        cur.execute(
            """
            SELECT has_table_privilege(%s, 'auth_tokens', 'INSERT'),
                   has_table_privilege(%s, 'auth_tokens', 'UPDATE'),
                   has_table_privilege(%s, 'auth_tokens', 'DELETE')
            """,
            (INGEST_ROLE, INGEST_ROLE, INGEST_ROLE),
        )
        row = cur.fetchone()
        if row and any(row):
            print("WARNING: ingest role has unexpected write privileges", file=sys.stderr)
            sys.exit(1)

    conn.close()

    print("\nAdd to .env:")
    print(f"INGEST_DB_USER={INGEST_ROLE}")
    print(f"INGEST_DB_PASSWORD={password}")
    print("\nBootstrap complete.")


if __name__ == "__main__":
    bootstrap()
