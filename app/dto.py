from dataclasses import dataclass


@dataclass
class TaskRef:
    id: int
    name: str
    project_name: str | None = None
    stage_id: int | None = None
    stage_name: str | None = None
    write_date: str | None = None
    create_date: str | None = None


@dataclass
class TicketRef:
    id: int
    name: str
    project_name: str | None = None
    stage_id: int | None = None
    stage_name: str | None = None
    write_date: str | None = None
    create_date: str | None = None


@dataclass
class EmployeeRef:
    employee_id: int
    name: str
    work_email: str | None
    user_id: int


@dataclass
class OptionRef:
    id: int
    name: str


@dataclass
class FieldCapability:
    present: bool
    field_name: str | None = None
    ttype: str | None = None  # 'selection' | 'many2one'
    comodel: str | None = None
    required: bool = False
    selection: list[tuple[str, str]] | None = None
    probed_at: str | None = None


@dataclass
class TimeEntry:
    id: int
    description: str
    task_id: int | None
    task_name: str | None
    ticket_id: int | None
    ticket_name: str | None
    type_analytic_kind: str | None
    type_analytic_value: str | None
    type_analytic_id: int | None
    type_analytic_label: str | None
    start_ts: str
    end_ts: str | None
    elapsed_seconds: int
    unit_amount: float
    entry_date: str
    state: str
    odoo_line_id: int | None
    last_error: str | None
    created_at: str
    updated_at: str
