import unittest
from factorytax.brackets import BRACKETS_2026, tax_for
from factorytax.filings import FILING_BANDS_2026


class TestBrackets(unittest.TestCase):
    def test_filing_bands_match_brackets(self):
        bracket_edges = [(low, high) for low, high, _ in BRACKETS_2026]
        self.assertEqual(bracket_edges, FILING_BANDS_2026)

    def test_below_allowance_pays_nothing(self):
        self.assertEqual(tax_for(2000), 0.0)

    def test_flat_spot(self):
        self.assertAlmostEqual(tax_for(11_925 + 2_450), 11_925 * 0.0055)


if __name__ == "__main__":
    unittest.main()
