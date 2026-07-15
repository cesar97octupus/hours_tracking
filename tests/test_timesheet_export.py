import sqlite3
import unittest
from unittest import mock

from app import repository as repo
from app import timesheet_export as export
from app.db import _migrate
from app.dto import EmployeeRef, FieldCapability
from app.exceptions import DuplicateFoundError, LocalValidationError


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _migrate(conn)
    return conn


class TestBuildPayload(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        self.employee = EmployeeRef(employee_id=42, name="Jane", work_email="jane@x.com", user_id=7)

    def _entry(self, **overrides):
        entry_id = repo.create_draft_entry(
            self.conn,
            description="worked on stuff",
            task_id=overrides.pop("task_id", 10),
            task_name="Task 10",
            ticket_id=overrides.pop("ticket_id", None),
            ticket_name=None,
            type_analytic_kind=overrides.pop("type_analytic_kind", None),
            type_analytic_value=overrides.pop("type_analytic_value", None),
            type_analytic_id=overrides.pop("type_analytic_id", None),
            type_analytic_label=None,
            start_ts="2026-07-15T10:00:00",
            end_ts="2026-07-15T10:30:00",
            elapsed_seconds=1800,
            unit_amount=0.5,
            entry_date="2026-07-15",
        )
        return repo.get_entry(self.conn, entry_id)

    def test_payload_task_no_capability(self):
        entry = self._entry()
        payload = export.build_payload(entry, FieldCapability(present=False), self.employee)
        self.assertEqual(payload["task_id"], 10)
        self.assertNotIn("helpdesk_ticket_id", payload)
        self.assertEqual(payload["employee_id"], 42)
        self.assertEqual(payload["unit_amount"], 0.5)
        self.assertEqual(payload["date"], "2026-07-15")

    def test_payload_ticket(self):
        entry = self._entry(task_id=None, ticket_id=99)
        payload = export.build_payload(entry, FieldCapability(present=False), self.employee)
        self.assertEqual(payload["helpdesk_ticket_id"], 99)
        self.assertNotIn("task_id", payload)

    def test_neither_task_nor_ticket_rejected(self):
        entry = self._entry(task_id=None, ticket_id=None)
        with self.assertRaises(LocalValidationError):
            export.build_payload(entry, FieldCapability(present=False), self.employee)

    def test_selection_capability_included(self):
        entry = self._entry(type_analytic_kind="selection", type_analytic_value="normal")
        capability = FieldCapability(present=True, field_name="type_analytic_line_id", ttype="selection", required=False)
        payload = export.build_payload(entry, capability, self.employee)
        self.assertEqual(payload["type_analytic_line_id"], "normal")

    def test_required_capability_missing_rejected(self):
        entry = self._entry()
        capability = FieldCapability(present=True, field_name="type_analytic_line_id", ttype="selection", required=True)
        with self.assertRaises(LocalValidationError):
            export.build_payload(entry, capability, self.employee)


class FakeClient:
    def __init__(self, duplicate_id=None, create_id=555):
        self.duplicate_id = duplicate_id
        self.create_id = create_id
        self.created_payloads = []

    def find_possible_duplicate(self, payload):
        return self.duplicate_id

    def create_timesheet_line(self, payload):
        self.created_payloads.append(payload)
        return self.create_id


class TestExportEntry(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        repo.set_app_state(self.conn, "employee", {"employee_id": 42, "name": "Jane", "work_email": "jane@x.com", "user_id": 7})
        self.entry_id = repo.create_draft_entry(
            self.conn,
            description="d", task_id=10, task_name="T10", ticket_id=None, ticket_name=None,
            type_analytic_kind=None, type_analytic_value=None, type_analytic_id=None, type_analytic_label=None,
            start_ts="2026-07-15T10:00:00", end_ts="2026-07-15T10:30:00",
            elapsed_seconds=1800, unit_amount=0.5, entry_date="2026-07-15",
        )

    def test_export_happy_path(self):
        client = FakeClient(duplicate_id=None, create_id=555)
        export.export_entry(self.entry_id, self.conn, client)
        entry = repo.get_entry(self.conn, self.entry_id)
        self.assertEqual(entry.state, "synced")
        self.assertEqual(entry.odoo_line_id, 555)

    def test_export_idempotent_noop_once_synced(self):
        client = FakeClient(duplicate_id=None, create_id=555)
        export.export_entry(self.entry_id, self.conn, client)
        export.export_entry(self.entry_id, self.conn, client)  # second call must not re-create
        self.assertEqual(len(client.created_payloads), 1)

    def test_duplicate_blocks_until_confirmed(self):
        client = FakeClient(duplicate_id=888, create_id=555)
        with self.assertRaises(DuplicateFoundError) as ctx:
            export.export_entry(self.entry_id, self.conn, client)
        self.assertEqual(ctx.exception.existing_odoo_id, 888)
        entry = repo.get_entry(self.conn, self.entry_id)
        self.assertEqual(entry.state, "draft")

        export.export_entry(self.entry_id, self.conn, client, confirm_duplicate=True)
        entry = repo.get_entry(self.conn, self.entry_id)
        self.assertEqual(entry.state, "synced")


if __name__ == "__main__":
    unittest.main()
