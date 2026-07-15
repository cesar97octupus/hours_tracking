import sqlite3

from app import repository as repo
from app.dto import EmployeeRef, FieldCapability, TimeEntry
from app.exceptions import (
    DuplicateFoundError,
    LocalValidationError,
    OdooAuthError,
    OdooConnectionError,
    OdooFault,
)
from app.odoo_client import OdooClient


def _get_capability(conn: sqlite3.Connection) -> FieldCapability:
    data = repo.get_app_state(conn, "type_analytic_capability")
    return FieldCapability(**data) if data else FieldCapability(present=False)


def _get_employee(conn: sqlite3.Connection) -> EmployeeRef:
    data = repo.get_app_state(conn, "employee")
    if not data:
        raise LocalValidationError("No employee cached locally — run the setup wizard again")
    return EmployeeRef(**data)


def build_payload(entry: TimeEntry, capability: FieldCapability, employee: EmployeeRef) -> dict:
    if bool(entry.task_id) == bool(entry.ticket_id):
        raise LocalValidationError("Entry must reference exactly one of task or ticket")

    payload = {
        "name": entry.description or "/",
        "unit_amount": entry.unit_amount,
        "employee_id": employee.employee_id,
        "date": entry.entry_date,
    }
    if entry.task_id:
        payload["task_id"] = entry.task_id
    else:
        payload["helpdesk_ticket_id"] = entry.ticket_id

    if capability.present:
        value = entry.type_analytic_value if capability.ttype == "selection" else entry.type_analytic_id
        if value:
            payload[capability.field_name] = value
        elif capability.required:
            raise LocalValidationError(f"{capability.field_name} is required but not set on this entry")

    return payload


def export_entry(
    entry_id: int,
    conn: sqlite3.Connection,
    client: OdooClient,
    *,
    confirm_duplicate: bool = False,
) -> None:
    """Attempt to export a local draft/error entry to Odoo.

    Idempotent: a no-op once entry.odoo_line_id is set. Raises
    DuplicateFoundError (without mutating state beyond leaving it as
    'draft') if a likely duplicate exists in Odoo and confirm_duplicate is
    False — callers should catch it, ask the user, and retry with
    confirm_duplicate=True to proceed anyway.
    """
    entry = repo.get_entry(conn, entry_id)
    if entry is None:
        raise LocalValidationError(f"No local entry with id={entry_id}")
    if entry.state == "synced" or entry.odoo_line_id is not None:
        return  # idempotency guard: never re-create once we hold an Odoo id

    capability = _get_capability(conn)
    employee = _get_employee(conn)
    payload = build_payload(entry, capability, employee)

    repo.set_entry_state(conn, entry_id, "pending_sync")
    try:
        if not confirm_duplicate:
            dup_id = client.find_possible_duplicate(payload)
            if dup_id is not None:
                repo.set_entry_state(conn, entry_id, "draft")
                raise DuplicateFoundError(dup_id)

        odoo_id = client.create_timesheet_line(payload)
        repo.mark_synced(conn, entry_id, odoo_id)
    except (OdooConnectionError, OdooFault, OdooAuthError) as exc:
        repo.mark_error(conn, entry_id, str(exc))
