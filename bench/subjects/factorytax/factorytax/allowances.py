"""Plant-specific allowances (not statutory — plant policy)."""

# Heat allowance: press and welding floor employees get a flat monthly amount
# June-September (stamping floor exceeds 32C midsummer).
HEAT_ALLOWANCE_MONTHLY = 65.0
HEAT_MONTHS = (6, 7, 8, 9)
HEAT_DEPARTMENTS = ("press", "welding")

# Tool allowance: maintenance employees, flat monthly.
TOOL_ALLOWANCE_MONTHLY = 40.0
TOOL_DEPARTMENTS = ("maintenance",)

# Shift meal: any employee on night shift, per-shift flat amount.
MEAL_ALLOWANCE_PER_NIGHT_SHIFT = 4.50


def month_allowances(employee, month, night_shifts):
    """Allowance total for one employee for one month (month = 1-12)."""
    total = 0.0
    if employee.department in HEAT_DEPARTMENTS and month in HEAT_MONTHS:
        total += HEAT_ALLOWANCE_MONTHLY
    if employee.department in TOOL_DEPARTMENTS:
        total += TOOL_ALLOWANCE_MONTHLY
    total += night_shifts * MEAL_ALLOWANCE_PER_NIGHT_SHIFT
    return total
