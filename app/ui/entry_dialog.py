import sqlite3

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app import repository as repo
from app import timesheet_export as export
from app.dto import FieldCapability
from app.exceptions import (
    DuplicateFoundError,
    LocalValidationError,
    OdooAuthError,
    OdooConnectionError,
    OdooFault,
)
from app.odoo_client import OdooClient
from app.ui.workers import run_async


def _capability(conn: sqlite3.Connection) -> FieldCapability:
    data = repo.get_app_state(conn, "type_analytic_capability")
    return FieldCapability(**data) if data else FieldCapability(present=False)


class EntryDialog(QDialog):
    """Edit one local time entry before export. Fields become read-only once
    the entry's state is 'synced' (post-sync edits are a future extension,
    not built in v1)."""

    def __init__(self, conn: sqlite3.Connection, entry_id: int, client: OdooClient, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.entry_id = entry_id
        self.client = client
        self.entry = repo.get_entry(conn, entry_id)
        self.capability = _capability(conn)

        self.setWindowTitle(f"Parte de horas #{entry_id}")
        self.setMinimumWidth(420)

        readonly = self.entry.state == "synced"

        self.description_edit = QLineEdit(self.entry.description)
        self.description_edit.setReadOnly(readonly)

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.fromString(self.entry.entry_date, "yyyy-MM-dd"))
        self.date_edit.setReadOnly(readonly)

        self.hours_spin = QDoubleSpinBox()
        self.hours_spin.setDecimals(2)
        self.hours_spin.setSingleStep(0.25)
        self.hours_spin.setRange(0.0, 24.0)
        self.hours_spin.setValue(self.entry.unit_amount)
        self.hours_spin.setReadOnly(readonly)

        target = self.entry.task_name or self.entry.ticket_name or "(ninguno)"
        kind = "Tarea" if self.entry.task_id else "Ticket"
        self.target_label = QLabel(f"{kind}: {target}")

        self.capability_widget: QComboBox | None = None
        self.capability_field_label = self.capability.field_name or "type_analytic_line_id"
        if self.capability.present:
            combo = QComboBox()
            combo.addItem("(sin especificar)", None)
            if self.capability.ttype == "selection":
                for key, label in self.capability.selection or []:
                    combo.addItem(label, key)
                current = self.entry.type_analytic_value
            else:
                for opt in repo.list_type_analytic_options(conn):
                    combo.addItem(opt.name, opt.id)
                current = self.entry.type_analytic_id
            if current is not None:
                idx = combo.findData(current)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            combo.setEnabled(not readonly)
            self.capability_widget = combo

        self.status_label = QLabel()
        self._refresh_status_label()

        form = QFormLayout()
        form.addRow("Descripción:", self.description_edit)
        form.addRow("Fecha:", self.date_edit)
        form.addRow("Horas:", self.hours_spin)
        form.addRow(self.target_label)
        if self.capability_widget is not None:
            form.addRow(f"{self.capability_field_label}:", self.capability_widget)

        self.save_button = QPushButton("Guardar")
        self.save_button.clicked.connect(lambda: self._on_save())
        self.export_button = QPushButton("Exportar a Odoo")
        self.export_button.setObjectName("primaryButton")
        self.export_button.clicked.connect(lambda: self._on_export())

        if readonly:
            self.save_button.setEnabled(False)
            self.export_button.setEnabled(False)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.addButton(self.save_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(self.export_button, QDialogButtonBox.ButtonRole.ActionRole)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addWidget(self.status_label)
        layout.addWidget(buttons)

    def _refresh_status_label(self) -> None:
        entry = repo.get_entry(self.conn, self.entry_id)
        text = f"Estado: {entry.state}"
        if entry.odoo_line_id:
            text += f" (Odoo #{entry.odoo_line_id})"
        if entry.last_error:
            text += f"\nÚltimo error: {entry.last_error}"
        self.status_label.setText(text)

    def _collect_capability_value(self) -> tuple[str | None, str | None, int | None, str | None]:
        if self.capability_widget is None:
            return None, None, None, None
        value = self.capability_widget.currentData()
        label = self.capability_widget.currentText() if value is not None else None
        if self.capability.ttype == "selection":
            return "selection", value, None, label
        return "many2one", None, value, label

    def _save_local(self) -> None:
        kind, value, cid, label = self._collect_capability_value()
        repo.update_entry(
            self.conn, self.entry_id,
            description=self.description_edit.text(),
            entry_date=self.date_edit.date().toString("yyyy-MM-dd"),
            unit_amount=self.hours_spin.value(),
            type_analytic_kind=kind,
            type_analytic_value=value,
            type_analytic_id=cid,
            type_analytic_label=label,
        )

    def _on_save(self) -> None:
        try:
            self._save_local()
        except Exception as exc:  # noqa: BLE001 - surfaced to the user directly
            QMessageBox.warning(self, "Error", str(exc))
            return
        self._refresh_status_label()

    def _on_export(self, confirm_duplicate: bool = False) -> None:
        try:
            self._save_local()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Error", str(exc))
            return

        self.export_button.setEnabled(False)
        run_async(
            export.export_entry,
            self.entry_id, self.conn, self.client,
            confirm_duplicate=confirm_duplicate,
            on_success=self._on_export_success,
            on_error=self._on_export_error,
        )

    def _on_export_success(self, _result) -> None:
        self.export_button.setEnabled(True)
        self._refresh_status_label()
        entry = repo.get_entry(self.conn, self.entry_id)
        if entry.state == "synced":
            QMessageBox.information(self, "Exportado", f"Parte de horas exportado como Odoo #{entry.odoo_line_id}.")
            self.save_button.setEnabled(False)
            self.export_button.setEnabled(False)
            self.description_edit.setReadOnly(True)
            self.date_edit.setReadOnly(True)
            self.hours_spin.setReadOnly(True)
            if self.capability_widget:
                self.capability_widget.setEnabled(False)

    def _on_export_error(self, exc: Exception) -> None:
        self.export_button.setEnabled(True)
        self._refresh_status_label()
        if isinstance(exc, DuplicateFoundError):
            answer = QMessageBox.question(
                self, "Posible duplicado",
                f"Ya existe un parte de horas similar en Odoo (#{exc.existing_odoo_id}). ¿Exportar de todas formas?",
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._on_export(confirm_duplicate=True)
            return
        if isinstance(exc, LocalValidationError):
            QMessageBox.warning(self, "Datos incompletos", str(exc))
            return
        if isinstance(exc, (OdooAuthError, OdooConnectionError, OdooFault)):
            QMessageBox.warning(self, "Error al exportar", str(exc))
            return
        QMessageBox.warning(self, "Error inesperado", str(exc))
