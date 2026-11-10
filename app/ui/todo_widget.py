import logging
import sqlite3

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import todo_export
from app import todo_repository as trepo
from app.dto import Todo
from app.ui.todo_wizard import TodoWizard

log = logging.getLogger(__name__)

_ROLE = Qt.ItemDataRole.UserRole
_PRIO_MARK = {"high": "▲ ", "medium": "", "low": "▽ "}

_SECTIONS = (
    ("today", "Hoy"),
    ("carried", "Arrastrados"),
    ("upcoming", "Próximos"),
    ("done", "Hechos"),
    ("dropped", "Descartados"),
)

_FILTER_OPEN, _FILTER_ALL = "open", "all"


class TodoWidget(QWidget):
    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self.conn = conn
        self._loading = False

        self.quick_edit = QLineEdit()
        self.quick_edit.setPlaceholderText("Añadir TODO rápido para hoy y pulsa Enter…")
        self.quick_edit.returnPressed.connect(self._quick_add)
        self.add_button = QPushButton("Añadir")
        self.add_button.setObjectName("primaryButton")
        self.add_button.setToolTip("Nuevo TODO (asistente)")
        self.add_button.setMinimumWidth(80)
        self.add_button.clicked.connect(self._open_wizard)

        self.delete_button = QPushButton("Eliminar")
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.setToolTip("Eliminar el TODO o subtarea seleccionado (Supr)")
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self._delete_selected)

        self.category_filter = QComboBox()
        self.category_filter.currentIndexChanged.connect(lambda _i: self.reload())
        self.status_filter = QComboBox()
        self.status_filter.addItem("Abiertos y hechos hoy", _FILTER_OPEN)
        self.status_filter.addItem("Todos", _FILTER_ALL)
        self.status_filter.currentIndexChanged.connect(lambda _i: self.reload())
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Buscar…")
        self.search_edit.textChanged.connect(lambda _t: self.reload())

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(18)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.itemSelectionChanged.connect(self._update_delete_enabled)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self.tree, activated=self._delete_selected,
                  context=Qt.ShortcutContext.WidgetShortcut)

        top = QHBoxLayout()
        top.addWidget(self.quick_edit, 1)
        top.addWidget(self.add_button)
        top.addWidget(self.delete_button)
        filters = QHBoxLayout()
        filters.addWidget(self.category_filter)
        filters.addWidget(self.status_filter)
        filters.addWidget(self.search_edit, 1)
        root = QVBoxLayout(self)
        root.addLayout(top)
        root.addLayout(filters)
        root.addWidget(self.tree, 1)

        self._reload_categories()
        self.reload()
        self.export()
        # Refresh the file (and the Hoy/Arrastrados split) when the day rolls over.
        self._day = trepo.today_iso()
        self._day_timer = QTimer(self)
        self._day_timer.setInterval(60_000)
        self._day_timer.timeout.connect(self._check_day_rollover)
        self._day_timer.start()

    def _check_day_rollover(self) -> None:
        if trepo.today_iso() != self._day:
            self._day = trepo.today_iso()
            self._changed()

    # ---- loading

    def _reload_categories(self) -> None:
        self.category_filter.blockSignals(True)
        current = self.category_filter.currentData()
        self.category_filter.clear()
        self.category_filter.addItem("Todas las categorías", None)
        for c in trepo.list_categories(self.conn):
            self.category_filter.addItem(c.name, c.id)
        idx = self.category_filter.findData(current)
        self.category_filter.setCurrentIndex(max(idx, 0))
        self.category_filter.blockSignals(False)

    def _visible(self, todos: list[Todo], today: str) -> dict[str, list[Todo]]:
        cat = self.category_filter.currentData()
        needle = self.search_edit.text().strip().lower()
        only_open = self.status_filter.currentData() == _FILTER_OPEN
        groups: dict[str, list[Todo]] = {k: [] for k, _ in _SECTIONS}
        for t in todos:
            if cat is not None and t.category_id != cat:
                continue
            if needle and needle not in t.title.lower() and not any(needle in s.title.lower() for s in t.subtasks):
                continue
            planned = t.planned_date or today
            if t.is_open:
                key = "today" if planned == today else "carried" if planned < today else "upcoming"
            elif t.status == "done":
                if only_open and trepo.local_date_of(t.completed_at) != today:
                    continue
                key = "done"
            else:
                if only_open:
                    continue
                key = "dropped"
            groups[key].append(t)
        order = {"high": 0, "medium": 1, "low": 2}
        for items in groups.values():
            items.sort(key=lambda t: (t.planned_date or "", order[t.priority], t.id))
        return groups

    def reload(self) -> None:
        today = trepo.today_iso()
        todos = trepo.list_todos(self.conn)
        groups = self._visible(todos, today)
        expanded = {
            self.tree.topLevelItem(i).data(0, _ROLE): self.tree.topLevelItem(i).isExpanded()
            for i in range(self.tree.topLevelItemCount())
        }
        self._loading = True
        self.tree.clear()
        bold = QFont()
        bold.setBold(True)
        for key, label in _SECTIONS:
            items = groups[key]
            if not items:
                continue
            sec = QTreeWidgetItem(self.tree, [f"{label} ({len(items)})"])
            sec.setFont(0, bold)
            sec.setFlags(Qt.ItemFlag.ItemIsEnabled)
            sec.setData(0, _ROLE, key)
            for t in items:
                self._add_todo_item(sec, t, today)
            sec.setExpanded(expanded.get(key, key in ("today", "carried")))
        self._loading = False

    def _add_todo_item(self, parent: QTreeWidgetItem, t: Todo, today: str) -> None:
        parts = [_PRIO_MARK[t.priority] + t.title]
        if t.category_name:
            parts.append(f"[{t.category_name}]")
        if t.subtasks:
            parts.append(f"{t.subtasks_done}/{len(t.subtasks)}")
        if t.status == "in_progress":
            parts.append("· en curso")
        if t.due_date:
            parts.append(f"· vence {t.due_date}")
        if t.is_open and (t.planned_date or today) < today:
            parts.append(f"· desde {t.planned_date}")
        item = QTreeWidgetItem(parent, ["  ".join(parts)])
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Checked if t.status == "done" else Qt.CheckState.Unchecked)
        item.setData(0, _ROLE, ("todo", t.id))
        if t.category_color:
            item.setForeground(0, QBrush(QColor(t.category_color)))
        if t.status in ("done", "dropped"):
            font = item.font(0)
            font.setStrikeOut(True)
            item.setFont(0, font)
        if t.due_date and t.is_open and t.due_date < today:
            item.setForeground(0, QBrush(QColor("#ef4444")))
        if t.description.strip():
            item.setToolTip(0, t.description.strip())
        for s in t.subtasks:
            sub = QTreeWidgetItem(item, [s.title])
            sub.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
            sub.setCheckState(0, Qt.CheckState.Checked if s.done else Qt.CheckState.Unchecked)
            sub.setData(0, _ROLE, ("sub", s.id))

    # ---- persistence + export

    def _changed(self) -> None:
        self.reload()
        self.export()

    def export(self) -> None:
        """Keeps todos/current.md in sync so Claude can read the pending list.
        A failed write must never break the UI."""
        try:
            todo_export.write_export(trepo.list_todos(self.conn), trepo.today_iso())
        except OSError:
            log.exception("could not write TODO export")

    # ---- actions

    def _quick_add(self) -> None:
        title = self.quick_edit.text().strip()
        if not title:
            return
        trepo.create_todo(self.conn, title=title)
        self.quick_edit.clear()
        self._changed()

    def _open_wizard(self, todo: Todo | None = None) -> None:
        dlg = TodoWizard(self.conn, todo if isinstance(todo, Todo) else None, self)
        if dlg.exec() != TodoWizard.DialogCode.Accepted:
            return
        data = dlg.result_data()
        if isinstance(todo, Todo):
            trepo.update_todo(self.conn, todo.id, **data)
        else:
            trepo.create_todo(self.conn, **data)
        self._reload_categories()
        self._changed()

    def _on_item_changed(self, item: QTreeWidgetItem, _col: int) -> None:
        if self._loading:
            return
        data = item.data(0, _ROLE)
        if not isinstance(data, tuple):
            return
        checked = item.checkState(0) == Qt.CheckState.Checked
        if data[0] == "sub":
            trepo.set_subtask_done(self.conn, data[1], checked)
        else:
            trepo.update_todo(self.conn, data[1], status="done" if checked else "pending")
        # Defer the rebuild: clearing the tree inside its own itemChanged signal is unsafe.
        QTimer.singleShot(0, self._changed)

    def _update_delete_enabled(self) -> None:
        item = self.tree.currentItem()
        data = item.data(0, _ROLE) if item else None
        self.delete_button.setEnabled(isinstance(data, tuple))

    def _delete_selected(self) -> None:
        item = self.tree.currentItem()
        data = item.data(0, _ROLE) if item else None
        if not isinstance(data, tuple):
            return
        if data[0] == "sub":
            if QMessageBox.question(self, "Eliminar subtarea", f"¿Eliminar la subtarea «{item.text(0)}»?") != QMessageBox.StandardButton.Yes:
                return
            trepo.delete_subtask(self.conn, data[1])
        else:
            if QMessageBox.question(self, "Eliminar TODO", "¿Eliminar este TODO y sus subtareas?") != QMessageBox.StandardButton.Yes:
                return
            trepo.delete_todo(self.conn, data[1])
        self._changed()

    def _selected_todo_id(self, item: QTreeWidgetItem | None) -> int | None:
        while item is not None:
            data = item.data(0, _ROLE)
            if isinstance(data, tuple) and data[0] == "todo":
                return data[1]
            item = item.parent()
        return None

    def _on_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        todo_id = self._selected_todo_id(item)
        if todo_id is not None:
            todo = trepo.get_todo(self.conn, todo_id)
            if todo:
                self._open_wizard(todo)

    def _context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        todo_id = self._selected_todo_id(item)
        if todo_id is None:
            return
        self.tree.setCurrentItem(item)
        data = item.data(0, _ROLE)
        if data[0] == "sub":
            menu = QMenu(self)
            delete_action = menu.addAction("Eliminar subtarea")
            if menu.exec(self.tree.viewport().mapToGlobal(pos)) is delete_action:
                self._delete_selected()
            return
        menu = QMenu(self)
        actions = {
            menu.addAction("Editar…"): "edit",
            menu.addAction("Marcar en curso"): "in_progress",
            menu.addAction("Marcar pendiente"): "pending",
            menu.addAction("Marcar hecho"): "done",
            menu.addAction("Descartar"): "dropped",
            menu.addAction("Mover a hoy"): "today",
            menu.addAction("Eliminar"): "delete",
        }
        chosen = actions.get(menu.exec(self.tree.viewport().mapToGlobal(pos)))
        if chosen is None:
            return
        if chosen == "edit":
            todo = trepo.get_todo(self.conn, todo_id)
            if todo:
                self._open_wizard(todo)
            return
        if chosen == "delete":
            self._delete_selected()
            return
        elif chosen == "today":
            trepo.update_todo(self.conn, todo_id, planned_date=trepo.today_iso())
        else:
            trepo.update_todo(self.conn, todo_id, status=chosen)
        self._changed()
