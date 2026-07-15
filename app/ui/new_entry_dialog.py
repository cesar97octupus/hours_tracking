import sqlite3

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QRadioButton,
    QVBoxLayout,
)

from app import repository as repo
from app.dto import FieldCapability


def _capability(conn: sqlite3.Connection) -> FieldCapability:
    data = repo.get_app_state(conn, "type_analytic_capability")
    return FieldCapability(**data) if data else FieldCapability(present=False)


class NewEntryDialog(QDialog):
    """Create a draft time entry directly, without running the stopwatch.
    Uses the locally cached task/ticket list (already fetched by the main
    window) rather than hitting the network."""

    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("Añadir parte de horas")
        self.setMinimumWidth(420)

        helpdesk_installed = bool((repo.get_app_state(conn, "helpdesk_installed") or {}).get("value"))
        self._tasks = repo.list_cached_tasks(conn)
        self._tickets = repo.list_cached_tickets(conn)

        self.task_radio = QRadioButton("Tarea")
        self.task_radio.setChecked(True)
        self.ticket_radio = QRadioButton("Ticket")
        self.ticket_radio.setVisible(helpdesk_installed)
        self.task_radio.toggled.connect(lambda _checked: self._on_picker_mode_changed())

        self.picker_combo = QComboBox()

        self.stage_filter_combo = QComboBox()
        self.stage_filter_combo.currentIndexChanged.connect(lambda _i: self._reload_picker())

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Buscar por nombre…")
        self.search_edit.textChanged.connect(lambda _t: self._reload_picker())

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())

        self.description_edit = QLineEdit()
        self.description_edit.setPlaceholderText("Descripción del trabajo…")

        self.hours_spin = QDoubleSpinBox()
        self.hours_spin.setDecimals(2)
        self.hours_spin.setSingleStep(0.25)
        self.hours_spin.setRange(0.0, 24.0)
        self.hours_spin.setValue(1.0)

        self.capability = _capability(conn)
        self.capability_widget: QComboBox | None = None
        if self.capability.present:
            combo = QComboBox()
            combo.addItem("(sin especificar)", None)
            if self.capability.ttype == "selection":
                for key, label in self.capability.selection or []:
                    combo.addItem(label, key)
            else:
                for opt in repo.list_type_analytic_options(conn):
                    combo.addItem(opt.name, opt.id)
            self.capability_widget = combo

        picker_row = QHBoxLayout()
        picker_row.addWidget(self.task_radio)
        picker_row.addWidget(self.ticket_radio)
        picker_row.addWidget(self.picker_combo, 1)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Estado:"))
        filter_row.addWidget(self.stage_filter_combo)
        filter_row.addWidget(self.search_edit, 1)

        form = QFormLayout()
        form.addRow(picker_row)
        form.addRow(filter_row)
        form.addRow("Fecha:", self.date_edit)
        form.addRow("Descripción:", self.description_edit)
        form.addRow("Horas:", self.hours_spin)
        if self.capability_widget is not None:
            form.addRow(f"{self.capability.field_name}:", self.capability_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primaryButton")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self._refresh_stage_filter_options()
        self._reload_picker()

    def _current_items(self):
        return self._tasks if self.task_radio.isChecked() else self._tickets

    def _refresh_stage_filter_options(self) -> None:
        stages: dict[int, str] = {}
        for item in self._current_items():
            if item.stage_id is not None:
                stages[item.stage_id] = item.stage_name or str(item.stage_id)

        previous = self.stage_filter_combo.currentData()
        self.stage_filter_combo.blockSignals(True)
        self.stage_filter_combo.clear()
        self.stage_filter_combo.addItem("Todos los estados", None)
        for stage_id, stage_name in sorted(stages.items(), key=lambda kv: kv[1].lower()):
            self.stage_filter_combo.addItem(stage_name, stage_id)
        idx = self.stage_filter_combo.findData(previous)
        self.stage_filter_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.stage_filter_combo.blockSignals(False)

    def _on_picker_mode_changed(self) -> None:
        self._refresh_stage_filter_options()
        self._reload_picker()

    def _reload_picker(self) -> None:
        self.picker_combo.clear()
        stage_filter = self.stage_filter_combo.currentData()
        search_text = self.search_edit.text().strip().lower()
        for item in self._current_items():
            if stage_filter is not None and item.stage_id != stage_filter:
                continue
            if search_text and search_text not in item.name.lower():
                continue
            label = f"#{item.id} {item.name}"
            if item.project_name:
                label += f" ({item.project_name})"
            if item.stage_name:
                label += f" [{item.stage_name}]"
            self.picker_combo.addItem(label, item.id)

    def _collect_capability_value(self) -> tuple[str | None, str | None, int | None, str | None]:
        if self.capability_widget is None:
            return None, None, None, None
        value = self.capability_widget.currentData()
        label = self.capability_widget.currentText() if value is not None else None
        if self.capability.ttype == "selection":
            return "selection", value, None, label
        return "many2one", None, value, label

    def _on_save(self) -> None:
        item_id = self.picker_combo.currentData()
        if item_id is None:
            QMessageBox.warning(self, "Falta información", "Selecciona una tarea o ticket.")
            return
        if self.hours_spin.value() <= 0:
            QMessageBox.warning(self, "Falta información", "Las horas deben ser mayores que cero.")
            return

        is_task = self.task_radio.isChecked()
        label = self.picker_combo.currentText()
        entry_date = self.date_edit.date().toString("yyyy-MM-dd")
        kind, value, cap_id, cap_label = self._collect_capability_value()

        repo.create_draft_entry(
            self.conn,
            description=self.description_edit.text(),
            task_id=item_id if is_task else None, task_name=label if is_task else None,
            ticket_id=item_id if not is_task else None, ticket_name=label if not is_task else None,
            type_analytic_kind=kind, type_analytic_value=value,
            type_analytic_id=cap_id, type_analytic_label=cap_label,
            start_ts=f"{entry_date}T00:00:00+00:00", end_ts=None,
            elapsed_seconds=int(round(self.hours_spin.value() * 3600)),
            unit_amount=self.hours_spin.value(),
            entry_date=entry_date,
        )
        self.accept()
