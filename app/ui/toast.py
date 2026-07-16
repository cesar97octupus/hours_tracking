from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.ui import theme

_MARGIN = 16
_DURATION_MS = 8000
_active_toasts: set = set()  # keeps parentless top-level widgets alive until closed;
                              # otherwise Python GC would delete the underlying C++
                              # object as soon as the local variable goes out of scope


class Toast(QWidget):
    """A small always-on-top popup shown in the bottom-right corner of the
    screen. QSystemTrayIcon.showMessage()'s native balloon is unreliable on
    Windows 10/11 for apps without a registered AppUserModelID/installer —
    it's frequently suppressed with no error, so this doesn't depend on the
    OS notification pipeline at all."""

    def __init__(self, title: str, message: str):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        c = theme.get_toast_colors()
        self.setStyleSheet(
            f"""
            QWidget#toastCard {{
                background: {c['surface']};
                border: 1px solid {c['border']};
                border-radius: 8px;
            }}
            QLabel#toastTitle {{ color: {c['text']}; font-weight: 700; }}
            QLabel#toastMessage {{ color: {c['text_muted']}; }}
            """
        )

        card = QWidget(self)
        card.setObjectName("toastCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setObjectName("toastTitle")
        message_label = QLabel(message)
        message_label.setObjectName("toastMessage")
        message_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(message_label)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)
        self.setFixedWidth(320)

        self._position()
        self.show()
        QTimer.singleShot(_DURATION_MS, self.close)

    def _position(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.adjustSize()
        x = geo.right() - self.width() - _MARGIN
        y = geo.bottom() - self.height() - _MARGIN
        self.move(x, y)


def show_toast(title: str, message: str) -> Toast:
    toast = Toast(title, message)
    _active_toasts.add(toast)
    toast.destroyed.connect(lambda: _active_toasts.discard(toast))
    return toast
