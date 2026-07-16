import json
import sqlite3
from datetime import datetime, timezone
from functools import wraps

from app.db import DB_LOCK
from app.dto import OptionRef, TaskRef, TicketRef, TimeEntry


def _synchronized(fn):
    """Serializes access to the shared sqlite3.Connection, which is created
    on the main thread but also used from QThreadPool worker threads (e.g.
    timesheet export). DB_LOCK is reentrant so nested calls (e.g.
    mark_synced -> update_entry) don't deadlock."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        with DB_LOCK:
            return fn(*args, **kwargs)
    return wrapper


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_entry(row: sqlite3.Row) -> TimeEntry:
    return TimeEntry(**{k: row[k] for k in row.keys()})


# ---- time_entries -----------------------------------------------------

@_synchronized
def create_draft_entry(
    conn: sqlite3.Connection,
    *,
    description: str,
    task_id: int | None,
    task_name: str | None,
    ticket_id: int | None,
    ticket_name: str | None,
    type_analytic_kind: str | None,
    type_analytic_value: str | None,
    type_analytic_id: int | None,
    type_analytic_label: str | None,
    start_ts: str,
    end_ts: str | None,
    elapsed_seconds: int,
    unit_amount: float,
    entry_date: str,
) -> int:
    now = _now_iso()
    cur = conn.execute(
        """INSERT INTO time_entries
           (description, task_id, task_name, ticket_id, ticket_name,
            type_analytic_kind, type_analytic_value, type_analytic_id, type_analytic_label,
            start_ts, end_ts, elapsed_seconds, unit_amount, entry_date,
            state, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)""",
        (
            description, task_id, task_name, ticket_id, ticket_name,
            type_analytic_kind, type_analytic_value, type_analytic_id, type_analytic_label,
            start_ts, end_ts, elapsed_seconds, unit_amount, entry_date,
            now, now,
        ),
    )
    conn.commit()
    return cur.lastrowid


@_synchronized
def get_entry(conn: sqlite3.Connection, entry_id: int) -> TimeEntry | None:
    row = conn.execute("SELECT * FROM time_entries WHERE id = ?", (entry_id,)).fetchone()
    return _row_to_entry(row) if row else None


@_synchronized
def list_entries(conn: sqlite3.Connection) -> list[TimeEntry]:
    rows = conn.execute("SELECT * FROM time_entries ORDER BY start_ts DESC").fetchall()
    return [_row_to_entry(r) for r in rows]


@_synchronized
def update_entry(conn: sqlite3.Connection, entry_id: int, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = _now_iso()
    columns = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE time_entries SET {columns} WHERE id = ?", (*fields.values(), entry_id))
    conn.commit()


@_synchronized
def delete_entry(conn: sqlite3.Connection, entry_id: int) -> None:
    conn.execute("DELETE FROM time_entries WHERE id = ? AND state = 'draft'", (entry_id,))
    conn.commit()


def set_entry_state(conn: sqlite3.Connection, entry_id: int, state: str) -> None:
    update_entry(conn, entry_id, state=state)


def mark_synced(conn: sqlite3.Connection, entry_id: int, odoo_line_id: int) -> None:
    update_entry(conn, entry_id, state="synced", odoo_line_id=odoo_line_id, last_error=None)


def mark_error(conn: sqlite3.Connection, entry_id: int, message: str) -> None:
    update_entry(conn, entry_id, state="error", last_error=message)


@_synchronized
def get_known_odoo_line_ids(conn: sqlite3.Connection) -> set[int]:
    rows = conn.execute("SELECT odoo_line_id FROM time_entries WHERE odoo_line_id IS NOT NULL").fetchall()
    return {r["odoo_line_id"] for r in rows}


@_synchronized
def create_synced_entry_from_odoo(
    conn: sqlite3.Connection,
    *,
    odoo_line_id: int,
    description: str,
    task_id: int | None,
    task_name: str | None,
    ticket_id: int | None,
    ticket_name: str | None,
    type_analytic_kind: str | None,
    type_analytic_value: str | None,
    type_analytic_id: int | None,
    type_analytic_label: str | None,
    unit_amount: float,
    entry_date: str,
) -> int:
    """Mirrors a line that already exists in Odoo (created there directly, or
    exported from this app in a previous session) into the local cache as
    'synced', so the monthly view reflects Odoo's actual state."""
    now = _now_iso()
    start_ts = f"{entry_date}T00:00:00+00:00"
    cur = conn.execute(
        """INSERT INTO time_entries
           (description, task_id, task_name, ticket_id, ticket_name,
            type_analytic_kind, type_analytic_value, type_analytic_id, type_analytic_label,
            start_ts, end_ts, elapsed_seconds, unit_amount, entry_date,
            state, odoo_line_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, 'synced', ?, ?, ?)""",
        (
            description, task_id, task_name, ticket_id, ticket_name,
            type_analytic_kind, type_analytic_value, type_analytic_id, type_analytic_label,
            start_ts, int(round(unit_amount * 3600)), unit_amount, entry_date,
            odoo_line_id, now, now,
        ),
    )
    conn.commit()
    return cur.lastrowid


