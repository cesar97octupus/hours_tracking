import sqlite3
import threading
from pathlib import Path

import platformdirs

SCHEMA_VERSION = 3

# The connection is created once on the main thread but export/sync work runs
# on QThreadPool worker threads (see app.ui.workers.run_async), so it must
# allow cross-thread use; this lock serializes actual statement execution
# (repository.py acquires it) since sqlite3 connections aren't safe for
# concurrent use from multiple threads without one.
DB_LOCK = threading.RLock()

_SCHEMA = """
CREATE TABLE time_entries (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    description          TEXT NOT NULL DEFAULT '',
    task_id              INTEGER,
    task_name            TEXT,
    ticket_id            INTEGER,
    ticket_name          TEXT,
    type_analytic_kind   TEXT,
    type_analytic_value  TEXT,
    type_analytic_id     INTEGER,
    type_analytic_label  TEXT,
    start_ts             TEXT NOT NULL,
    end_ts                TEXT,
    elapsed_seconds        INTEGER NOT NULL DEFAULT 0,
    unit_amount              REAL NOT NULL DEFAULT 0.0,
    entry_date                TEXT NOT NULL,
    state                      TEXT NOT NULL DEFAULT 'draft'
                                CHECK (state IN ('draft','pending_sync','synced','error')),
    odoo_line_id                INTEGER,
    last_error                    TEXT,
    created_at                     TEXT NOT NULL,
    updated_at                      TEXT NOT NULL,
    CHECK (NOT (task_id IS NOT NULL AND ticket_id IS NOT NULL))
);

CREATE TABLE cached_tasks (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    project_name TEXT,
    fetched_at TEXT NOT NULL
);

CREATE TABLE cached_tickets (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    project_name TEXT,
    fetched_at TEXT NOT NULL
);

CREATE TABLE type_analytic_options (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE active_timer (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    description TEXT NOT NULL DEFAULT '',
    task_id INTEGER,
    task_name TEXT,
    ticket_id INTEGER,
    ticket_name TEXT,
    start_ts TEXT NOT NULL
);
"""

def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, coltype: str) -> None:
    """ALTER TABLE ... ADD COLUMN is not idempotent in SQLite (no IF NOT
    EXISTS), and PRAGMA user_version can end up behind the actual schema if a
    prior migration's column-add committed but the version bump didn't (e.g.
    a process killed mid-migration) — checking first keeps re-running a
    migration step safe either way."""
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def get_app_dir() -> Path:
    path = Path(platformdirs.user_config_dir("hours_tracking", appauthor=False))
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_db_path() -> Path:
    return get_app_dir() / "hours_tracking.db"


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path or get_db_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current < 1:
        conn.executescript(_SCHEMA)
        current = 1
    if current < 2:
        for table in ("cached_tasks", "cached_tickets"):
            _add_column_if_missing(conn, table, "stage_id", "INTEGER")
            _add_column_if_missing(conn, table, "stage_name", "TEXT")
            _add_column_if_missing(conn, table, "write_date", "TEXT")
        current = 2
    if current < 3:
        for table in ("cached_tasks", "cached_tickets"):
            _add_column_if_missing(conn, table, "create_date", "TEXT")
        current = 3
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
