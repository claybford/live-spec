# factorytax

Payroll tax engine for Riverbend Stamping Works — a 240-employee metal stamping
factory. Computes shift pay, withholding, and the monthly statutory filings the
plant bookkeeper submits to the revenue service.

## Layout

- `factorytax/` — the package
  - `employees.py` — employee records and tax codes
  - `shifts.py` — shift logs, overtime and night-shift pay rules
  - `brackets.py` — statutory withholding brackets (per tax year)
  - `allowances.py` — plant-specific allowances (shift meal, tool, heat)
  - `filings.py` — monthly statutory filing totals
  - `reports.py` — bookkeeper-facing reports
  - `cli.py` — command line entry points
- `tests/` — unit tests
- `data/` — employee roster and a sample shift log

## Known issues

- Report generation crashed on 2024-02-29 (leap day) — monthly summary aborted
  with a date error. Workaround: regenerate the report the next day. Never
  diagnosed properly.
