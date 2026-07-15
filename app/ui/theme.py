import winreg

from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QWidget

_LIGHT = dict(
    bg="#f3f5f8", surface="#ffffff", border="#d7dbe2", text="#1f2430", text_muted="#6b7280",
    primary="#2f6fed", primary_hover="#2558c4", primary_pressed="#1d47a3", on_primary="#ffffff",
    accent="#06b6d4",
    danger="#c62828", disabled_bg="#f0f1f3", disabled_fg="#a8adb5",
    state_draft="#6b7280", state_pending="#2f6fed", state_synced="#1f8a4c", state_error="#c62828",
)

_DARK = dict(
    bg="#1c1f24", surface="#262a31", border="#3c4149", text="#e8eaed", text_muted="#9aa0aa",
    primary="#5b9bff", primary_hover="#7bacff", primary_pressed="#3f7de0", on_primary="#0d1117",
    accent="#22d3ee",
    danger="#ff7a7a", disabled_bg="#20242a", disabled_fg="#5b6169",
    state_draft="#9aa0aa", state_pending="#5b9bff", state_synced="#4cd97b", state_error="#ff7a7a",
)

_current = _LIGHT  # updated by apply_theme(); read by get_state_colors()


def _windows_prefers_dark() -> bool:
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return value == 0
    except OSError:
        return False


def get_state_colors() -> dict[str, str]:
    """Current theme's colors for time-entry states (draft/pending_sync/synced/error)."""
    return {
        "draft": _current["state_draft"],
        "pending_sync": _current["state_pending"],
        "synced": _current["state_synced"],
        "error": _current["state_error"],
    }


def get_ring_colors() -> dict[str, str]:
    """Current theme's colors for the TimerRingWidget."""
    return {
        "track": _current["border"],
        "gradient_start": _current["primary"],
        "gradient_end": _current["accent"],
        "text": _current["text"],
        "muted_text": _current["text_muted"],
    }


