from PySide6.QtCore import QTime
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from app import autostart, config


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
        self.autostart_checkbox.stateChanged.connect(self._on_autostart_changed)

        general_group = QGroupBox("General")
        general_layout = QVBoxLayout(general_group)
        general_layout.addWidget(self.autostart_checkbox)

        self.checkin_checkbox = QCheckBox("Recordar entrada")
        self.checkin_checkbox.setChecked(ui.checkin_alarm_enabled)
        self.checkin_checkbox.stateChanged.connect(self._on_alarms_changed)
        self.checkin_time_edit = QTimeEdit(_time_from_str(ui.checkin_alarm_time))
        self.checkin_time_edit.setDisplayFormat("HH:mm")
        self.checkin_time_edit.timeChanged.connect(self._on_alarms_changed)

        self.checkout_checkbox = QCheckBox("Recordar salida")
        self.checkout_checkbox.setChecked(ui.checkout_alarm_enabled)
        self.checkout_checkbox.stateChanged.connect(self._on_alarms_changed)
        self.checkout_time_edit = QTimeEdit(_time_from_str(ui.checkout_alarm_time))
        self.checkout_time_edit.setDisplayFormat("HH:mm")
        self.checkout_time_edit.timeChanged.connect(self._on_alarms_changed)

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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)
        layout.addWidget(general_group)
        layout.addWidget(alarms_group)
        layout.addStretch(1)

    def _on_autostart_changed(self, _state: int) -> None:
        enabled = self.autostart_checkbox.isChecked()
        autostart.set_enabled(enabled)
        self._update_config(autostart_enabled=enabled)

    def _on_alarms_changed(self, *_args) -> None:
        self._update_config(
            checkin_alarm_enabled=self.checkin_checkbox.isChecked(),
            checkin_alarm_time=self.checkin_time_edit.time().toString("HH:mm"),
            checkout_alarm_enabled=self.checkout_checkbox.isChecked(),
            checkout_alarm_time=self.checkout_time_edit.time().toString("HH:mm"),
        )

    def _update_config(self, **fields) -> None:
        cfg = config.load_config()
        if not cfg:
            return
        for key, value in fields.items():
            setattr(cfg.ui, key, value)
        config.save_config(cfg)