# ---- caches -------------------------------------------------------------

_CACHED_ORDER_SQL = "ORDER BY write_date IS NULL, write_date DESC, id DESC"


@_synchronized
def replace_cached_tasks(conn: sqlite3.Connection, tasks: list[TaskRef]) -> None:
    now = _now_iso()
    conn.execute("DELETE FROM cached_tasks")
    conn.executemany(
        """INSERT INTO cached_tasks
           (id, name, project_name, stage_id, stage_name, write_date, create_date, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (t.id, t.name, t.project_name, t.stage_id, t.stage_name, t.write_date, t.create_date, now)
            for t in tasks
        ],
    )
    conn.commit()


@_synchronized
def list_cached_tasks(conn: sqlite3.Connection) -> list[TaskRef]:
    rows = conn.execute(
        "SELECT id, name, project_name, stage_id, stage_name, write_date, create_date "
        f"FROM cached_tasks {_CACHED_ORDER_SQL}"
    ).fetchall()
    return [
        TaskRef(
            id=r["id"], name=r["name"], project_name=r["project_name"],
            stage_id=r["stage_id"], stage_name=r["stage_name"], write_date=r["write_date"],
            create_date=r["create_date"],
        )
        for r in rows
    ]


@_synchronized
def replace_cached_tickets(conn: sqlite3.Connection, tickets: list[TicketRef]) -> None:
    now = _now_iso()
    conn.execute("DELETE FROM cached_tickets")
    conn.executemany(
        """INSERT INTO cached_tickets
           (id, name, project_name, stage_id, stage_name, write_date, create_date, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (t.id, t.name, t.project_name, t.stage_id, t.stage_name, t.write_date, t.create_date, now)
            for t in tickets
        ],
    )
    conn.commit()


@_synchronized
def list_cached_tickets(conn: sqlite3.Connection) -> list[TicketRef]:
    rows = conn.execute(
        "SELECT id, name, project_name, stage_id, stage_name, write_date, create_date "
        f"FROM cached_tickets {_CACHED_ORDER_SQL}"
    ).fetchall()
    return [
        TicketRef(
            id=r["id"], name=r["name"], project_name=r["project_name"],
            stage_id=r["stage_id"], stage_name=r["stage_name"], write_date=r["write_date"],
            create_date=r["create_date"],
        )
        for r in rows
    ]


@_synchronized
def replace_type_analytic_options(conn: sqlite3.Connection, options: list[OptionRef]) -> None:
    now = _now_iso()
    conn.execute("DELETE FROM type_analytic_options")
    conn.executemany(
        "INSERT INTO type_analytic_options (id, name, fetched_at) VALUES (?, ?, ?)",
        [(o.id, o.name, now) for o in options],
    )
    conn.commit()


@_synchronized
def list_type_analytic_options(conn: sqlite3.Connection) -> list[OptionRef]:
    rows = conn.execute("SELECT id, name FROM type_analytic_options ORDER BY name").fetchall()
    return [OptionRef(id=r["id"], name=r["name"]) for r in rows]


# ---- app_state ------------------------------------------------------------

@_synchronized
def get_app_state(conn: sqlite3.Connection, key: str) -> dict | None:
    row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else None


@_synchronized
def set_app_state(conn: sqlite3.Connection, key: str, value: dict) -> None:
    conn.execute(
        "INSERT INTO app_state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )
    conn.commit()


# ---- active_timer (crash-recovery marker) ----------------------------------

@_synchronized
def set_active_timer(
    conn: sqlite3.Connection,
    *,
    description: str,
    task_id: int | None,
    task_name: str | None,
    ticket_id: int | None,
    ticket_name: str | None,
    start_ts: str,
) -> None:
    conn.execute("DELETE FROM active_timer")
    conn.execute(
        """INSERT INTO active_timer (id, description, task_id, task_name, ticket_id, ticket_name, start_ts)
           VALUES (1, ?, ?, ?, ?, ?, ?)""",
        (description, task_id, task_name, ticket_id, ticket_name, start_ts),
    )
    conn.commit()


@_synchronized
def get_active_timer(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM active_timer WHERE id = 1").fetchone()
    return {k: row[k] for k in row.keys()} if row else None


@_synchronized
def clear_active_timer(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM active_timer")
    conn.commit()
