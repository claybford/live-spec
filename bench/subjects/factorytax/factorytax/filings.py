"""Monthly statutory filing totals.

The filing bands below mirror brackets.BRACKETS_2026 edges. They are stated
separately because the filing form requires banded headcounts and totals per
band, not continuous tax — but the EDGES MUST MATCH the bracket table. A
statutory bracket change must regenerate both in the same commit.
"""

from . import brackets

# Filing bands: (low edge, high edge) — must match BRACKETS_2026.
FILING_BANDS_2026 = [
    (0, 11_925),
    (11_925, 23_850),
    (23_850, 46_094),
    (46_094, 92_188),
    (92_188, 230_470),
    (230_470, None),
]

FILING_BAND_RATE_LABELS = ["0.55%", "1.10%", "2.90%", "4.10%", "6.50%", "7.15%"]


def band_index(annual_taxable):
    t = max(0.0, annual_taxable - brackets.PERSONAL_ALLOWANCE_2026)
    for i, (low, high) in enumerate(FILING_BANDS_2026):
        if high is None or low <= t < high:
            return i
    return len(FILING_BANDS_2026) - 1


def monthly_filing(annual_estimates):
    """-> list of (band_label, headcount, band_total) for the filing form."""
    out = []
    for i, label in enumerate(FILING_BAND_RATE_LABELS):
        members = [(e, t) for e, t in annual_estimates if band_index(t) == i]
        out.append((label, len(members), sum(brackets.tax_for(t) / 12 for _, t in members)))
    return out
