import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from app import todo_export as export
from app import todo_repository as trepo
from app.db import _migrate


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _migrate(conn)
    return conn


class TestTodos(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()

    def tearDown(self):
        self.conn.close()

    def test_default_categories_seeded(self):
        names = [c.name for c in trepo.list_categories(self.conn)]
        self.assertEqual(names[:4], ["Investigación", "Comunicación", "Análisis", "Desarrollo"])

    def test_create_and_subtasks(self):
        cat = trepo.list_categories(self.conn)[0].id
        tid = trepo.create_todo(
            self.conn, title=" Hacer X ", category_id=cat, subtasks=[("a", False), ("", False), ("b", True)]
        )
        t = trepo.get_todo(self.conn, tid)
        self.assertEqual(t.title, "Hacer X")
        self.assertEqual(t.category_name, "Investigación")
        self.assertEqual([s.title for s in t.subtasks], ["a", "b"])
        self.assertEqual(t.subtasks_done, 1)
        self.assertEqual(t.planned_date, date.today().isoformat())

    def test_blank_title_rejected(self):
        with self.assertRaises(ValueError):
            trepo.create_todo(self.conn, title="  ")

    def test_status_sets_and_clears_completed_at(self):
        tid = trepo.create_todo(self.conn, title="x")
        trepo.update_todo(self.conn, tid, status="done")
        self.assertIsNotNone(trepo.get_todo(self.conn, tid).completed_at)
        trepo.update_todo(self.conn, tid, status="pending")
        self.assertIsNone(trepo.get_todo(self.conn, tid).completed_at)

    def test_update_replaces_subtasks_and_rejects_unknown_field(self):
        tid = trepo.create_todo(self.conn, title="x", subtasks=[("a", False)])
        trepo.update_todo(self.conn, tid, subtasks=[("n1", False), ("n2", False)])
        self.assertEqual(len(trepo.get_todo(self.conn, tid).subtasks), 2)
        with self.assertRaises(ValueError):
            trepo.update_todo(self.conn, tid, bogus=1)

    def test_set_subtask_done_and_cascade_delete(self):
        tid = trepo.create_todo(self.conn, title="x", subtasks=[("a", False)])
        sid = trepo.get_todo(self.conn, tid).subtasks[0].id
        trepo.set_subtask_done(self.conn, sid, True)
        self.assertTrue(trepo.get_todo(self.conn, tid).subtasks[0].done)
        trepo.delete_todo(self.conn, tid)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM todo_subtasks").fetchone()[0], 0)

    def test_delete_single_subtask_keeps_todo(self):
        tid = trepo.create_todo(self.conn, title="x", subtasks=[("a", False), ("b", False)])
        trepo.delete_subtask(self.conn, trepo.get_todo(self.conn, tid).subtasks[0].id)
        t = trepo.get_todo(self.conn, tid)
        self.assertEqual([s.title for s in t.subtasks], ["b"])

    def test_create_category_is_case_insensitive_idempotent(self):
        a = trepo.create_category(self.conn, "Foo")
        b = trepo.create_category(self.conn, "foo")
        self.assertEqual(a, b)

    def test_export_sections(self):
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        trepo.create_todo(self.conn, title="hoy", priority="high", subtasks=[("s", True), ("t", False)])
        trepo.create_todo(self.conn, title="viejo", planned_date=yesterday, due_date=yesterday)
        done = trepo.create_todo(self.conn, title="listo")
        trepo.update_todo(self.conn, done, status="done")
        text = export.render_markdown(trepo.list_todos(self.conn), today)
        self.assertIn("## Pendientes de hoy (1)", text)
        self.assertIn("## Arrastrados de días anteriores (1)", text)
        self.assertIn("## Hechos hoy (1)", text)
        self.assertIn("1/2 subtareas", text)
        self.assertIn("(VENCIDO)", text)
        self.assertIn("- [x] [Sin categoría", text)

    def test_write_export_creates_files(self):
        with tempfile.TemporaryDirectory() as d:
            path = export.write_export(trepo.list_todos(self.conn), "2026-11-10", Path(d))
            self.assertTrue(path.exists())
            self.assertTrue((Path(d) / "2026-11-10.md").exists())

    def test_update_category(self):
        cid = trepo.create_category(self.conn, "Temp")
        trepo.update_category(self.conn, cid, name="Renombrada", color="#112233")
        cat = next(c for c in trepo.list_categories(self.conn) if c.id == cid)
        self.assertEqual((cat.name, cat.color), ("Renombrada", "#112233"))
        with self.assertRaises(ValueError):
            trepo.update_category(self.conn, cid, name="  ")
        with self.assertRaises(ValueError):
            trepo.update_category(self.conn, cid, name="desarrollo")

    def test_delete_category_uncategorizes_todos(self):
        cid = trepo.create_category(self.conn, "Borrable")
        tid = trepo.create_todo(self.conn, title="x", category_id=cid)
        self.assertEqual(trepo.count_category_todos(self.conn, cid), 1)
        trepo.delete_category(self.conn, cid)
        self.assertIsNone(trepo.get_todo(self.conn, tid).category_id)
        self.assertNotIn("Borrable", [c.name for c in trepo.list_categories(self.conn)])


if __name__ == "__main__":
    unittest.main()
