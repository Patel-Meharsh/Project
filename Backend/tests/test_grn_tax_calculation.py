"""Regression tests for GRN taxable-value calculations."""
import unittest

from app.api.routes import _grn_line_taxable_value, _grn_net_unit_rate


class GRNTaxCalculationTests(unittest.TestCase):
    def test_percentage_discount_reduces_net_unit_rate(self):
        self.assertAlmostEqual(
            _grn_net_unit_rate({"rate": 40, "discount_pct": 15.25}),
            33.9,
            places=2,
        )

    def test_discounted_accepted_value_uses_net_rate(self):
        self.assertAlmostEqual(
            _grn_line_taxable_value({
                "accepted_qty": 3,
                "rate": 40,
                "discount_pct": 15.25,
            }),
            101.7,
            places=2,
        )

    def test_invoice_charge_uses_its_printed_amount(self):
        self.assertEqual(
            _grn_line_taxable_value({
                "is_charge_line": True,
                "line_amount": 150,
            }),
            150,
        )


if __name__ == "__main__":
    unittest.main()
