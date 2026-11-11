"""Claude Code SessionStart hook: prints the user's TODO list (the Markdown
that the hours_tracking app regenerates on every change) to stdout, which
Claude Code injects into the session context. This is how Claude knows the
user's pendientes at the start of every session.

Read-only and fail-safe: any problem results in no output and exit code 0,
so it can never block or break a session.

Registered as a global SessionStart hook in ~/.claude/settings.json.
"""
import os
import sys
from datetime import date
from pathlib import Path

TODOS_FILE = Path(os.environ.get("HOURS_TRACKING_TODOS_DIR", r"D:\Octupus\hours_tracking\todos")) / "current.md"
MAX_CHARS = 8000


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        if not TODOS_FILE.is_file():
            return
        text = TODOS_FILE.read_text(encoding="utf-8").strip()
        if not text:
            return
        today = date.today().isoformat()
        stale = ""
        first_line = text.splitlines()[0]
        if today not in first_line:
            stale = (
                f"NOTA: este listado es de otro día ({first_line.lstrip('# ').strip()}), hoy es {today}; "
                "puede estar desactualizado (se refresca al abrir la app hours_tracking).\n\n"
            )
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS] + "\n… (recortado)"
        print(
            "Pendientes (TODO) del usuario, exportados por la app hours_tracking "
            f"({TODOS_FILE}). Úsalos como contexto de lo que tiene por hacer:\n\n{stale}{text}"
        )
    except Exception:
        return


if __name__ == "__main__":
    main()
