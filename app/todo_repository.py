import sqlite3
from datetime import date, datetime

from app.dto import Todo, TodoCategory, TodoSubtask
from app.repository import _now_iso, _synchronized

STATUSES = ("pending", "in_progress", "done", "dropped")
PRIORITIES = ("low", "medium", "high")

STATUS_LABELS = {
    "pending": "Pendiente",
    "in_progress": "En curso",
    "done": "Hecho",
    "dropped": "Descartado",
}
PRIORITY_LABELS = {"low": "Baja", "medium": "Media", "high": "Alta"}

_TODO_SELECT = """
    SELECT t.*, c.name AS category_name, c.color AS category_color
    FROM todos t LEFT JOIN todo_categories c ON c.id = t.category_id
"""

_UPDATABLE = {
    "title", "description", "category_id", "priority", "status", "planned_date",
    "due_date", "task_id", "task_name", "ticket_id", "ticket_name",
}


def today_iso() -> str:
    return date.today().isoformat()


def local_date_of(iso_ts: str | None) -> str | None:
    """Local calendar date (YYYY-MM-DD) of a stored UTC ISO timestamp."""
    if not iso_ts:
        return None
    return datetime.fromisoformat(iso_ts).astimezone().date().isoformat()


# ---- categories -------------------------------------------------------

@_synchronized
def list_categories(conn: sqlite3.Connection) -> list[TodoCategory]:
    rows = conn.execute("SELECT * FROM todo_categories ORDER BY position, id").fetchall()
    return [TodoCategory(**{k: r[k] for k in r.keys()}) for r in rows]


@_synchronized
def create_category(conn: sqlite3.Connection, name: str, color: str = "#6b7280") -> int:
    name = name.strip()
    row = conn.execute("SELECT id FROM todo_categories WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    if row:
        return row["id"]
    pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM todo_categories").fetchone()[0]
    cur = conn.execute(
        "INSERT INTO todo_categories (name, color, position) VALUES (?, ?, ?)", (name, color, pos)
    )
    conn.commit()
    return cur.lastrowid


# ---- todos ------------------------------------------------------------

def _load(conn: sqlite3.Connection, rows) -> list[Todo]:
    todos = []
    for r in rows:
        subs = conn.execute(
            "SELECT id, title, done, position FROM todo_subtasks WHERE todo_id = ? ORDER BY position, id",
            (r["id"],),
        ).fetchall()
        todo = Todo(**{k: r[k] for k in r.keys()})
        todo.subtasks = [TodoSubtask(s["id"], s["title"], bool(s["done"]), s["position"]) for s in subs]
        todos.append(todo)
    return todos


def _replace_subtasks(conn: sqlite3.Connection, todo_id: int, subtasks: list[tuple[str, bool]]) -> None:
    conn.execute("DELETE FROM todo_subtasks WHERE todo_id = ?", (todo_id,))
    conn.executemany(
        "INSERT INTO todo_subtasks (todo_id, title, done, position) VALUES (?, ?, ?, ?)",
        [(todo_id, t.strip(), int(bool(d)), i) for i, (t, d) in enumerate(subtasks) if t.strip()],
    )


@_synchronized
def create_todo(
    conn: sqlite3.Connection,
    *,
    title: str,
    description: str = "",
    category_id: int | None = None,
    priority: str = "medium",
    status: str = "pending",
    planned_date: str | None = None,
    due_date: str | None = None,
    task_id: int | None = None,
    task_name: str | None = None,
    ticket_id: int | None = None,
    ticket_name: str | None = None,
    subtasks: list[tuple[str, bool]] | None = None,
) -> int:
    title = title.strip()
    if not title:
        raise ValueError("title is required")
    now = _now_iso()
    cur = conn.execute(
        """INSERT INTO todos
           (title, description, category_id, priority, status, planned_date, due_date,
            task_id, task_name, ticket_id, ticket_name, created_at, updated_at, completed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            title, description, category_id, priority, status,
            planned_date or today_iso(), due_date, task_id, task_name, ticket_id, ticket_name,
            now, now, now if status == "done" else None,
        ),
    )
    todo_id = cur.lastrowid
    _replace_subtasks(conn, todo_id, subtasks or [])
    conn.commit()
    return todo_id


@_synchronized
def get_todo(conn: sqlite3.Connection, todo_id: int) -> Todo | None:
    rows = conn.execute(_TODO_SELECT + " WHERE t.id = ?", (todo_id,)).fetchall()
    return _load(conn, rows)[0] if rows else None


@_synchronized
def list_todos(conn: sqlite3.Connection) -> list[Todo]:
    rows = conn.execute(_TODO_SELECT + " ORDER BY t.planned_date, t.id").fetchall()
    return _load(conn, rows)


@_synchronized
def update_todo(
    conn: sqlite3.Connection,
    todo_id: int,
    *,
    subtasks: list[tuple[str, bool]] | None = None,
    **fields,
) -> None:
    unknown = set(fields) - _UPDATABLE
    if unknown:
        raise ValueError(f"unknown todo fields: {sorted(unknown)}")
    if "status" in fields:
        current = conn.execute("SELECT status FROM todos WHERE id = ?", (todo_id,)).fetchone()
        if current is None:
            return
        if fields["status"] == "done":
            if current["status"] != "done":
                fields["completed_at"] = _now_iso()
        else:
            fields["completed_at"] = None
    fields["updated_at"] = _now_iso()
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE todos SET {cols} WHERE id = ?", (*fields.values(), todo_id))
    if subtasks is not None:
        _replace_subtasks(conn, todo_id, subtasks)
    conn.commit()


@_synchronized
def set_subtask_done(conn: sqlite3.Connection, subtask_id: int, done: bool) -> None:
    row = conn.execute("SELECT todo_id FROM todo_subtasks WHERE id = ?", (subtask_id,)).fetchone()
    if row is None:
        return
    conn.execute("UPDATE todo_subtasks SET done = ? WHERE id = ?", (int(done), subtask_id))
    conn.execute("UPDATE todos SET updated_at = ? WHERE id = ?", (_now_iso(), row["todo_id"]))
    conn.commit()


@_synchronized
def delete_subtask(conn: sqlite3.Connection, subtask_id: int) -> None:
    row = conn.execute("SELECT todo_id FROM todo_subtasks WHERE id = ?", (subtask_id,)).fetchone()
    if row is None:
        return
    conn.execute("DELETE FROM todo_subtasks WHERE id = ?", (subtask_id,))
    conn.execute("UPDATE todos SET updated_at = ? WHERE id = ?", (_now_iso(), row["todo_id"]))
    conn.commit()


@_synchronized
def delete_todo(conn: sqlite3.Connection, todo_id: int) -> None:
    conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
    conn.commit()
