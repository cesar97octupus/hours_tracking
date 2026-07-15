import calendar
import sqlite3
from datetime import date

from app import repository as repo
from app.dto import EmployeeRef, FieldCapability
from app.exceptions import LocalValidationError
from app.odoo_client import OdooClient


def _get_capability(conn: sqlite3.Connection) -> FieldCapability:
    data = repo.get_app_state(conn, "type_analytic_capability")
    return FieldCapability(**data) if data else FieldCapability(present=False)


def _get_employee(conn: sqlite3.Connection) -> EmployeeRef:
    data = repo.get_app_state(conn, "employee")
    if not data:
        raise LocalValidationError("No employee cached locally — run the setup wizard again")
    return EmployeeRef(**data)


def _selection_label(capability: FieldCapability, key: str | None) -> str | None:
    if not key or not capability.selection:
        return key
    for option_key, label in capability.selection:
        if option_key == key:
            return label
    return key


def month_bounds(year: int, month: int) -> tuple[str, str]:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1).isoformat(), date(year, month, last_day).isoformat()


def import_month_from_odoo(conn: sqlite3.Connection, client: OdooClient, year: int, month: int) -> int:
    """Pulls every account.analytic.line for the employee in the given month
    that isn't already known locally (matched by odoo_line_id) and stores it
    as a 'synced' entry. Lets the monthly view reflect hours logged directly
    in Odoo (web UI, other tools), not just ones exported from this app.
    Returns how many new lines were imported."""
    employee = _get_employee(conn)
    capability = _get_capability(conn)
    helpdesk_installed = bool((repo.get_app_state(conn, "helpdesk_installed") or {}).get("value"))

    date_from, date_to = month_bounds(year, month)
    rows = client.fetch_month_timesheet_lines(
        employee.employee_id, date_from, date_to,
        type_field=capability.field_name if capability.present else None,
        include_ticket_field=helpdesk_installed,
    )

    known_ids = repo.get_known_odoo_line_ids(conn)
    imported = 0
    for row in rows:
        if row["id"] in known_ids:
            continue

        task = row.get("task_id")
        ticket = row.get("helpdesk_ticket_id")

        type_kind = type_value = type_id = type_label = None
        if capability.present:
            raw = row.get(capability.field_name)
            if capability.ttype == "selection":
                type_kind, type_value = "selection", raw or None
                type_label = _selection_label(capability, raw)
            elif raw:
                type_kind, type_id, type_label = "many2one", raw[0], raw[1]

        repo.create_synced_entry_from_odoo(
            conn,
            odoo_line_id=row["id"],
            description=row.get("name") or "",
            task_id=task[0] if task else None, task_name=task[1] if task else None,
            ticket_id=ticket[0] if ticket else None, ticket_name=ticket[1] if ticket else None,
            type_analytic_kind=type_kind, type_analytic_value=type_value,
            type_analytic_id=type_id, type_analytic_label=type_label,
            unit_amount=row["unit_amount"], entry_date=row["date"],
        )
        imported += 1

    return imported
