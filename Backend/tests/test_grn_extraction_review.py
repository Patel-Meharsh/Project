import unittest

from app.api.grn_extraction import _extract_item_rows, _mark_row_for_review


class EmptyItemMasterQuery:
    def all(self):
        return []


class EmptyItemMasterDB:
    def query(self, _model):
        return EmptyItemMasterQuery()


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

    def test_text_parser_keeps_incomplete_item_row_for_review(self):
        rows = _extract_item_rows("LED Fitting 2 Nos", EmptyItemMasterDB())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["item_name"], "LED Fitting")
        self.assertEqual(rows[0]["recd_qty"], 2.0)
        self.assertIsNone(rows[0]["rate"])
        self.assertTrue(rows[0]["needs_review"])

    def test_text_parser_does_not_deduplicate_identical_invoice_lines(self):
        text = "LED Fitting 2 Nos 320 640\nLED Fitting 2 Nos 320 640"
        rows = _extract_item_rows(text, EmptyItemMasterDB())
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["item_name"], rows[1]["item_name"])
        self.assertEqual(rows[0]["recd_qty"], rows[1]["recd_qty"])


if __name__ == "__main__":
    unittest.main()
