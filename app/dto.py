from dataclasses import dataclass, field


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


@dataclass
class TodoCategory:
    id: int
    name: str
    color: str
    position: int = 0


@dataclass
class TodoSubtask:
    id: int | None
    title: str
    done: bool = False
    position: int = 0


@dataclass
class Todo:
    id: int
    title: str
    description: str
    category_id: int | None
    category_name: str | None
    category_color: str | None
    priority: str  # 'low' | 'medium' | 'high'
    status: str  # 'pending' | 'in_progress' | 'done' | 'dropped'
    planned_date: str | None
    due_date: str | None
    task_id: int | None
    task_name: str | None
    ticket_id: int | None
    ticket_name: str | None
    created_at: str
    updated_at: str
    completed_at: str | None
    recurrence: str = "none"  # 'none' | 'daily' | 'weekdays' | 'weekly' | 'monthly'
    subtasks: list[TodoSubtask] = field(default_factory=list)

    @property
    def subtasks_done(self) -> int:
        return sum(1 for s in self.subtasks if s.done)

    @property
    def is_open(self) -> bool:
        return self.status in ("pending", "in_progress")
