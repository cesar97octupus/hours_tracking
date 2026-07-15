import sqlite3
from datetime import date

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import repository as repo
from app import timesheet_export as export
from app import timesheet_sync as sync
from app.dto import TimeEntry
from app.exceptions import (
    DuplicateFoundError,
    LocalValidationError,
    OdooAuthError,
    OdooConnectionError,
    OdooFault,
)
from app.odoo_client import OdooClient
from app.ui import theme
from app.ui.entry_dialog import EntryDialog
from app.ui.new_entry_dialog import NewEntryDialog
from app.ui.workers import run_async

_STATE_LABELS = {
    "draft": "Borrador",
    "pending_sync": "Sincronizando…",
    "synced": "Sincronizado",
    "error": "Error",
}

COLUMNS = ["Descripción", "Tarea/Ticket", "Tipo de horas", "Horas", "Estado"]
_STATE_COLUMN = COLUMNS.index("Estado")

_WEEKDAYS_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
_MONTHS_ES = [
    "", "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def _format_day_header(date_str: str) -> str:
    d = date.fromisoformat(date_str)
    return f"{_WEEKDAYS_ES[d.weekday()]} {d.day} de {_MONTHS_ES[d.month]} de {d.year}"


def _state_dot_icon(color: QColor, size: int = 10) -> QIcon:
    """A small colored dot, used instead of colored text for the state column
    so it stays legible when the row is selected/highlighted regardless of
    theme (colored text can end up low-contrast against the selection
    background, an icon isn't affected by text/selection color rules)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(color)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(0, 0, size, size)
    painter.end()
    return QIcon(pixmap)


def _month_options(months_back: int = 12) -> list[tuple[int, int]]:
    """Most recent month first; today's month is always index 0."""
    today = date.today()
    options = []
    y, m = today.year, today.month
    for _ in range(months_back):
        options.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return options


class EntriesListWidget(QWidget):
    def __init__(self, conn: sqlite3.Connection, client: OdooClient, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.client = client
        self._state_icons = {
            state: _state_dot_icon(QColor(hex_)) for state, hex_ in theme.get_state_colors().items()
        }

        self.month_combo = QComboBox()
        for year, month in _month_options():
            self.month_combo.addItem(f"{_MONTHS_ES[month].capitalize()} {year}", (year, month))
        self.month_combo.currentIndexChanged.connect(lambda _i: self.refresh())

        self.add_button = QPushButton("+ Añadir registro")
        self.add_button.setObjectName("primaryButton")
        self.add_button.clicked.connect(self._on_add_clicked)
        self.sync_button = QPushButton("Actualizar desde Odoo")
        self.sync_button.clicked.connect(self._on_sync_clicked)

        self.month_total_label = QLabel("")
        self.month_total_label.setObjectName("totalLabel")

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        top_row.addWidget(QLabel("Mes:"))
        top_row.addWidget(self.month_combo)
        top_row.addWidget(self.add_button)
        top_row.addWidget(self.sync_button)
        top_row.addStretch(1)
        top_row.addWidget(self.month_total_label)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(COLUMNS))
        self.tree.setHeaderLabels(COLUMNS)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setIconSize(QSize(10, 10))
        self.tree.itemDoubleClicked.connect(lambda _item, _col: self._edit_selected())

        self.edit_button = QPushButton("Editar")
        self.edit_button.clicked.connect(lambda: self._edit_selected())
        self.export_button = QPushButton("Exportar")
        self.export_button.setObjectName("primaryButton")
        self.export_button.clicked.connect(lambda: self._export_selected())
        self.retry_all_button = QPushButton("Reintentar todos los errores")
        self.retry_all_button.clicked.connect(lambda: self._retry_all_errors())
        self.delete_button = QPushButton("Eliminar")
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.clicked.connect(lambda: self._delete_selected())
        self.refresh_button = QPushButton("Recargar vista")
        self.refresh_button.clicked.connect(lambda: self.refresh())

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(10)
        for b in (self.edit_button, self.export_button, self.retry_all_button, self.delete_button, self.refresh_button):
            buttons_row.addWidget(b)
        buttons_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addLayout(top_row)
        layout.addLayout(buttons_row)
        layout.addWidget(self.tree)

        self.refresh()

    # ---- data loading -----------------------------------------------------

    def _selected_year_month(self) -> tuple[int, int]:
        data = self.month_combo.currentData()
        if data is None:
            today = date.today()
            return today.year, today.month
        return data

    def refresh(self) -> None:
        year, month = self._selected_year_month()
        prefix = f"{year:04d}-{month:02d}"
        entries = [e for e in repo.list_entries(self.conn) if e.entry_date.startswith(prefix)]

        by_date: dict[str, list[TimeEntry]] = {}
        for entry in entries:
            by_date.setdefault(entry.entry_date, []).append(entry)
        for day_entries in by_date.values():
            day_entries.sort(key=lambda e: e.start_ts or "")

        self.tree.clear()
        month_total = 0.0
        for entry_date in sorted(by_date.keys(), reverse=True):
            day_entries = by_date[entry_date]
            day_total = sum(e.unit_amount for e in day_entries)
            month_total += day_total

            count_label = "registro" if len(day_entries) == 1 else "registros"
            header = QTreeWidgetItem([f"{_format_day_header(entry_date)}  —  {day_total:.2f} h  ({len(day_entries)} {count_label})"])
            header.setFirstColumnSpanned(True)
            header.setFlags(header.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            bold_font = header.font(0)
            bold_font.setBold(True)
            header.setFont(0, bold_font)
            self.tree.addTopLevelItem(header)

            for entry in day_entries:
                target = entry.task_name or entry.ticket_name or ""
                values = [
                    entry.description, target, entry.type_analytic_label or "",
                    f"{entry.unit_amount:.2f}", _STATE_LABELS.get(entry.state, entry.state),
                ]
                child = QTreeWidgetItem(values)
                child.setData(0, Qt.ItemDataRole.UserRole, entry.id)
                icon = self._state_icons.get(entry.state)
                if icon:
                    child.setIcon(_STATE_COLUMN, icon)
                if entry.last_error:
                    child.setToolTip(_STATE_COLUMN, entry.last_error)
                header.addChild(child)

            header.setExpanded(True)

        self.month_total_label.setText(f"Total del mes: {month_total:.2f} h")

    # ---- selection / actions -----------------------------------------------

    def _selected_entry_ids(self) -> list[int]:
        ids = []
        for item in self.tree.selectedItems():
            if item.parent() is None:  # top-level => a day header, not an entry
                continue
            entry_id = item.data(0, Qt.ItemDataRole.UserRole)
            if entry_id is not None:
                ids.append(entry_id)
        return ids

    def _edit_selected(self) -> None:
        ids = self._selected_entry_ids()
        if not ids:
            QMessageBox.information(self, "Nada seleccionado", "Selecciona un registro (no el encabezado del día) primero.")
            return
        if len(ids) > 1:
            QMessageBox.information(self, "Selección múltiple", "Selecciona un solo registro para editarlo.")
            return
        dialog = EntryDialog(self.conn, ids[0], self.client, parent=self)
        dialog.exec()
        self.refresh()

    def _on_add_clicked(self) -> None:
        dialog = NewEntryDialog(self.conn, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _export_selected(self) -> None:
        ids = self._selected_entry_ids()
        if not ids:
            QMessageBox.information(self, "Nada seleccionado", "Selecciona uno o más registros (no el encabezado del día) primero.")
            return
        for entry_id in ids:
            self._export_entry(entry_id)

    def _export_entry(self, entry_id: int, confirm_duplicate: bool = False) -> None:
        run_async(
            export.export_entry,
            entry_id, self.conn, self.client,
            confirm_duplicate=confirm_duplicate,
            on_success=lambda _r: self.refresh(),
            on_error=lambda exc, eid=entry_id: self._on_export_error(eid, exc),
        )

    def _on_export_error(self, entry_id: int, exc: Exception) -> None:
        self.refresh()
        if isinstance(exc, DuplicateFoundError):
            answer = QMessageBox.question(
                self, "Posible duplicado",
                f"Ya existe un parte de horas similar en Odoo (#{exc.existing_odoo_id}). ¿Exportar de todas formas?",
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._export_entry(entry_id, confirm_duplicate=True)
            return
        if isinstance(exc, (LocalValidationError, OdooAuthError, OdooConnectionError, OdooFault)):
            QMessageBox.warning(self, "Error al exportar", str(exc))
            return
        QMessageBox.warning(self, "Error inesperado", str(exc))

    def _retry_all_errors(self) -> None:
        for entry in repo.list_entries(self.conn):
            if entry.state == "error":
                self._export_entry(entry.id)

    def _delete_selected(self) -> None:
        ids = self._selected_entry_ids()
        if not ids:
            QMessageBox.information(self, "Nada seleccionado", "Selecciona uno o más registros (no el encabezado del día) primero.")
            return
        entries = [repo.get_entry(self.conn, entry_id) for entry_id in ids]
        if any(e.state != "draft" for e in entries):
            QMessageBox.warning(self, "No permitido", "Solo se pueden eliminar entradas en borrador. Deselecciona las que no lo sean.")
            return
        prompt = "¿Eliminar esta entrada local?" if len(ids) == 1 else f"¿Eliminar estas {len(ids)} entradas locales?"
        if QMessageBox.question(self, "Confirmar", prompt) == QMessageBox.StandardButton.Yes:
            for entry_id in ids:
                repo.delete_entry(self.conn, entry_id)
            self.refresh()

    # ---- Odoo monthly sync --------------------------------------------------

    def _on_sync_clicked(self) -> None:
        year, month = self._selected_year_month()
        self.sync_button.setEnabled(False)
        self.sync_button.setText("Sincronizando…")
        run_async(
            sync.import_month_from_odoo, self.conn, self.client, year, month,
            on_success=self._on_sync_success, on_error=self._on_sync_error,
        )

    def _on_sync_success(self, imported_count: int) -> None:
        self.sync_button.setEnabled(True)
        self.sync_button.setText("Actualizar desde Odoo")
        self.refresh()
        if imported_count:
            QMessageBox.information(self, "Sincronizado", f"Se importaron {imported_count} registro(s) nuevos desde Odoo.")
        else:
            QMessageBox.information(self, "Sincronizado", "No hay registros nuevos en Odoo para este mes.")

    def _on_sync_error(self, exc: Exception) -> None:
        self.sync_button.setEnabled(True)
        self.sync_button.setText("Actualizar desde Odoo")
        QMessageBox.warning(self, "Error al sincronizar", str(exc))
