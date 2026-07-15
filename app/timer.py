import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from app import repository as repo
from app.rounding import round_up_to_quarter_hour

MAX_TIMER_SECONDS = 7 * 3600  # auto-stop safety cutoff


@dataclass
class TimeEntryDraft:
    elapsed_seconds: float
    unit_amount: float
    start_wall: datetime
    end_wall: datetime


class Timer:
    """Pure stopwatch domain object — no DB/network coupling, so it's
    trivially unit-testable. Elapsed time is measured with time.monotonic()
    so it's immune to wall-clock/DST adjustments."""

    def __init__(
        self,
        *,
        description: str,
        task_id: int | None = None,
        task_name: str | None = None,
        ticket_id: int | None = None,
        ticket_name: str | None = None,
    ):
        self.description = description
        self.task_id = task_id
        self.task_name = task_name
        self.ticket_id = ticket_id
        self.ticket_name = ticket_name
        self._start_monotonic: float | None = None
        self.start_wall: datetime | None = None

    def start(self) -> None:
        self._start_monotonic = time.monotonic()
        self.start_wall = datetime.now(timezone.utc)

    def is_running(self) -> bool:
        return self._start_monotonic is not None

    def resume_from(self, start_wall: datetime) -> None:
        """Reattach to a timer that was started in a previous process (crash
        recovery). time.monotonic() resets on every process start, so elapsed
        time must be rebased off the persisted wall-clock start instead."""
        elapsed_since_start = (datetime.now(timezone.utc) - start_wall).total_seconds()
        self._start_monotonic = time.monotonic() - elapsed_since_start
        self.start_wall = start_wall

    def elapsed_seconds(self) -> float:
        if self._start_monotonic is None:
            return 0.0
        return time.monotonic() - self._start_monotonic

    def exceeded_max_duration(self) -> bool:
        return self.elapsed_seconds() >= MAX_TIMER_SECONDS

    def stop(self) -> TimeEntryDraft:
        elapsed = self.elapsed_seconds()
        end_wall = datetime.now(timezone.utc)
        draft = TimeEntryDraft(
            elapsed_seconds=elapsed,
            unit_amount=round_up_to_quarter_hour(elapsed),
            start_wall=self.start_wall,
            end_wall=end_wall,
        )
        self._start_monotonic = None
        return draft


# ---- persistence glue (crash-recovery marker + draft entry creation) --------

def start_and_persist(conn: sqlite3.Connection, timer: Timer) -> None:
    timer.start()
    repo.set_active_timer(
        conn,
        description=timer.description,
        task_id=timer.task_id,
        task_name=timer.task_name,
        ticket_id=timer.ticket_id,
        ticket_name=timer.ticket_name,
        start_ts=timer.start_wall.isoformat(),
    )


def stop_and_persist(conn: sqlite3.Connection, timer: Timer) -> int:
    draft = timer.stop()
    repo.clear_active_timer(conn)
    return repo.create_draft_entry(
        conn,
        description=timer.description,
        task_id=timer.task_id,
        task_name=timer.task_name,
        ticket_id=timer.ticket_id,
        ticket_name=timer.ticket_name,
        type_analytic_kind=None,
        type_analytic_value=None,
        type_analytic_id=None,
        type_analytic_label=None,
        start_ts=draft.start_wall.isoformat(),
        end_ts=draft.end_wall.isoformat(),
        elapsed_seconds=int(draft.elapsed_seconds),
        unit_amount=draft.unit_amount,
        entry_date=draft.start_wall.date().isoformat(),
    )
