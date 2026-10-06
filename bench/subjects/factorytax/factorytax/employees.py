"""Employee records and tax codes."""

from dataclasses import dataclass

# Tax codes used by the plant bookkeeper. A code change mid-year requires a
# new W-4-equivalent form on file; employees.py refuses to apply a new code
# without an effective date.
CODES = ("A", "B", "C", "EXEMPT")


@dataclass
class Employee:
    emp_id: str
    name: str
    tax_code: str
    hourly_rate: float
    department: str          # press | welding | finishing | maintenance
    effective_from: str      # YYYY-MM-DD of current tax code

    def __post_init__(self):
        if self.tax_code not in CODES:
            raise ValueError(f"unknown tax code {self.tax_code!r}")


def load_roster(path):
    """Load the CSV roster into Employee records."""
    import csv
    out = []
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            out.append(Employee(
                emp_id=row["emp_id"],
                name=row["name"],
                tax_code=row["tax_code"],
                hourly_rate=float(row["hourly_rate"]),
                department=row["department"],
                effective_from=row["effective_from"],
            ))
    return out
