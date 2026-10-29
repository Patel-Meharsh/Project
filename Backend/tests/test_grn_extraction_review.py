import unittest

from app.api.grn_extraction import _mark_row_for_review


class GRNExtractedRowReviewTests(unittest.TestCase):
    def make_row(self, **overrides):
        row = {
            "item_name": "LED Fitting",
            "recd_qty": 2.0,
            "rate": 320.0,
            "line_amount": 640.0,
        }
        row.update(overrides)
        return row

    def test_complete_arithmetically_consistent_row_needs_no_review(self):
        row = _mark_row_for_review(self.make_row())
        self.assertFalse(row["needs_review"])
        self.assertEqual(row["extraction_warning"], "")

    def test_missing_quantity_is_preserved_and_flagged(self):
        row = _mark_row_for_review(self.make_row(recd_qty=None))
        self.assertIsNone(row["recd_qty"])
        self.assertTrue(row["needs_review"])
        self.assertIn("quantity was not confidently read", row["extraction_warning"])

    def test_missing_rate_is_preserved_and_flagged(self):
        row = _mark_row_for_review(self.make_row(rate=None))
        self.assertIsNone(row["rate"])
        self.assertTrue(row["needs_review"])
        self.assertIn("rate was not confidently read", row["extraction_warning"])

    def test_arithmetic_mismatch_is_preserved_and_flagged(self):
        row = _mark_row_for_review(self.make_row(line_amount=700.0))
        self.assertEqual(row["line_amount"], 700.0)
        self.assertTrue(row["needs_review"])
        self.assertIn(
            "quantity × rate differs from the printed line amount",
            row["extraction_warning"],
        )


if __name__ == "__main__":
    unittest.main()
