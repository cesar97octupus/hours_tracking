import sqlite3
from datetime import date, datetime, timezone

from PySide6.QtCore import QDate, QTimer as QtTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QStyle,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app import config, repository as repo
from app import timesheet_sync as sync
from app.dto import TaskRef, TicketRef
from app.odoo_client import OdooClient
from app.rounding import round_up_to_quarter_hour
from app.timer import MAX_TIMER_SECONDS, Timer, start_and_persist, stop_and_persist
from app.ui import theme
from app.ui.entries_list_widget import EntriesListWidget
from app.ui.entry_dialog import EntryDialog
from app.ui.settings_widget import SettingsWidget
from app.ui.timer_ring import TimerRingWidget
from app.ui.tray import Tray
from app.ui.workers import run_async


def _format_hms(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class MainWindow(QMainWindow):
    def __init__(self, conn: sqlite3.Connection, client: OdooClient):
        super().__init__()
        self.conn = conn
        self.client = client
        self.timer: Timer | None = None
        self._tasks: list[TaskRef] = []
        self._tickets: list[TicketRef] = []
        self._task_ids_with_hours: set[int] = set()
        self._ticket_ids_with_hours: set[int] = set()
        self.helpdesk_installed = bool((repo.get_app_state(conn, "helpdesk_installed") or {}).get("value"))
        self.attendance_installed = bool((repo.get_app_state(conn, "attendance_installed") or {}).get("value"))
        # (date, configured HH:MM) of the last notification fired per alarm —
        # keying on the configured time too (not just the date) means editing
        # an alarm's time later the same day counts as a new target and fires
        # again, instead of staying silenced because "today" already notified.
        self._checkin_notified_key: tuple[date, str] | None = None
        self._checkout_notified_key: tuple[date, str] | None = None
        self._hours_notified_key: tuple[date, str] | None = None
        saved_ui = (config.load_config() or config.AppConfig(odoo_url="", odoo_db="", odoo_username="")).ui
        self._pending_stage_filter_id = saved_ui.filter_stage_id

        self.setWindowTitle("hours_tracking")
        self.resize(640, 560)
        theme.center_on_screen(self)

        self.status_label = QLabel("Conectando…")
        self.status_label.setObjectName("statusLabel")

        self.task_radio = QRadioButton("Tarea")
        self.task_radio.setChecked(True)
        self.ticket_radio = QRadioButton("Ticket")
        self.ticket_radio.setVisible(self.helpdesk_installed)
        self.task_radio.toggled.connect(self._on_picker_mode_changed)

        self.picker_combo = QComboBox()
        self.description_edit = QLineEdit()
        self.description_edit.setPlaceholderText("Descripción del trabajo…")

        self.stage_filter_combo = QComboBox()
        self.stage_filter_combo.currentIndexChanged.connect(lambda _i: self._on_stage_filter_changed())

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Buscar por nombre…")
        self.search_edit.textChanged.connect(lambda _t: self._reload_combo())

        self.no_hours_checkbox = QCheckBox("Solo sin registros de horas")
        self.no_hours_checkbox.setToolTip(
            "Se actualiza al pulsar «Actualizar tareas/tickets» — consulta a Odoo cuáles no tienen ninguna hora registrada."
        )
        self.no_hours_checkbox.stateChanged.connect(lambda _s: self._on_no_hours_toggled())

        self.refresh_button = QPushButton()
        self.refresh_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self.refresh_button.setToolTip("Actualizar tareas/tickets")
        self.refresh_button.setFixedSize(28, 28)
        self.refresh_button.setEnabled(False)
        self.refresh_button.clicked.connect(lambda: self._refresh_picker(live=True))

        self.created_after_checkbox = QCheckBox("Creadas desde:")
        self.created_after_checkbox.stateChanged.connect(self._on_created_after_toggled)
        self.created_after_edit = QDateEdit(QDate.currentDate())
        self.created_after_edit.setCalendarPopup(True)
        self.created_after_edit.setEnabled(False)
        self.created_after_edit.dateChanged.connect(lambda _d: self._on_created_after_date_changed())

        if saved_ui.filter_no_hours_only:
            self.no_hours_checkbox.setChecked(True)
        if saved_ui.filter_created_after_date:
            parsed_date = QDate.fromString(saved_ui.filter_created_after_date, "yyyy-MM-dd")
            if parsed_date.isValid():
                self.created_after_edit.setDate(parsed_date)
        if saved_ui.filter_created_after_enabled:
            self.created_after_checkbox.setChecked(True)

        self.attendance_button = QPushButton("Registrar entrada")
        self.attendance_button.clicked.connect(self._on_attendance_clicked)

        self.attendance_dot = QLabel("●")
        self.attendance_dot.setStyleSheet("color: red; font-size: 14px;")
        self.attendance_dot.setToolTip("Sin fichar")

        self.attendance_corner = QWidget()
        attendance_corner_layout = QHBoxLayout(self.attendance_corner)
        attendance_corner_layout.setContentsMargins(0, 0, 8, 0)
        attendance_corner_layout.setSpacing(6)
        attendance_corner_layout.addWidget(self.attendance_button)
        attendance_corner_layout.addWidget(self.attendance_dot)
        self.attendance_corner.setVisible(self.attendance_installed)

        self.start_stop_button = QPushButton("Iniciar")
        self.start_stop_button.setObjectName("heroButton")
        self.start_stop_button.setMinimumHeight(40)
        self.start_stop_button.clicked.connect(lambda: self._on_start_stop_clicked())

        self.timer_ring = TimerRingWidget()

        picker_row = QHBoxLayout()
        picker_row.setSpacing(10)
        picker_row.addWidget(self.task_radio)
        picker_row.addWidget(self.ticket_radio)
        picker_row.addWidget(self.picker_combo, 1)
        picker_row.addWidget(self.refresh_button)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(10)
        filter_row.addWidget(QLabel("Estado:"))
        filter_row.addWidget(self.stage_filter_combo)
        filter_row.addWidget(self.search_edit, 1)
        filter_row.addWidget(self.no_hours_checkbox)
        filter_row.addWidget(self.created_after_checkbox)
        filter_row.addWidget(self.created_after_edit)

        picker_group = QGroupBox("Selecciona una tarea o ticket")
        picker_group_layout = QVBoxLayout(picker_group)
        picker_group_layout.setSpacing(10)
        picker_group_layout.addLayout(picker_row)
        picker_group_layout.addLayout(filter_row)

        timer_group = QGroupBox("Cronómetro")
        timer_group_layout = QVBoxLayout(timer_group)
        timer_group_layout.setSpacing(12)
        timer_group_layout.addWidget(self.description_edit)
        timer_group_layout.addWidget(self.timer_ring, alignment=Qt.AlignmentFlag.AlignHCenter)
        timer_group_layout.addWidget(self.start_stop_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(16, 16, 16, 16)
        controls_layout.setSpacing(14)
        controls_layout.addWidget(self.status_label)
        controls_layout.addWidget(picker_group)
        controls_layout.addWidget(timer_group)
        controls_layout.addStretch(1)

        self.entries_widget = EntriesListWidget(conn, client)

        self.tabs = QTabWidget()
        self.tabs.addTab(controls, "Cronómetro")
        self.tabs.addTab(self.entries_widget, "Partes de horas")
        self.tabs.addTab(SettingsWidget(), "Configuración")
        self.tabs.setCornerWidget(self.attendance_corner, Qt.Corner.TopRightCorner)
        self.setCentralWidget(self.tabs)

        self.tray = Tray(self)
        self.tray.show_window_requested.connect(self._show_and_raise)
        self.tray.start_stop_requested.connect(self._on_start_stop_clicked)
        self.tray.quit_requested.connect(self._on_quit_requested)
        self.tray.show()

        self.tick_timer = QtTimer(self)
        self.tick_timer.setInterval(1000)
        self.tick_timer.timeout.connect(self._on_tick)

        self.alarm_timer = QtTimer(self)
        self.alarm_timer.setInterval(30_000)
        self.alarm_timer.timeout.connect(self._check_alarms)
        self.alarm_timer.start()

        self._load_cached_picker()
        self._connect_and_load()
        self._check_crash_recovery()

    # ---- connection / data loading -----------------------------------

    def _connect_and_load(self) -> None:
        run_async(self.client.authenticate, on_success=self._on_authenticated, on_error=self._on_connect_error)

    def _on_authenticated(self, _uid: int) -> None:
        self.status_label.setText("Conectado.")
        self.refresh_button.setEnabled(True)
        self._refresh_picker(live=True)
        if self.attendance_installed:
            self._refresh_attendance_status()
        run_async(
            sync.revalidate_employee, self.conn, self.client,
            on_success=self._on_employee_revalidated, on_error=self._on_employee_revalidate_error,
        )

    def _on_connect_error(self, exc: Exception) -> None:
        self.status_label.setText(f"No se pudo conectar: {exc}")

    def _on_employee_revalidated(self, _employee) -> None:
        pass  # local cache already refreshed inside sync.revalidate_employee

    def _on_employee_revalidate_error(self, exc: Exception) -> None:
        # Deliberately don't touch the cached employee here: keep whatever was
        # last known-good so exports/timer keep working off it rather than
        # losing the cache entirely over a transient RPC hiccup.
        self.status_label.setText(f"Conectado, pero no se pudo validar el empleado: {exc}")

    def _load_cached_picker(self) -> None:
        self._populate_picker(repo.list_cached_tasks(self.conn), repo.list_cached_tickets(self.conn))

    def _refresh_picker(self, live: bool = False) -> None:
        if not live:
            self._load_cached_picker()
            return
        run_async(self.client.fetch_my_tasks, on_success=self._on_tasks_fetched, on_error=self._on_fetch_error)
        if self.helpdesk_installed:
            run_async(self.client.fetch_my_tickets, on_success=self._on_tickets_fetched, on_error=self._on_fetch_error)

    def _on_tasks_fetched(self, tasks: list[TaskRef]) -> None:
        repo.replace_cached_tasks(self.conn, tasks)
        self._populate_picker(repo.list_cached_tasks(self.conn), repo.list_cached_tickets(self.conn))
        run_async(
            self.client.fetch_ids_with_hours, "task_id", [t.id for t in tasks],
            on_success=self._on_task_hours_flags_fetched, on_error=self._on_fetch_error,
        )

    def _on_tickets_fetched(self, tickets: list[TicketRef]) -> None:
        repo.replace_cached_tickets(self.conn, tickets)
        self._populate_picker(repo.list_cached_tasks(self.conn), repo.list_cached_tickets(self.conn))
        run_async(
            self.client.fetch_ids_with_hours, "helpdesk_ticket_id", [t.id for t in tickets],
            on_success=self._on_ticket_hours_flags_fetched, on_error=self._on_fetch_error,
        )

    def _on_task_hours_flags_fetched(self, ids_with_hours: set[int]) -> None:
        self._task_ids_with_hours = ids_with_hours
        self._reload_combo()

    def _on_ticket_hours_flags_fetched(self, ids_with_hours: set[int]) -> None:
        self._ticket_ids_with_hours = ids_with_hours
        self._reload_combo()

    def _on_fetch_error(self, exc: Exception) -> None:
        self.status_label.setText(f"Error al actualizar tareas/tickets: {exc}")

    def _populate_picker(self, tasks: list[TaskRef], tickets: list[TicketRef]) -> None:
        self._tasks = tasks
        self._tickets = tickets
        self._refresh_stage_filter_options()
        self._reload_combo()

    def _current_items(self) -> list[TaskRef] | list[TicketRef]:
        return self._tasks if self.task_radio.isChecked() else self._tickets

    def _refresh_stage_filter_options(self) -> None:
        stages: dict[int, str] = {}
        for item in self._current_items():
            if item.stage_id is not None:
                stages[item.stage_id] = item.stage_name or str(item.stage_id)

        previous = self.stage_filter_combo.currentData()
        if previous is None and self._pending_stage_filter_id is not None:
            previous = self._pending_stage_filter_id
            self._pending_stage_filter_id = None
        self.stage_filter_combo.blockSignals(True)
        self.stage_filter_combo.clear()
        self.stage_filter_combo.addItem("Todos los estados", None)
        for stage_id, stage_name in sorted(stages.items(), key=lambda kv: kv[1].lower()):
            self.stage_filter_combo.addItem(stage_name, stage_id)
        idx = self.stage_filter_combo.findData(previous)
        self.stage_filter_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.stage_filter_combo.blockSignals(False)

    def _reload_combo(self) -> None:
        self.picker_combo.clear()
        stage_filter = self.stage_filter_combo.currentData()
        search_text = self.search_edit.text().strip().lower()
        only_no_hours = self.no_hours_checkbox.isChecked()
        created_after = self.created_after_edit.date().toPython() if self.created_after_checkbox.isChecked() else None
        ids_with_hours = self._task_ids_with_hours if self.task_radio.isChecked() else self._ticket_ids_with_hours
        for item in self._current_items():
            if stage_filter is not None and item.stage_id != stage_filter:
                continue
            if search_text and search_text not in item.name.lower():
                continue
            if only_no_hours and item.id in ids_with_hours:
                continue
            if created_after and item.create_date and date.fromisoformat(item.create_date[:10]) < created_after:
                continue
            label = f"#{item.id} {item.name}"
            if item.project_name:
                label += f" ({item.project_name})"
            if item.stage_name:
                label += f" [{item.stage_name}]"
            self.picker_combo.addItem(label, item.id)

    def _on_picker_mode_changed(self, _checked: bool) -> None:
        self._refresh_stage_filter_options()
        self._reload_combo()

    def _on_stage_filter_changed(self) -> None:
        self._reload_combo()
        self._persist_filters()

    def _on_no_hours_toggled(self) -> None:
        self._reload_combo()
        self._persist_filters()

    def _on_created_after_toggled(self, _state: int) -> None:
        self.created_after_edit.setEnabled(self.created_after_checkbox.isChecked())
        self._reload_combo()
        self._persist_filters()

    def _on_created_after_date_changed(self) -> None:
        self._reload_combo()
        self._persist_filters()

    def _persist_filters(self) -> None:
        cfg = config.load_config()
        if not cfg:
            return
        cfg.ui.filter_stage_id = self.stage_filter_combo.currentData()
        cfg.ui.filter_no_hours_only = self.no_hours_checkbox.isChecked()
        cfg.ui.filter_created_after_enabled = self.created_after_checkbox.isChecked()
        cfg.ui.filter_created_after_date = self.created_after_edit.date().toString("yyyy-MM-dd")
        config.save_config(cfg)

    # ---- timer control --------------------------------------------------

    def _on_start_stop_clicked(self) -> None:
        if self.timer is None:
            self._start_timer()
        else:
            self._stop_timer()

    def _start_timer(self) -> None:
        item_id = self.picker_combo.currentData()
        if item_id is None:
            QMessageBox.warning(self, "Selecciona una tarea o ticket", "Debes seleccionar una tarea o ticket antes de iniciar.")
            return

        is_task = self.task_radio.isChecked()
        label = self.picker_combo.currentText()
        self.timer = Timer(
            description=self.description_edit.text(),
            task_id=item_id if is_task else None,
            task_name=label if is_task else None,
            ticket_id=item_id if not is_task else None,
            ticket_name=label if not is_task else None,
        )
        start_and_persist(self.conn, self.timer)
        self.tick_timer.start()
        self._set_running_ui(True)

    def _stop_timer(self, *, auto: bool = False) -> None:
        if self.timer is None:
            return
        entry_id = stop_and_persist(self.conn, self.timer)
        self.timer = None
        self.tick_timer.stop()
        self._set_running_ui(False)
        self.entries_widget.refresh()
        if auto:
            self.tray.notify("hours_tracking", "El cronómetro se detuvo automáticamente tras 7 horas.")
        dialog = EntryDialog(self.conn, entry_id, self.client, parent=self)
        dialog.exec()
        self.entries_widget.refresh()

    def _set_running_ui(self, running: bool) -> None:
        self.start_stop_button.setText("Detener" if running else "Iniciar")
        self.task_radio.setEnabled(not running)
        self.ticket_radio.setEnabled(not running)
        self.picker_combo.setEnabled(not running)
        self.description_edit.setEnabled(not running)
        self.tray.set_running(running, self.description_edit.text())
        self.timer_ring.set_running(running)
        if not running:
            self.timer_ring.set_time_text("00:00:00")
            self.timer_ring.set_progress(0.0)

    def _on_tick(self) -> None:
        if self.timer is None:
            return
        elapsed = self.timer.elapsed_seconds()
        self.timer_ring.set_time_text(_format_hms(elapsed))
        self.timer_ring.set_progress(elapsed / MAX_TIMER_SECONDS)
        self.tray.set_running(True, _format_hms(elapsed))
        if self.timer.exceeded_max_duration():
            self._stop_timer(auto=True)

    # ---- attendance (check-in / check-out) -------------------------------

    def _refresh_attendance_status(self) -> None:
        run_async(
            self.client.fetch_attendance_status,
            on_success=self._apply_attendance_status, on_error=self._on_attendance_error,
        )

    def _apply_attendance_status(self, status: dict) -> None:
        self.attendance_button.setEnabled(True)
        checked_in = status.get("attendance_state") == "checked_in"
        self.attendance_dot.setStyleSheet(f"color: {'green' if checked_in else 'red'}; font-size: 14px;")
        self.attendance_dot.setToolTip("Fichado" if checked_in else "Sin fichar")
        self.attendance_button.setText("Registrar salida" if checked_in else "Registrar entrada")

    def _on_attendance_clicked(self) -> None:
        self.attendance_button.setEnabled(False)
        run_async(
            self.client.toggle_attendance,
            on_success=self._apply_attendance_status, on_error=self._on_attendance_error,
        )

    def _on_attendance_error(self, exc: Exception) -> None:
        self.attendance_button.setEnabled(True)
        QMessageBox.warning(self, "Error de asistencia", str(exc))

    # ---- attendance alarms -------------------------------------------------

    def _check_alarms(self) -> None:
        cfg = config.load_config()
        if not cfg:
            return
        now = datetime.now()
        today = now.date()
        current_hm = now.strftime("%H:%M")

        # ">=" rather than "==": a 30s poll only overlaps the alarm's exact
        # minute for one or two ticks, so an app that starts late, wakes from
        # sleep, or hiccups on a tick would otherwise miss that alarm for the
        # rest of the day. The (date, configured time) key means it still
        # fires only once per target — but editing the time later the same
        # day is a new target, so it fires again instead of staying silenced.
        if cfg.ui.checkin_alarm_enabled and current_hm >= cfg.ui.checkin_alarm_time:
            key = (today, cfg.ui.checkin_alarm_time)
            if self._checkin_notified_key != key:
                self._checkin_notified_key = key
                self.tray.notify("hours_tracking", "Recuerda registrar tu entrada.")

        if cfg.ui.checkout_alarm_enabled and current_hm >= cfg.ui.checkout_alarm_time:
            key = (today, cfg.ui.checkout_alarm_time)
            if self._checkout_notified_key != key:
                self._checkout_notified_key = key
                self.tray.notify("hours_tracking", "Recuerda registrar tu salida.")

        if cfg.ui.hours_alarm_enabled and current_hm >= cfg.ui.hours_alarm_time:
            key = (today, cfg.ui.hours_alarm_time)
            if self._hours_notified_key != key:
                self._hours_notified_key = key
                self._notify_hours_logged_today(today)

    def _notify_hours_logged_today(self, today: date) -> None:
        logged = sum(
            e.unit_amount for e in repo.list_entries(self.conn) if e.entry_date == today.isoformat()
        )
        self.tray.notify(
            "hours_tracking",
            f"Por favor, recuerde registrar sus horas. Ha registrado {logged:.2f} h hasta el momento.",
        )

    # ---- crash recovery -------------------------------------------------

    def _check_crash_recovery(self) -> None:
        active = repo.get_active_timer(self.conn)
        if not active:
            return
        start_ts = active["start_ts"]
        target = active["task_name"] or active["ticket_name"] or "(sin nombre)"
        box = QMessageBox(self)
        box.setWindowTitle("Cronómetro sin finalizar")
        box.setText(
            f"Había un cronómetro corriendo para '{target}' iniciado a las {start_ts} "
            f"cuando la aplicación se cerró inesperadamente."
        )
        resume_btn = box.addButton("Reanudar", QMessageBox.ButtonRole.AcceptRole)
        stop_btn = box.addButton("Detener y guardar ahora", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Descartar", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()

        if clicked is resume_btn:
            self.timer = Timer(
                description=active["description"],
                task_id=active["task_id"], task_name=active["task_name"],
                ticket_id=active["ticket_id"], ticket_name=active["ticket_name"],
            )
            self.timer.resume_from(datetime.fromisoformat(start_ts))
            self.tick_timer.start()
            self._set_running_ui(True)
        elif clicked is stop_btn:
            self._recover_stop_and_save(active)
        else:
            repo.clear_active_timer(self.conn)

    def _recover_stop_and_save(self, active: dict) -> None:
        start_wall = datetime.fromisoformat(active["start_ts"])
        end_wall = datetime.now(timezone.utc)
        elapsed = (end_wall - start_wall).total_seconds()
        repo.clear_active_timer(self.conn)
        repo.create_draft_entry(
            self.conn,
            description=active["description"],
            task_id=active["task_id"], task_name=active["task_name"],
            ticket_id=active["ticket_id"], ticket_name=active["ticket_name"],
            type_analytic_kind=None, type_analytic_value=None, type_analytic_id=None, type_analytic_label=None,
            start_ts=active["start_ts"], end_ts=end_wall.isoformat(),
            elapsed_seconds=int(elapsed), unit_amount=round_up_to_quarter_hour(elapsed),
            entry_date=start_wall.date().isoformat(),
        )
        self.entries_widget.refresh()

    # ---- window / tray lifecycle -----------------------------------------

    def _show_and_raise(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()
        self.tray.notify("hours_tracking", "La aplicación sigue ejecutándose en la bandeja del sistema.")

    def _on_quit_requested(self) -> None:
        if self.timer is not None:
            answer = QMessageBox.question(
                self, "Cronómetro en ejecución",
                "Hay un cronómetro corriendo. Si sales ahora se detendrá el seguimiento en esta sesión, "
                "pero podrás reanudarlo o guardarlo la próxima vez que abras la aplicación. ¿Salir de todas formas?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        QApplication.instance().quit()
