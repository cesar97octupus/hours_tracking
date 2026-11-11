import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app import todo_repository as trepo
from app.ui import theme


class CategoryDialog(QDialog):
    """Rename, recolor and delete TODO categories."""

    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("Gestionar categorías")
        self.resize(340, 380)

        self.list = QListWidget()
        self.list.itemSelectionChanged.connect(self._update_buttons)
        self.list.itemDoubleClicked.connect(lambda _i: self._rename())

        self.rename_btn = QPushButton("Renombrar…")
        self.rename_btn.clicked.connect(self._rename)
        self.color_btn = QPushButton("Color…")
        self.color_btn.clicked.connect(self._recolor)
        self.delete_btn = QPushButton("Eliminar")
        self.delete_btn.clicked.connect(self._delete)

        buttons = QHBoxLayout()
        for b in (self.rename_btn, self.color_btn, self.delete_btn):
            buttons.addWidget(b)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(self.list, 1)
        layout.addLayout(buttons)
        layout.addWidget(close)
        self._reload()

    def _reload(self, select_id: int | None = None) -> None:
        self.list.clear()
        for c in trepo.list_categories(self.conn):
            item = QListWidgetItem(theme.color_dot_icon(c.color), c.name)
            item.setData(Qt.ItemDataRole.UserRole, c)
            self.list.addItem(item)
            if c.id == select_id:
                self.list.setCurrentItem(item)
        self._update_buttons()

    def _current(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _update_buttons(self) -> None:
        on = self._current() is not None
        for b in (self.rename_btn, self.color_btn, self.delete_btn):
            b.setEnabled(on)

    def _rename(self) -> None:
        cat = self._current()
        if cat is None:
            return
        name, ok = QInputDialog.getText(self, "Renombrar categoría", "Nuevo nombre:", text=cat.name)
        if not ok:
            return
        try:
            trepo.update_category(self.conn, cat.id, name=name)
        except ValueError as e:
            QMessageBox.warning(self, "Nombre no válido", str(e))
            return
        self._reload(cat.id)

    def _recolor(self) -> None:
        cat = self._current()
        if cat is None:
            return
        color = QColorDialog.getColor(QColor(cat.color), self, "Color de la categoría")
        if color.isValid():
            trepo.update_category(self.conn, cat.id, color=color.name())
            self._reload(cat.id)

    def _delete(self) -> None:
        cat = self._current()
        if cat is None:
            return
        n = trepo.count_category_todos(self.conn, cat.id)
        extra = f"\n{n} TODO(s) quedarán sin categoría." if n else ""
        if QMessageBox.question(self, "Eliminar categoría", f"¿Eliminar «{cat.name}»?{extra}") != (
            QMessageBox.StandardButton.Yes
        ):
            return
        trepo.delete_category(self.conn, cat.id)
        self._reload()
