import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QConicalGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

from app.ui import theme

_STROKE_WIDTH = 10
_SIZE = 220


class TimerRingWidget(QWidget):
    """Circular progress ring showing elapsed time toward the 7h auto-stop
    safety cutoff, with the HH:MM:SS readout centered inside. Inspired by
    focus-timer apps' progress rings, repurposed here for a count-up
    (not count-down) timer with no fixed session length."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(_SIZE, _SIZE)
        self._progress = 0.0
        self._time_text = "00:00:00"
        self._running = False
        self._colors: dict[str, str] = {}
        self.refresh_theme()

    def refresh_theme(self) -> None:
        self._colors = theme.get_ring_colors()
        self.update()

    def set_progress(self, value: float) -> None:
        self._progress = max(0.0, min(1.0, value))
        self.update()

    def set_time_text(self, text: str) -> None:
        self._time_text = text
        self.update()

    def set_running(self, running: bool) -> None:
        self._running = running
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        margin = _STROKE_WIDTH / 2 + 4
        rect = QRectF(margin, margin, self.width() - 2 * margin, self.height() - 2 * margin)

        track_pen = QPen(QColor(self._colors["track"]), _STROKE_WIDTH)
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track_pen)
        painter.drawArc(rect, 0, 360 * 16)

        if self._progress > 0.002:
            gradient = QConicalGradient(rect.center(), 90)
            gradient.setColorAt(0.0, QColor(self._colors["gradient_start"]))
            gradient.setColorAt(1.0, QColor(self._colors["gradient_end"]))
            progress_pen = QPen(gradient, _STROKE_WIDTH)
            progress_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(progress_pen)
            span = -int(self._progress * 360 * 16)
            painter.drawArc(rect, 90 * 16, span)

            if self._progress < 0.995:
                angle_rad = math.radians(90 - self._progress * 360)
                r = rect.width() / 2
                cx = rect.center().x() + r * math.cos(angle_rad)
                cy = rect.center().y() - r * math.sin(angle_rad)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(self._colors["gradient_end"]))
                painter.drawEllipse(QRectF(cx - 4, cy - 4, 8, 8))

        painter.setPen(QColor(self._colors["text"] if self._running else self._colors["muted_text"]))
        font = painter.font()
        font.setFamily("Consolas")
        font.setPointSize(24)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._time_text)
