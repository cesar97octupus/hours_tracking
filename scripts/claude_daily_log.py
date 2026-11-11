"""Claude Code Stop hook: appends a one-line activity log entry for every
turn run under D:\\Octupus\\odoo to a daily plain-text file. Read-only,
per-turn "what did Claude just do" trail for the user to review and turn
into a manual hours_tracking entry at the end of the day. Never writes to
the hours_tracking app/database and never blocks the session -- any
failure here must not affect the Claude Code turn.

Each line is tagged with a short session id (from the hook's session_id)
so that parallel sessions running under the same project path can be told
apart when reviewing a day's log.

Registered as a global Stop hook in ~/.claude/settings.json.
"""
import json
import os
import re
import sys
from datetime import datetime

ODOO_ROOT = r"D:\Octupus\odoo"
LOG_DIR = r"D:\Octupus\hours_tracking\daily_logs"
MAX_TEXT_CHARS = 300
TAIL_BYTES = 500_000  # read only the last ~500KB of a long transcript first


def under_odoo_root(cwd: str) -> bool:
    if not cwd:
        return False
    cwd = os.path.normpath(cwd)
    root = os.path.normpath(ODOO_ROOT)
    if len(cwd) < len(root) or cwd[: len(root)].lower() != root.lower():
        return False
    return len(cwd) == len(root) or cwd[len(root)] == os.sep


def last_assistant_text(transcript_path: str) -> str | None:
    if not transcript_path or not os.path.isfile(transcript_path):
        return None

    def scan(lines: list[str]) -> str | None:
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("type") != "assistant" or obj.get("isSidechain"):
                continue
            for block in reversed(obj.get("message", {}).get("content", [])):
                if block.get("type") == "text" and block.get("text", "").strip():
                    return block["text"]
        return None

    size = os.path.getsize(transcript_path)
    with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
        if size > TAIL_BYTES:
            f.seek(size - TAIL_BYTES)
            f.readline()  # drop partial first line
            text = scan(f.readlines())
            if text is not None:
                return text
            f.seek(0)
        return scan(f.readlines())


def brief(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS].rstrip() + "..."
    return text


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0

    cwd = data.get("cwd", "")
    if not under_odoo_root(cwd):
        return 0

    text = last_assistant_text(data.get("transcript_path", ""))
    if not text:
        return 0

    rel = os.path.relpath(os.path.normpath(cwd), os.path.normpath(ODOO_ROOT))
    now = datetime.now()
    session_tag = (data.get("session_id") or "unknown")[:8]

    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = os.path.join(LOG_DIR, now.strftime("%Y-%m-%d") + ".txt")
    line = f"[{now.strftime('%H:%M')}][{session_tag}] {rel} | {brief(text)}\n"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(line)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
