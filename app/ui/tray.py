from PySide6.QtCore import Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QStyle, QSystemTrayIcon, QWidget


class Tray(QSystemTrayIcon):
    show_window_requested = Signal()
    start_stop_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent: QWidget):
        icon = parent.style().standardIcon(QStyle.StandardPixmap.SP_DialogYesButton)
        super().__init__(icon, parent)
        self.setToolTip("hours_tracking")

        menu = QMenu(parent)
        self.show_action = menu.addAction("Mostrar ventana")
        self.show_action.triggered.connect(self.show_window_requested.emit)

        self.start_stop_action = menu.addAction("Iniciar")
        self.start_stop_action.triggered.connect(self.start_stop_requested.emit)

        menu.addSeparator()
        quit_action = menu.addAction("Salir")
        quit_action.triggered.connect(self.quit_requested.emit)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_window_requested.emit()

    def set_running(self, running: bool, label: str = "") -> None:
        self.start_stop_action.setText("Detener" if running else "Iniciar")
        self.setToolTip(f"hours_tracking — {label}" if running and label else "hours_tracking")

    def notify(self, title: str, message: str) -> None:
        self.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 5000)
