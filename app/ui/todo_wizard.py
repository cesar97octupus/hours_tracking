import sqlite3

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QDateEdit,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app import repository as repo
from app import todo_repository as trepo
from app.dto import Todo

_STEP_TITLES = ("1/3 · Qué", "2/3 · Detalle", "3/3 · Cuándo y enlace")


def _to_qdate(iso: str | None) -> QDate:
    d = QDate.fromString(iso or "", Qt.DateFormat.ISODate)
    return d if d.isValid() else QDate.currentDate()


class TodoWizard(QDialog):
    """3-step wizard to create (or edit, when `todo` is given) a TODO."""

    def __init__(self, conn: sqlite3.Connection, todo: Todo | None = None, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.todo = todo
        self.setWindowTitle("Editar TODO" if todo else "Nuevo TODO")
        self.setMinimumWidth(480)

        # --- step 1: what
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Título del TODO")
        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        self.category_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.category_combo.lineEdit().setPlaceholderText("Elige o escribe una categoría nueva")
        self._categories = trepo.list_categories(conn)
        self.category_combo.addItem("", None)
        for c in self._categories:
            self.category_combo.addItem(c.name, c.id)
        self.priority_combo = QComboBox()
        for key in trepo.PRIORITIES:
            self.priority_combo.addItem(trepo.PRIORITY_LABELS[key], key)
        self.priority_combo.setCurrentIndex(trepo.PRIORITIES.index("medium"))
        self.status_combo = QComboBox()
        for key in trepo.STATUSES:
            self.status_combo.addItem(trepo.STATUS_LABELS[key], key)

        page1 = QWidget()
        f1 = QFormLayout(page1)
        f1.addRow("Título:", self.title_edit)
        f1.addRow("Categoría:", self.category_combo)
        f1.addRow("Prioridad:", self.priority_combo)
        f1.addRow("Estado:", self.status_combo)

        # --- step 2: detail
        self.description_edit = QPlainTextEdit()
        self.description_edit.setPlaceholderText("Descripción (opcional)")
        self.description_edit.setFixedHeight(90)
        self.subtask_list = QListWidget()
        self.subtask_edit = QLineEdit()
        self.subtask_edit.setPlaceholderText("Nueva subtarea y Enter")
        self.subtask_edit.returnPressed.connect(self._add_subtask)
        add_btn = QPushButton("Añadir")
        add_btn.clicked.connect(self._add_subtask)
        remove_btn = QPushButton("Quitar seleccionada")
        remove_btn.clicked.connect(self._remove_subtask)
        sub_row = QHBoxLayout()
        sub_row.addWidget(self.subtask_edit, 1)
        sub_row.addWidget(add_btn)

        page2 = QWidget()
        l2 = QVBoxLayout(page2)
        l2.addWidget(QLabel("Descripción:"))
        l2.addWidget(self.description_edit)
        l2.addWidget(QLabel("Subtareas (marca las ya hechas):"))
        l2.addWidget(self.subtask_list, 1)
        l2.addLayout(sub_row)
        l2.addWidget(remove_btn)

        # --- step 3: when and link
        self.planned_edit = QDateEdit()
        self.planned_edit.setCalendarPopup(True)
        self.planned_edit.setDate(QDate.currentDate())
        self.due_check = QCheckBox("Tiene fecha de vencimiento")
        self.due_edit = QDateEdit()
        self.due_edit.setCalendarPopup(True)
        self.due_edit.setDate(QDate.currentDate())
        self.due_edit.setEnabled(False)
        self.due_check.toggled.connect(self.due_edit.setEnabled)
        self.link_combo = QComboBox()
        self.link_combo.setEditable(True)
        self.link_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.link_combo.addItem("Sin vincular", None)
        for t in repo.list_cached_tasks(conn):
            self.link_combo.addItem(f"Tarea · {t.name}", ("task", t.id, t.name))
        for t in repo.list_cached_tickets(conn):
            self.link_combo.addItem(f"Ticket · {t.name}", ("ticket", t.id, t.name))
        completer = self.link_combo.completer()
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)

        page3 = QWidget()
        f3 = QFormLayout(page3)
        f3.addRow("Día planificado:", self.planned_edit)
        f3.addRow(self.due_check)
        f3.addRow("Vence:", self.due_edit)
        f3.addRow("Vincular a Odoo:", self.link_combo)

        self.stack = QStackedWidget()
        for p in (page1, page2, page3):
            self.stack.addWidget(p)

        self.step_label = QLabel()
        self.step_label.setObjectName("sectionTitle")
        self.error_label = QLabel()
        self.back_btn = QPushButton("Atrás")
        self.back_btn.clicked.connect(lambda: self._go(-1))
        self.next_btn = QPushButton("Siguiente")
        self.next_btn.setObjectName("primaryButton")
        self.next_btn.clicked.connect(self._on_next)
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(cancel_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.back_btn)
        buttons.addWidget(self.next_btn)

        root = QVBoxLayout(self)
        root.addWidget(self.step_label)
        root.addWidget(self.stack, 1)
        root.addWidget(self.error_label)
        root.addLayout(buttons)

        if todo:
            self._populate(todo)
        self._update_nav()
        self.title_edit.setFocus()

    # ---- population / result

    def _populate(self, t: Todo) -> None:
        self.title_edit.setText(t.title)
        idx = self.category_combo.findData(t.category_id)
        self.category_combo.setCurrentIndex(max(idx, 0))
        self.priority_combo.setCurrentIndex(self.priority_combo.findData(t.priority))
        self.status_combo.setCurrentIndex(self.status_combo.findData(t.status))
        self.description_edit.setPlainText(t.description)
        for s in t.subtasks:
            self._append_subtask(s.title, s.done)
        self.planned_edit.setDate(_to_qdate(t.planned_date))
        if t.due_date:
            self.due_check.setChecked(True)
            self.due_edit.setDate(_to_qdate(t.due_date))
        if t.task_id:
            self._select_link(("task", t.task_id, t.task_name), f"Tarea · {t.task_name}")
        elif t.ticket_id:
            self._select_link(("ticket", t.ticket_id, t.ticket_name), f"Ticket · {t.ticket_name}")

    def _select_link(self, data: tuple, label: str) -> None:
        idx = self.link_combo.findData(data)
        if idx < 0:  # no longer in the cache: keep the existing link anyway
            self.link_combo.addItem(label, data)
            idx = self.link_combo.count() - 1
        self.link_combo.setCurrentIndex(idx)

    def _append_subtask(self, title: str, done: bool) -> None:
        item = QListWidgetItem(title)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable)
        item.setCheckState(Qt.CheckState.Checked if done else Qt.CheckState.Unchecked)
        self.subtask_list.addItem(item)

    def _add_subtask(self) -> None:
        text = self.subtask_edit.text().strip()
        if text:
            self._append_subtask(text, False)
            self.subtask_edit.clear()
        self.subtask_edit.setFocus()

    def _remove_subtask(self) -> None:
        for item in self.subtask_list.selectedItems():
            self.subtask_list.takeItem(self.subtask_list.row(item))

    def result_data(self) -> dict:
        """Kwargs for trepo.create_todo / update_todo. Creates the category
        when the user typed a name that doesn't exist yet."""
        cat_text = self.category_combo.currentText().strip()
        category_id = None
        if cat_text:
            idx = self.category_combo.findText(cat_text, Qt.MatchFlag.MatchFixedString)
            category_id = (
                self.category_combo.itemData(idx) if idx >= 0 else trepo.create_category(self.conn, cat_text)
            )
        link = self.link_combo.currentData() if self.link_combo.currentText() != "Sin vincular" else None
        task = link if link and link[0] == "task" else None
        ticket = link if link and link[0] == "ticket" else None
        # A pending subtask typed but not yet added should not be lost.
        pending = self.subtask_edit.text().strip()
        subtasks = [
            (it.text(), it.checkState() == Qt.CheckState.Checked)
            for it in (self.subtask_list.item(i) for i in range(self.subtask_list.count()))
        ]
        if pending:
            subtasks.append((pending, False))
        return dict(
            title=self.title_edit.text().strip(),
            description=self.description_edit.toPlainText().strip(),
            category_id=category_id,
            priority=self.priority_combo.currentData(),
            status=self.status_combo.currentData(),
            planned_date=self.planned_edit.date().toString(Qt.DateFormat.ISODate),
            due_date=self.due_edit.date().toString(Qt.DateFormat.ISODate) if self.due_check.isChecked() else None,
            task_id=task[1] if task else None,
            task_name=task[2] if task else None,
            ticket_id=ticket[1] if ticket else None,
            ticket_name=ticket[2] if ticket else None,
            subtasks=subtasks,
        )

    # ---- navigation

    def _go(self, delta: int) -> None:
        self.stack.setCurrentIndex(self.stack.currentIndex() + delta)
        self._update_nav()

    def _update_nav(self) -> None:
        i = self.stack.currentIndex()
        last = self.stack.count() - 1
        self.step_label.setText(_STEP_TITLES[i])
        self.back_btn.setVisible(i > 0)
        self.next_btn.setText("Guardar" if i == last else "Siguiente")

    def _on_next(self) -> None:
        if self.stack.currentIndex() == 0 and not self.title_edit.text().strip():
            self.error_label.setText("El título es obligatorio.")
            self.title_edit.setFocus()
            return
        self.error_label.clear()
        if self.stack.currentIndex() == self.stack.count() - 1:
            self.accept()
        else:
            self._go(1)
