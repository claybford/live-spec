import unittest
from factorytax.shifts import Shift, pay_multiplier


class TestShifts(unittest.TestCase):
    def test_plain_day(self):
        self.assertEqual(pay_multiplier(Shift("e1", "2026-03-02", 8.0, "D")), 1.0)

    def test_overtime(self):
        self.assertEqual(pay_multiplier(Shift("e1", "2026-03-02", 10.0, "D")), 1.5)

    def test_night(self):
        self.assertEqual(pay_multiplier(Shift("e1", "2026-03-02", 8.0, "N")), 1.25)

    def test_night_overtime_no_stack(self):
        # Union rule: greater of the two, never both.
        self.assertEqual(pay_multiplier(Shift("e1", "2026-03-02", 10.0, "N")), 1.5)


if __name__ == "__main__":
    unittest.main()
