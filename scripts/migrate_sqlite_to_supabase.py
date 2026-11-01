import argparse
import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

import main

TABLES = (
    "users",
    "user_settings",
    "transactions",
    "budgets",
    "goals",
    "deleted_transactions",
    "budget_alerts",
    "weekly_reports",
    "rules",
)


def sqlite_table_columns(connection, table):
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return [row["name"] for row in rows]


def inspect_source():
    connection = sqlite3.connect(main.DB_PATH)
    connection.row_factory = sqlite3.Row
    counts = {}
    try:
        existing = {
            row["name"]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for table in TABLES:
            if table in existing:
                counts[table] = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        connection.close()
    return counts


def migrate():
    if not main.DATABASE_URL:
        raise SystemExit("Set DATABASE_URL in .env to the Supabase Session Pooler URI before applying the migration.")

    main.init_db()
    source = sqlite3.connect(main.DB_PATH)
    source.row_factory = sqlite3.Row
    copied = {}
    try:
        existing = {
            row["name"]
            for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        with main.db() as destination:
            for table in TABLES:
                if table not in existing:
                    continue
                columns = sqlite_table_columns(source, table)
                if not columns:
                    continue
                column_sql = ",".join(columns)
                placeholders = ",".join("?" for _ in columns)
                statement = (
                    f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders}) "
                    "ON CONFLICT DO NOTHING"
                )
                rows = source.execute(f"SELECT {column_sql} FROM {table}").fetchall()
                if rows:
                    destination.executemany(
                        statement,
                        [tuple(row[column] for column in columns) for row in rows],
                    )
                copied[table] = len(rows)

            for table in ("transactions", "goals"):
                destination.execute(
                    "SELECT setval(pg_get_serial_sequence(?, 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {table}), 1), "
                    f"EXISTS(SELECT 1 FROM {table}))",
                    (table,),
                )
    finally:
        source.close()

    for table, count in copied.items():
        print(f"{table}: {count} source rows processed (conflicts skipped)")
    main.close_postgres_pool()


def main_cli():
    parser = argparse.ArgumentParser(description="Copy local SQLite records to the Supabase PostgreSQL schema.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write rows to Supabase; without this option the script only reports local row counts",
    )
    args = parser.parse_args()

    counts = inspect_source()
    for table, count in counts.items():
        print(f"{table}: {count}")
    if not args.apply:
        print("Dry run only. Set DATABASE_URL and rerun with --apply to copy these rows.")
        return
    migrate()


if __name__ == "__main__":
    main_cli()
