import sqlite3
import unittest

from app import repository as repo
from app import timesheet_sync as sync
from app.db import _migrate


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _migrate(conn)
    return conn


class FakeClient:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def fetch_month_timesheet_lines(self, employee_id, date_from, date_to, type_field=None, include_ticket_field=False):
        self.calls.append((employee_id, date_from, date_to, type_field, include_ticket_field))
        return self.rows


class TestImportMonthFromOdoo(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        repo.set_app_state(self.conn, "employee", {"employee_id": 42, "name": "Jane", "work_email": "jane@x.com", "user_id": 7})

    def test_date_range_and_employee_passed_to_client(self):
        client = FakeClient(rows=[])
        sync.import_month_from_odoo(self.conn, client, 2026, 7)
        self.assertEqual(client.calls[0][:3], (42, "2026-07-01", "2026-07-31"))

    def test_imports_new_lines_as_synced(self):
        rows = [
            {"id": 100, "name": "worked", "date": "2026-07-10", "unit_amount": 2.0,
             "task_id": (5, "Task 5"), "helpdesk_ticket_id": False},
        ]
        client = FakeClient(rows)
        imported = sync.import_month_from_odoo(self.conn, client, 2026, 7)
        self.assertEqual(imported, 1)

        entries = repo.list_entries(self.conn)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].state, "synced")
        self.assertEqual(entries[0].odoo_line_id, 100)
        self.assertEqual(entries[0].task_id, 5)
        self.assertEqual(entries[0].unit_amount, 2.0)

    def test_skips_lines_already_known_locally(self):
        repo.create_synced_entry_from_odoo(
            self.conn, odoo_line_id=100, description="worked",
            task_id=5, task_name="Task 5", ticket_id=None, ticket_name=None,
            type_analytic_kind=None, type_analytic_value=None, type_analytic_id=None, type_analytic_label=None,
            unit_amount=2.0, entry_date="2026-07-10",
        )
        rows = [{"id": 100, "name": "worked", "date": "2026-07-10", "unit_amount": 2.0, "task_id": (5, "Task 5")}]
        client = FakeClient(rows)
        imported = sync.import_month_from_odoo(self.conn, client, 2026, 7)
        self.assertEqual(imported, 0)
        self.assertEqual(len(repo.list_entries(self.conn)), 1)

    def test_selection_capability_resolves_label(self):
        repo.set_app_state(self.conn, "type_analytic_capability", {
            "present": True, "field_name": "type_analytic_line_id", "ttype": "selection",
            "comodel": None, "required": False, "selection": [["normal", "Normal"], ["extra", "Extra"]],
        })
        rows = [{
            "id": 200, "name": "worked", "date": "2026-07-11", "unit_amount": 1.0,
            "task_id": (5, "Task 5"), "type_analytic_line_id": "extra",
        }]
        client = FakeClient(rows)
        sync.import_month_from_odoo(self.conn, client, 2026, 7)
        entry = repo.list_entries(self.conn)[0]
        self.assertEqual(entry.type_analytic_kind, "selection")
        self.assertEqual(entry.type_analytic_value, "extra")
        self.assertEqual(entry.type_analytic_label, "Extra")

    def test_many2one_capability_resolves_label(self):
        repo.set_app_state(self.conn, "type_analytic_capability", {
            "present": True, "field_name": "type_analytic_line_id", "ttype": "many2one",
            "comodel": "some.model", "required": False, "selection": None,
        })
        rows = [{
            "id": 300, "name": "worked", "date": "2026-07-12", "unit_amount": 1.0,
            "task_id": (5, "Task 5"), "type_analytic_line_id": (9, "Development"),
        }]
        client = FakeClient(rows)
        sync.import_month_from_odoo(self.conn, client, 2026, 7)
        entry = repo.list_entries(self.conn)[0]
        self.assertEqual(entry.type_analytic_kind, "many2one")
        self.assertEqual(entry.type_analytic_id, 9)
        self.assertEqual(entry.type_analytic_label, "Development")


if __name__ == "__main__":
    unittest.main()
