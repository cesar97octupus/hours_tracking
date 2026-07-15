import socket
import xmlrpc.client
from contextlib import contextmanager

from app.dto import EmployeeRef, FieldCapability, OptionRef, TaskRef, TicketRef
from app.exceptions import (
    EmployeeNotFoundError,
    MultipleEmployeesFoundError,
    OdooAuthError,
    OdooConnectionError,
    OdooFault,
)

TYPE_ANALYTIC_FIELD = "type_analytic_line_id"


@contextmanager
def _translate_errors():
    try:
        yield
    except xmlrpc.client.Fault as exc:
        raise OdooFault(exc.faultString) from exc
    except (
        ConnectionRefusedError,
        TimeoutError,
        OSError,
        xmlrpc.client.ProtocolError,
        socket.gaierror,
    ) as exc:
        raise OdooConnectionError(str(exc)) from exc


class OdooClient:
    def __init__(self, url: str, db: str, username: str, password: str, timeout: int = 15):
        self.url = url.rstrip("/")
        self.db = db
        self.username = username
        self.password = password
        self.timeout = timeout
        self.uid: int | None = None
        self._common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self._models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")

    def _execute_kw(self, model: str, method: str, args: list, kwargs: dict | None = None):
        with _translate_errors():
            return self._models.execute_kw(
                self.db, self.uid, self.password, model, method, args, kwargs or {}
            )

    # ---- auth -------------------------------------------------------

    def authenticate(self) -> int:
        with _translate_errors():
            uid = self._common.authenticate(self.db, self.username, self.password, {})
        if not uid:
            raise OdooAuthError("Odoo rejected the supplied credentials")
        self.uid = uid
        return uid

    def get_user_context(self) -> dict:
        rows = self._execute_kw(
            "res.users", "read", [[self.uid]], {"fields": ["login", "email", "name"]}
        )
        return rows[0]

    # ---- employee resolution -----------------------------------------

    def resolve_employee(self, work_email: str | None) -> EmployeeRef:
        rows = []
        if work_email:
            rows = self._execute_kw(
                "hr.employee.public", "search_read",
                [[("work_email", "=", work_email)]],
                {"fields": ["employee_id", "name", "work_email", "user_id"]},
            )
        if not rows:
            rows = self._execute_kw(
                "hr.employee.public", "search_read",
                [[("user_id", "=", self.uid)]],
                {"fields": ["employee_id", "name", "work_email", "user_id"]},
            )
        if not rows:
            raise EmployeeNotFoundError(
                f"No hr.employee.public record found for work_email={work_email!r} or user_id={self.uid}"
            )
        if len(rows) > 1:
            raise MultipleEmployeesFoundError(
                f"Multiple hr.employee.public records found ({len(rows)}) for this user"
            )
        row = rows[0]
        employee_id = row["employee_id"][0] if row["employee_id"] else row["id"]
        return EmployeeRef(
            employee_id=employee_id,
            name=row["name"],
            work_email=row.get("work_email"),
            user_id=row["user_id"][0] if row["user_id"] else self.uid,
        )

    # ---- tasks / tickets ----------------------------------------------

    def fetch_my_tasks(self) -> list[TaskRef]:
        rows = self._execute_kw(
            "project.task", "search_read",
            [[("user_ids", "in", [self.uid]), ("project_id.allow_timesheets", "=", True)]],
            {"fields": ["name", "project_id", "stage_id", "write_date"], "order": "write_date desc"},
        )
        return [
            TaskRef(
                id=r["id"], name=r["name"],
                project_name=r["project_id"][1] if r["project_id"] else None,
                stage_id=r["stage_id"][0] if r["stage_id"] else None,
                stage_name=r["stage_id"][1] if r["stage_id"] else None,
                write_date=r.get("write_date"),
            )
            for r in rows
        ]

    def probe_helpdesk_installed(self) -> bool:
        count = self._execute_kw(
            "ir.module.module", "search_count",
            [[("name", "=", "helpdesk_timesheet"), ("state", "=", "installed")]],
        )
        return bool(count)

    def fetch_my_tickets(self) -> list[TicketRef]:
        rows = self._execute_kw(
            "helpdesk.ticket", "search_read",
            [[("user_id", "=", self.uid)]],
            {"fields": ["name", "project_id", "stage_id", "write_date"], "order": "write_date desc"},
        )
        return [
            TicketRef(
                id=r["id"], name=r["name"],
                project_name=r["project_id"][1] if r.get("project_id") else None,
                stage_id=r["stage_id"][0] if r.get("stage_id") else None,
                stage_name=r["stage_id"][1] if r.get("stage_id") else None,
                write_date=r.get("write_date"),
            )
            for r in rows
        ]

    # ---- type_analytic_line_id capability probe -------------------------

    def probe_type_analytic_line_field(self) -> FieldCapability:
        fields = self._execute_kw(
            "account.analytic.line", "fields_get",
            [],
            {"attributes": ["type", "relation", "selection", "string", "required"]},
        )
        info = fields.get(TYPE_ANALYTIC_FIELD)
        if not info:
            return FieldCapability(present=False)
        return FieldCapability(
            present=True,
            field_name=TYPE_ANALYTIC_FIELD,
            ttype=info["type"],
            comodel=info.get("relation"),
            required=bool(info.get("required")),
            selection=info.get("selection"),
        )

    def fetch_type_analytic_line_options(self, comodel: str, limit: int = 200) -> list[OptionRef]:
        rows = self._execute_kw(
            comodel, "search_read", [[]], {"fields": ["display_name"], "limit": limit}
        )
        return [OptionRef(id=r["id"], name=r["display_name"]) for r in rows]

    # ---- monthly reconciliation ------------------------------------------

    def fetch_month_timesheet_lines(
        self,
        employee_id: int,
        date_from: str,
        date_to: str,
        type_field: str | None = None,
        include_ticket_field: bool = False,
    ) -> list[dict]:
        """All account.analytic.line rows for this employee in [date_from, date_to]
        (inclusive), regardless of how they were created (this app, Odoo web UI,
        etc.) — used to reconcile what's actually recorded in Odoo for a month."""
        fields = ["name", "date", "unit_amount", "task_id"]
        if include_ticket_field:
            fields.append("helpdesk_ticket_id")
        if type_field:
            fields.append(type_field)
        domain = [
            ("employee_id", "=", employee_id),
            ("date", ">=", date_from),
            ("date", "<=", date_to),
        ]
        return self._execute_kw(
            "account.analytic.line", "search_read", [domain], {"fields": fields, "order": "date asc"}
        )

    # ---- create / duplicate check ----------------------------------------

    def create_timesheet_line(self, payload: dict) -> int:
        return self._execute_kw("account.analytic.line", "create", [payload])

    def find_possible_duplicate(self, payload: dict) -> int | None:
        domain = [
            ("employee_id", "=", payload["employee_id"]),
            ("date", "=", payload["date"]),
            ("unit_amount", "=", payload["unit_amount"]),
        ]
        if payload.get("task_id"):
            domain.append(("task_id", "=", payload["task_id"]))
        elif payload.get("helpdesk_ticket_id"):
            domain.append(("helpdesk_ticket_id", "=", payload["helpdesk_ticket_id"]))
        rows = self._execute_kw("account.analytic.line", "search_read", [domain], {"fields": ["id"], "limit": 1})
        return rows[0]["id"] if rows else None
