"""Statutory withholding brackets, tax year 2026.

IMPORTANT: filings.py derives its filing-band boundaries from the bracket
edges below. If the statute changes these tables, the filing bands in
filings.py MUST be regenerated from this table in the same change — the
bookkeeper submits both and a mismatch triggers a reconciliation letter.
"""

BRACKETS_2026 = [
    # (annual taxable low edge, annual taxable high edge, rate)
    (0, 11_925, 0.0055),
    (11_925, 23_850, 0.0110),
    (23_850, 46_094, 0.0290),
    (46_094, 92_188, 0.0410),
    (92_188, 230_470, 0.0650),
    (230_470, None, 0.0715),
]

PERSONAL_ALLOWANCE_2026 = 2_450.0


def tax_for(annual_taxable):
    """Statutory withholding for one annual taxable amount."""
    t = max(0.0, annual_taxable - PERSONAL_ALLOWANCE_2026)
    due = 0.0
    for low, high, rate in BRACKETS_2026:
        if t <= low:
            break
        span = (min(t, high) if high else t) - low
        due += max(0.0, span) * rate
    return due
