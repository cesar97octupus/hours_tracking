import unittest
from unittest import mock

from app.timer import MAX_TIMER_SECONDS, Timer


class TestTimer(unittest.TestCase):
    def test_start_stop_elapsed_and_rounding(self):
        timer = Timer(description="d", task_id=1, task_name="T1")
        self.assertFalse(timer.is_running())

        with mock.patch("app.timer.time.monotonic", side_effect=[100.0, 100.0 + 1020]):
            timer.start()
            self.assertTrue(timer.is_running())
            draft = timer.stop()

        self.assertFalse(timer.is_running())
        self.assertAlmostEqual(draft.elapsed_seconds, 1020.0)
        self.assertEqual(draft.unit_amount, 0.5)  # 17 min -> rounds up to 2/4h

    def test_exceeded_max_duration(self):
        timer = Timer(description="d")
        with mock.patch(
            "app.timer.time.monotonic",
            side_effect=[0.0, MAX_TIMER_SECONDS - 1, MAX_TIMER_SECONDS + 1],
        ):
            timer.start()
            self.assertFalse(timer.exceeded_max_duration())
            self.assertTrue(timer.exceeded_max_duration())


if __name__ == "__main__":
    unittest.main()
