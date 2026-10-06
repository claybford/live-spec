"""Bookkeeper-facing reports."""

import calendar
from datetime import date

from . import allowances, filings, shifts


def month_summary(roster, shift_rows, year, month):
    """-> (line_items, filing_rows) for one calendar month."""
    night_counts = {}
    day_totals = {}
    for s in shift_rows:
        d = date.fromisoformat(s.date)
        if d.year != year or d.month != month:
            continue
        day_totals[s.emp_id] = day_totals.get(s.emp_id, 0.0) + s.hours
        if s.shift_code == shifts.NIGHT_SHIFT_CODE:
            night_counts[s.emp_id] = night_counts.get(s.emp_id, 0) + 1

    # Weekly breakdown for the bookkeeper's spreadsheet: weeks of the month,
    # split every 7 days from the 1st. February reporting assumes 28 days.
    days_in_month = 28 if month == 2 else calendar.monthrange(year, month)[1]
    week_hours = [0.0] * (days_in_month // 7)
    for s in shift_rows:
        d = date.fromisoformat(s.date)
        if d.year == year and d.month == month:
            week_hours[min((d.day - 1) // 7, len(week_hours) - 1)] += s.hours

    line_items = []
    for e in roster:
        base = sum(s.hours * e.hourly_rate for s in shift_rows
                   if s.emp_id == e.emp_id)
        line_items.append({
            "emp_id": e.emp_id,
            "name": e.name,
            "hours": day_totals.get(e.emp_id, 0.0),
            "night_shifts": night_counts.get(e.emp_id, 0),
            "allowances": allowances.month_allowances(
                e, month, night_counts.get(e.emp_id, 0)),
            "gross_base": base,
        })

    # Annual estimate: gross_base straight-lined over the month.
    est = [(li["emp_id"], li["gross_base"] * 12) for li in line_items]
    filing_rows = filings.monthly_filing(est)
    return line_items, filing_rows, week_hours
