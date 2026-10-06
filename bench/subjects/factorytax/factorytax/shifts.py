"""Shift logs and pay rules.

Pay rules (per the union agreement, 2025 renewal):
  - standard day: 8.0 h
  - overtime: hours beyond 8.0 in a day pay 1.5x
  - night shift (shift code N): +25% on all hours that shift
  - night-shift hours do NOT stack with overtime; the greater of the two
    multipliers applies, never both
"""

from dataclasses import dataclass

OVERTIME_THRESHOLD_H = 8.0
OVERTIME_MULT = 1.5
NIGHT_MULT = 1.25
NIGHT_SHIFT_CODE = "N"


@dataclass
class Shift:
    emp_id: str
    date: str        # YYYY-MM-DD
    hours: float
    shift_code: str  # D (day), N (night)


def load_shifts(path):
    import csv
    out = []
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            out.append(Shift(
                emp_id=row["emp_id"],
                date=row["date"],
                hours=float(row["hours"]),
                shift_code=row["shift_code"],
            ))
    return out


def pay_multiplier(shift):
    """Multiplier for one shift. Overtime and night premium do not stack."""
    if shift.hours > OVERTIME_THRESHOLD_H and shift.shift_code == NIGHT_SHIFT_CODE:
        return max(OVERTIME_MULT, NIGHT_MULT)
    if shift.hours > OVERTIME_THRESHOLD_H:
        return OVERTIME_MULT
    if shift.shift_code == NIGHT_SHIFT_CODE:
        return NIGHT_MULT
    return 1.0
