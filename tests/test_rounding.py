import unittest

from app.rounding import round_up_to_quarter_hour


class TestRoundUpToQuarterHour(unittest.TestCase):
    def test_cases(self):
        cases = [
            (0, 0.0),
            (1, 0.25),
            (899, 0.25),
            (900, 0.25),
            (901, 0.5),
            (3600, 1.0),
            (25200, 7.0),
        ]
        for seconds, expected in cases:
            with self.subTest(seconds=seconds):
                self.assertEqual(round_up_to_quarter_hour(seconds), expected)

    def test_negative(self):
        self.assertEqual(round_up_to_quarter_hour(-5), 0.0)


if __name__ == "__main__":
    unittest.main()
