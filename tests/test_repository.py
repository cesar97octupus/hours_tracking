import sqlite3
import unittest

from app import repository as repo
from app.db import _migrate
from app.dto import TaskRef


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _migrate(conn)
    return conn


class TestRepository(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()

    def tearDown(self):
        self.conn.close()

    def _draft_kwargs(self, **overrides):
        kwargs = dict(
            description="desc",
            task_id=1,
            task_name="Task 1",
            ticket_id=None,
            ticket_name=None,
            type_analytic_kind=None,
            type_analytic_value=None,
            type_analytic_id=None,
            type_analytic_label=None,
            start_ts="2026-07-15T10:00:00",
            end_ts="2026-07-15T10:30:00",
            elapsed_seconds=1800,
            unit_amount=0.5,
            entry_date="2026-07-15",
        )
        kwargs.update(overrides)
        return kwargs

    def test_create_get_list_entry(self):
        entry_id = repo.create_draft_entry(self.conn, **self._draft_kwargs())
        entry = repo.get_entry(self.conn, entry_id)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.state, "draft")
        self.assertEqual(len(repo.list_entries(self.conn)), 1)

    def test_mark_synced_and_error(self):
        entry_id = repo.create_draft_entry(self.conn, **self._draft_kwargs())
        repo.mark_error(self.conn, entry_id, "boom")
        entry = repo.get_entry(self.conn, entry_id)
        self.assertEqual(entry.state, "error")
        self.assertEqual(entry.last_error, "boom")

        repo.mark_synced(self.conn, entry_id, 999)
        entry = repo.get_entry(self.conn, entry_id)
        self.assertEqual(entry.state, "synced")
        self.assertEqual(entry.odoo_line_id, 999)
        self.assertIsNone(entry.last_error)

    def test_delete_only_draft(self):
        entry_id = repo.create_draft_entry(self.conn, **self._draft_kwargs())
        repo.mark_synced(self.conn, entry_id, 1)
        repo.delete_entry(self.conn, entry_id)
        self.assertIsNotNone(repo.get_entry(self.conn, entry_id))  # not deleted, wasn't draft

        entry_id2 = repo.create_draft_entry(self.conn, **self._draft_kwargs())
        repo.delete_entry(self.conn, entry_id2)
        self.assertIsNone(repo.get_entry(self.conn, entry_id2))

    def test_task_and_ticket_mutually_exclusive(self):
        with self.assertRaises(sqlite3.IntegrityError):
            repo.create_draft_entry(self.conn, **self._draft_kwargs(ticket_id=2, ticket_name="Ticket 2"))

    def test_app_state_roundtrip(self):
        repo.set_app_state(self.conn, "employee", {"employee_id": 1, "name": "Test"})
        self.assertEqual(repo.get_app_state(self.conn, "employee"), {"employee_id": 1, "name": "Test"})
        repo.set_app_state(self.conn, "employee", {"employee_id": 2, "name": "Other"})
        self.assertEqual(repo.get_app_state(self.conn, "employee"), {"employee_id": 2, "name": "Other"})

    def test_cached_tasks_ordered_by_write_date_desc(self):
        tasks = [
            TaskRef(id=1, name="Old", write_date="2026-01-01 00:00:00", stage_id=1, stage_name="To do"),
            TaskRef(id=2, name="New", write_date="2026-07-01 00:00:00", stage_id=2, stage_name="Done"),
            TaskRef(id=3, name="No date"),
        ]
        repo.replace_cached_tasks(self.conn, tasks)
        result = repo.list_cached_tasks(self.conn)
        self.assertEqual([t.id for t in result], [2, 1, 3])  # most recent first, undated last
        self.assertEqual(result[0].stage_name, "Done")

    def test_create_synced_entry_from_odoo_and_known_ids(self):
        self.assertEqual(repo.get_known_odoo_line_ids(self.conn), set())
        entry_id = repo.create_synced_entry_from_odoo(
            self.conn, odoo_line_id=777, description="from odoo",
            task_id=5, task_name="Task 5", ticket_id=None, ticket_name=None,
            type_analytic_kind=None, type_analytic_value=None, type_analytic_id=None, type_analytic_label=None,
            unit_amount=1.5, entry_date="2026-07-10",
        )
        entry = repo.get_entry(self.conn, entry_id)
        self.assertEqual(entry.state, "synced")
        self.assertEqual(entry.odoo_line_id, 777)
        self.assertEqual(repo.get_known_odoo_line_ids(self.conn), {777})

    def test_active_timer_roundtrip(self):
        self.assertIsNone(repo.get_active_timer(self.conn))
        repo.set_active_timer(
            self.conn, description="d", task_id=1, task_name="T", ticket_id=None,
            ticket_name=None, start_ts="2026-07-15T10:00:00",
        )
        active = repo.get_active_timer(self.conn)
        self.assertEqual(active["task_id"], 1)
        repo.clear_active_timer(self.conn)
        self.assertIsNone(repo.get_active_timer(self.conn))


if __name__ == "__main__":
    unittest.main()
