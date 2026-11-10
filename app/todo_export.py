"""Renders the TODO list as Markdown so Claude (and the user) can read the
day's pending work from a plain file. Regenerated on every change."""
import os
import sys
from pathlib import Path

from app import todo_repository as trepo
from app.db import get_app_dir
from app.dto import Todo

_PRIO_ORDER = {"high": 0, "medium": 1, "low": 2}


def get_export_dir() -> Path:
    override = os.environ.get("HOURS_TRACKING_TODOS_DIR")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        return get_app_dir() / "todos"
    return Path(__file__).resolve().parent.parent / "todos"


def _line(t: Todo, today: str) -> str:
    box = {"done": "x", "dropped": "-"}.get(t.status, " ")
    meta = [t.category_name or "Sin categoría", trepo.PRIORITY_LABELS[t.priority].lower()]
    if t.status == "in_progress":
        meta.append("en curso")
    head = f"- [{box}] [{' | '.join(meta)}] {t.title}"
    extra = []
    if t.subtasks:
        extra.append(f"{t.subtasks_done}/{len(t.subtasks)} subtareas")
    if t.due_date:
        extra.append(f"vence {t.due_date}" + (" (VENCIDO)" if t.is_open and t.due_date < today else ""))
    if t.task_name:
        extra.append(f"tarea Odoo: {t.task_name}")
    if t.ticket_name:
        extra.append(f"ticket Odoo: {t.ticket_name}")
    if t.is_open and t.planned_date and t.planned_date < today:
        extra.append(f"arrastrado desde {t.planned_date}")
    if extra:
        head += " — " + ", ".join(extra)
    lines = [head]
    if t.description.strip():
        lines += [f"    > {d}" for d in t.description.strip().splitlines()]
    for s in t.subtasks:
        lines.append(f"    - [{'x' if s.done else ' '}] {s.title}")
    return "\n".join(lines)


def render_markdown(todos: list[Todo], today: str) -> str:
    def key(t: Todo):
        return (_PRIO_ORDER[t.priority], t.id)

    open_ = [t for t in todos if t.is_open]
    today_open = sorted((t for t in open_ if (t.planned_date or today) == today), key=key)
    carried = sorted((t for t in open_ if (t.planned_date or today) < today), key=key)
    upcoming = sorted((t for t in open_ if (t.planned_date or today) > today), key=key)
    done_today = [t for t in todos if t.status == "done" and trepo.local_date_of(t.completed_at) == today]
    dropped_today = [t for t in todos if t.status == "dropped" and trepo.local_date_of(t.updated_at) == today]

    out = [f"# TODOs — {today}", ""]
    for title, items in (
        ("Pendientes de hoy", today_open),
        ("Arrastrados de días anteriores", carried),
        ("Hechos hoy", done_today),
        ("Descartados hoy", dropped_today),
        ("Próximos", upcoming),
    ):
        out.append(f"## {title} ({len(items)})")
        out.append("")
        out += [_line(t, today) for t in items] if items else ["_Ninguno_"]
        out.append("")
    return "\n".join(out)


def write_export(todos: list[Todo], today: str, export_dir: Path | None = None) -> Path:
    """Writes todos/current.md plus a per-day snapshot todos/YYYY-MM-DD.md."""
    d = export_dir or get_export_dir()
    d.mkdir(parents=True, exist_ok=True)
    text = render_markdown(todos, today)
    (d / f"{today}.md").write_text(text, encoding="utf-8")
    current = d / "current.md"
    current.write_text(text, encoding="utf-8")
    return current
