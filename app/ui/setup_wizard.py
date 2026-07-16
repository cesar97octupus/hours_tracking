import sqlite3
from dataclasses import asdict

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app import autostart, config, repository as repo
from app.dto import EmployeeRef, FieldCapability
from app.exceptions import (
    EmployeeNotFoundError,
    MultipleEmployeesFoundError,
    OdooAuthError,
    OdooConnectionError,
    OdooFault,
)
from app.odoo_client import OdooClient
from app.ui import theme
from app.ui.workers import run_async


def _friendly_error(exc: Exception) -> str:
    if isinstance(exc, OdooAuthError):
        return "Usuario o contraseña incorrectos."
    if isinstance(exc, OdooConnectionError):
        return f"No se pudo conectar al servidor: {exc}"
    if isinstance(exc, EmployeeNotFoundError):
        return "No se encontró un empleado (hr.employee.public) para este usuario."
    if isinstance(exc, MultipleEmployeesFoundError):
        return "Se encontró más de un empleado para este usuario; contacta al administrador de Odoo."
    if isinstance(exc, OdooFault):
        return f"Error del servidor Odoo: {exc}"
    return f"Error inesperado: {exc}"


def _probe_everything(url: str, db: str, username: str, password: str) -> dict:
    """Runs off the Qt main thread. Pure network I/O, no DB/Qt access here."""
    client = OdooClient(url, db, username, password)
    client.authenticate()
    ctx = client.get_user_context()
    employee = client.resolve_employee(ctx.get("email"))
    helpdesk_installed = client.probe_helpdesk_installed()
    attendance_installed = client.probe_attendance_installed()
    capability = client.probe_type_analytic_line_field()
    options = []
    if capability.present and capability.ttype == "many2one" and capability.comodel:
        options = client.fetch_type_analytic_line_options(capability.comodel)
    return {
        "employee": employee,
        "helpdesk_installed": helpdesk_installed,
        "attendance_installed": attendance_installed,
        "capability": capability,
        "options": options,
    }


class SetupWizard(QDialog):
    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("Configuración de hours_tracking")
        self.setMinimumWidth(420)
        self._probe_result: dict | None = None
        self._password: str | None = None

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://mi-servidor-odoo.com")
        self.db_edit = QLineEdit()
        self.username_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)

        existing = config.load_config()
        if existing:
            self.url_edit.setText(existing.odoo_url)
            self.db_edit.setText(existing.odoo_db)
            self.username_edit.setText(existing.odoo_username)

        form = QFormLayout()
        form.addRow("URL de Odoo:", self.url_edit)
        form.addRow("Base de datos:", self.db_edit)
        form.addRow("Usuario:", self.username_edit)
        form.addRow("Contraseña:", self.password_edit)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)

        self.test_button = QPushButton("Probar conexión")
        self.test_button.clicked.connect(self._on_test_clicked)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.save_button = QPushButton("Guardar y continuar")
        self.save_button.setObjectName("primaryButton")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._on_save_clicked)
        self.buttons.addButton(self.save_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addWidget(self.test_button)
        layout.addWidget(self.status_label)
        layout.addWidget(self.buttons)

        self.adjustSize()
        theme.center_on_screen(self)

    def _on_test_clicked(self) -> None:
        url = self.url_edit.text().strip()
        db = self.db_edit.text().strip()
        username = self.username_edit.text().strip()
        password = self.password_edit.text()

        if not all([url, db, username, password]):
            self.status_label.setText("Completa todos los campos antes de probar la conexión.")
            return

        self._password = password
        self.test_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.status_label.setText("Probando conexión…")

        run_async(
            _probe_everything,
            url, db, username, password,
            on_success=self._on_probe_success,
            on_error=self._on_probe_error,
        )

    def _on_probe_success(self, result: dict) -> None:
        self.test_button.setEnabled(True)
        self._probe_result = result
        employee: EmployeeRef = result["employee"]
        capability: FieldCapability = result["capability"]
        lines = [
            f"Conexión exitosa. Empleado: {employee.name} ({employee.work_email or 's/correo'}).",
            f"Helpdesk instalado: {'sí' if result['helpdesk_installed'] else 'no'}.",
        ]
        if capability.present:
            lines.append(f"Campo type_analytic_line_id detectado: tipo={capability.ttype}, requerido={capability.required}.")
        else:
            lines.append("Campo type_analytic_line_id no existe en este servidor.")
        self.status_label.setText("\n".join(lines))
        self.save_button.setEnabled(True)

    def _on_probe_error(self, exc: Exception) -> None:
        self.test_button.setEnabled(True)
        self.save_button.setEnabled(False)
        self._probe_result = None
        self.status_label.setText(_friendly_error(exc))

    def _on_save_clicked(self) -> None:
        if not self._probe_result:
            return
        url = self.url_edit.text().strip()
        db = self.db_edit.text().strip()
        username = self.username_edit.text().strip()

        cfg = config.AppConfig(odoo_url=url, odoo_db=db, odoo_username=username)
        config.save_config(cfg)
        config.set_password(username, self._password)
        autostart.set_enabled(cfg.ui.autostart_enabled)

        employee: EmployeeRef = self._probe_result["employee"]
        capability: FieldCapability = self._probe_result["capability"]
        repo.set_app_state(self.conn, "employee", asdict(employee))
        repo.set_app_state(self.conn, "type_analytic_capability", asdict(capability))
        repo.set_app_state(self.conn, "helpdesk_installed", {"value": self._probe_result["helpdesk_installed"]})
        repo.set_app_state(self.conn, "attendance_installed", {"value": self._probe_result["attendance_installed"]})
        if self._probe_result["options"]:
            repo.replace_type_analytic_options(self.conn, self._probe_result["options"])

        QMessageBox.information(self, "Configuración guardada", "La configuración se guardó correctamente.")
        self.accept()