def _build_qss(c: dict) -> str:
    return f"""
* {{
    font-family: "Segoe UI", sans-serif;
    font-size: 10pt;
    color: {c['text']};
}}

QMainWindow, QDialog {{
    background: {c['bg']};
}}

QLabel {{
    background: transparent;
}}

QToolTip {{
    background: {c['surface']};
    color: {c['text']};
    border: 1px solid {c['border']};
}}

QTabWidget::pane {{
    border: 1px solid {c['border']};
    border-radius: 8px;
    background: {c['surface']};
    top: -1px;
}}

QTabBar::tab {{
    background: transparent;
    padding: 8px 20px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    color: {c['text_muted']};
}}

QTabBar::tab:selected {{
    background: {c['surface']};
    color: {c['text']};
    font-weight: 600;
    border: 1px solid {c['border']};
    border-bottom: none;
}}

QTabBar::tab:hover {{
    color: {c['text']};
}}

QPushButton {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 7px 16px;
    color: {c['text']};
}}

QPushButton:hover {{
    border-color: {c['primary']};
    color: {c['primary']};
}}

QPushButton:pressed {{
    background: {c['bg']};
}}

QPushButton:disabled {{
    color: {c['disabled_fg']};
    background: {c['disabled_bg']};
    border-color: {c['border']};
}}

QPushButton#primaryButton {{
    background: {c['primary']};
    color: {c['on_primary']};
    border: none;
    font-weight: 600;
    padding: 9px 18px;
}}

QPushButton#primaryButton:hover {{
    background: {c['primary_hover']};
    color: {c['on_primary']};
}}

QPushButton#primaryButton:pressed {{
    background: {c['primary_pressed']};
}}

QPushButton#primaryButton:disabled {{
    background: {c['disabled_bg']};
    color: {c['disabled_fg']};
}}

QPushButton#dangerButton:hover {{
    border-color: {c['danger']};
    color: {c['danger']};
}}

QPushButton#heroButton {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {c['primary']}, stop:1 {c['accent']});
    color: {c['on_primary']};
    border: none;
    border-radius: 20px;
    font-weight: 700;
    font-size: 11pt;
    padding: 10px 30px;
}}

QPushButton#heroButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {c['primary_hover']}, stop:1 {c['accent']});
    color: {c['on_primary']};
}}

QPushButton#heroButton:pressed {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {c['primary_pressed']}, stop:1 {c['accent']});
}}

QPushButton#heroButton:disabled {{
    background: {c['disabled_bg']};
    color: {c['disabled_fg']};
}}

QLineEdit, QComboBox, QDateEdit, QDoubleSpinBox {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 5px 8px;
    min-height: 22px;
    color: {c['text']};
    selection-background-color: {c['primary']};
    selection-color: {c['on_primary']};
}}

QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QDoubleSpinBox:focus {{
    border: 1px solid {c['primary']};
}}

QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled, QDoubleSpinBox:disabled {{
    background: {c['disabled_bg']};
    color: {c['disabled_fg']};
}}

QComboBox::drop-down {{
    border: none;
    width: 22px;
}}

QComboBox QAbstractItemView {{
    background: {c['surface']};
    color: {c['text']};
    border: 1px solid {c['border']};
    selection-background-color: {c['primary']};
    selection-color: {c['on_primary']};
    outline: none;
}}

QCalendarWidget QWidget {{
    background: {c['surface']};
    color: {c['text']};
}}

QRadioButton, QCheckBox {{
    spacing: 8px;
    background: transparent;
}}

QRadioButton::indicator, QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {c['border']};
    background: {c['surface']};
}}

QRadioButton::indicator {{
    border-radius: 8px;
}}

QCheckBox::indicator {{
    border-radius: 4px;
}}

QRadioButton::indicator:hover, QCheckBox::indicator:hover {{
    border: 1px solid {c['primary']};
}}

QRadioButton::indicator:checked {{
    border: 1px solid {c['primary']};
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 {c['primary']}, stop:0.45 {c['primary']}, stop:0.55 {c['surface']}, stop:1 {c['surface']});
}}

QCheckBox::indicator:checked {{
    border: 1px solid {c['primary']};
    background: {c['primary']};
}}

QRadioButton:disabled, QCheckBox:disabled {{
    color: {c['disabled_fg']};
}}

QRadioButton::indicator:disabled, QCheckBox::indicator:disabled {{
    background: {c['disabled_bg']};
    border-color: {c['border']};
}}

QTreeWidget, QTableWidget {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: 8px;
    alternate-background-color: {c['bg']};
    color: {c['text']};
    selection-background-color: {c['primary']};
    selection-color: {c['on_primary']};
    outline: none;
}}

QTreeWidget::item, QTableWidget::item {{
    padding: 5px 3px;
    border: none;
}}

QTreeWidget::item:selected, QTableWidget::item:selected,
QTreeWidget::item:selected:active, QTableWidget::item:selected:active,
QTreeWidget::item:selected:!active, QTableWidget::item:selected:!active {{
    background: {c['primary']};
    color: {c['on_primary']};
}}

QHeaderView::section {{
    background: {c['surface']};
    border: none;
    border-bottom: 1px solid {c['border']};
    padding: 7px 4px;
    font-weight: 600;
    color: {c['text_muted']};
}}

QLabel#elapsedLabel {{
    color: {c['primary']};
    font-weight: 600;
}}

QLabel#totalLabel {{
    color: {c['text_muted']};
    font-weight: 600;
    padding: 4px 0;
}}

QLabel#statusLabel {{
    color: {c['text_muted']};
}}

QMessageBox {{
    background: {c['surface']};
}}

QGroupBox {{
    border: 1px solid {c['border']};
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 16px;
    font-weight: 600;
    color: {c['text_muted']};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
}}
"""


def _build_palette(c: dict) -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(c["bg"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(c["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(c["surface"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(c["bg"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(c["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(c["surface"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(c["text"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(c["surface"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(c["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(c["primary"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(c["on_primary"]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(c["text_muted"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(c["disabled_fg"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(c["disabled_fg"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(c["disabled_fg"]))
    # Explicit Inactive group too: a selected row keeps its own colors even
    # when the window loses focus (otherwise Qt falls back to a muted gray
    # here that isn't legible against a dark surface).
    palette.setColor(QPalette.ColorGroup.Inactive, QPalette.ColorRole.Highlight, QColor(c["primary"]))
    palette.setColor(QPalette.ColorGroup.Inactive, QPalette.ColorRole.HighlightedText, QColor(c["on_primary"]))
    return palette


def apply_theme(app: QApplication) -> None:
    global _current
    _current = _DARK if _windows_prefers_dark() else _LIGHT
    app.setStyle("Fusion")
    app.setPalette(_build_palette(_current))
    app.setStyleSheet(_build_qss(_current))


def center_on_screen(widget: QWidget) -> None:
    screen = widget.screen() or QGuiApplication.primaryScreen()
    if screen is None:
        return
    geo = screen.availableGeometry()
    frame = widget.frameGeometry()
    frame.moveCenter(geo.center())
    widget.move(frame.topLeft())
