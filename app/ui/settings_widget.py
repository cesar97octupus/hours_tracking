from PySide6.QtCore import QTime, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from app import autostart, config
from app.timer import MAX_TIMER_SECONDS

_HOURS_ALARM_THRESHOLD = 0.8


def _time_from_str(value: str) -> QTime:
    time = QTime.fromString(value, "HH:mm")
    return time if time.isValid() else QTime(9, 0)


class SettingsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        cfg = config.load_config()
        ui = cfg.ui if cfg else config.UiPrefs()

        self.autostart_checkbox = QCheckBox("Iniciar automáticamente con Windows")
        self.autostart_checkbox.setChecked(ui.autostart_enabled)

        general_group = QGroupBox("General")
        general_layout = QVBoxLayout(general_group)
        general_layout.addWidget(self.autostart_checkbox)

        self.checkin_checkbox = QCheckBox("Recordar entrada")
        self.checkin_checkbox.setChecked(ui.checkin_alarm_enabled)
        self.checkin_time_edit = QTimeEdit(_time_from_str(ui.checkin_alarm_time))
        self.checkin_time_edit.setDisplayFormat("HH:mm")

        self.checkout_checkbox = QCheckBox("Recordar salida")
        self.checkout_checkbox.setChecked(ui.checkout_alarm_enabled)
        self.checkout_time_edit = QTimeEdit(_time_from_str(ui.checkout_alarm_time))
        self.checkout_time_edit.setDisplayFormat("HH:mm")

        checkin_row = QHBoxLayout()
        checkin_row.addWidget(self.checkin_checkbox)
        checkin_row.addWidget(self.checkin_time_edit)
        checkin_row.addStretch(1)

        checkout_row = QHBoxLayout()
        checkout_row.addWidget(self.checkout_checkbox)
        checkout_row.addWidget(self.checkout_time_edit)
        checkout_row.addStretch(1)

        alarms_group = QGroupBox("Alarmas de asistencia")
        alarms_layout = QVBoxLayout(alarms_group)
        alarms_layout.addLayout(checkin_row)
        alarms_layout.addLayout(checkout_row)

        expected_hours = MAX_TIMER_SECONDS / 3600
        threshold_hours = expected_hours * _HOURS_ALARM_THRESHOLD
        self.hours_checkbox = QCheckBox("Recordar registrar horas")
        self.hours_checkbox.setChecked(ui.hours_alarm_enabled)
        self.hours_time_edit = QTimeEdit(_time_from_str(ui.hours_alarm_time))
        self.hours_time_edit.setDisplayFormat("HH:mm")

        hours_row = QHBoxLayout()
        hours_row.addWidget(self.hours_checkbox)
        hours_row.addWidget(self.hours_time_edit)
        hours_row.addStretch(1)

        hours_hint = QLabel(
            f"Si a esa hora no has registrado al menos el {int(_HOURS_ALARM_THRESHOLD * 100)}% de tu "
            f"jornada ({threshold_hours:.1f} h de {expected_hours:.0f} h), te lo recordamos."
        )
        hours_hint.setObjectName("statusLabel")
        hours_hint.setWordWrap(True)

        hours_group = QGroupBox("Registro de horas")
        hours_layout = QVBoxLayout(hours_group)
        hours_layout.addLayout(hours_row)
        hours_layout.addWidget(hours_hint)

        self.save_button = QPushButton("Guardar")
        self.save_button.clicked.connect(self._on_save_clicked)
        self.saved_label = QLabel("")
        self.saved_label.setObjectName("statusLabel")

        save_row = QHBoxLayout()
        save_row.addWidget(self.save_button)
        save_row.addWidget(self.saved_label)
        save_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)
        layout.addWidget(general_group)
        layout.addWidget(alarms_group)
        layout.addWidget(hours_group)
        layout.addLayout(save_row)
        layout.addStretch(1)

    def _on_save_clicked(self) -> None:
        cfg = config.load_config()
        if not cfg:
            return
        cfg.ui.autostart_enabled = self.autostart_checkbox.isChecked()
        cfg.ui.checkin_alarm_enabled = self.checkin_checkbox.isChecked()
        cfg.ui.checkin_alarm_time = self.checkin_time_edit.time().toString("HH:mm")
        cfg.ui.checkout_alarm_enabled = self.checkout_checkbox.isChecked()
        cfg.ui.checkout_alarm_time = self.checkout_time_edit.time().toString("HH:mm")
        cfg.ui.hours_alarm_enabled = self.hours_checkbox.isChecked()
        cfg.ui.hours_alarm_time = self.hours_time_edit.time().toString("HH:mm")
        config.save_config(cfg)
        autostart.set_enabled(cfg.ui.autostart_enabled)

        self.saved_label.setText("Cambios guardados ✓")
        QTimer.singleShot(3000, lambda: self.saved_label.setText(""))
