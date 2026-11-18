"""Tests for reusable, deterministic document-engine primitives."""
import unittest

from app.document_engine import (
    group_words_into_rows,
    line_item_warnings,
    normalize_alphanumeric,
    rank_candidates,
    rows_to_text,
    score_line_item_rows,
)
from app.document_engine.ocr import _ocr_quality_score
from app.document_engine.pdf import extract_pdf_text_sources
from fastapi import HTTPException


class DocumentEngineTests(unittest.TestCase):
    def test_normalization_is_stable_for_ocr_text(self):
        self.assertEqual(normalize_alphanumeric("CHOWNK PL"), "chownkpl")

    def test_candidate_ranking_prefers_closest_catalog_name(self):
        candidates = ["M Fold Napkin", "M Fold Paper", "Floor Cleaner"]
        ranked = rank_candidates(
            "M Fold Nepkin", candidates, name_getter=lambda value: value
        )
        self.assertEqual(ranked[0]["candidate"], "M Fold Napkin")

    def test_candidate_ranking_does_not_return_low_confidence_matches(self):
        ranked = rank_candidates(
            "LED Tube", ["Vendor Address"], name_getter=lambda value: value,
            minimum_score=0.75,
        )
        self.assertEqual(ranked, [])

    def test_layout_groups_words_by_y_and_orders_them_by_x(self):
        words = [
            {"text": "100", "x": 90, "y": 20},
            {"text": "LED", "x": 10, "y": 21},
            {"text": "Light", "x": 40, "y": 22},
            {"text": "Qty", "x": 10, "y": 80},
        ]
        rows = group_words_into_rows(words, page_height=1000)
        self.assertEqual(rows_to_text(rows), "LED Light 100\nQty")

    def test_validation_flags_missing_and_inconsistent_values(self):
        self.assertEqual(
            line_item_warnings(2, 50, 100), []
        )
        self.assertIn(
            "quantity × rate differs from the printed line amount",
            line_item_warnings(2, 50, 120),
        )
        self.assertIn(
            "quantity was not confidently read",
            line_item_warnings(None, 50, 100),
        )

    def test_row_quality_rewards_arithmetic_consistency(self):
        good = [{"item_name": "LED Light", "recd_qty": 2, "rate": 50, "line_amount": 100}]
        bad = [{"item_name": "LED Light", "recd_qty": 2, "rate": 50, "line_amount": 140}]
        self.assertGreater(score_line_item_rows(good), score_line_item_rows(bad))

    def test_invoice_ocr_quality_rewards_readable_header_and_item_rows(self):
        text = (
            "TAX INVOICE\\nSupplier: Example Electricals\\n"
            "GSTIN 24ABCDE1234F1Z5\\nInvoice No: EX/123/26-27\\n"
            "LED Tube Light 2 PCS 100.00 200.00"
        )
        self.assertGreater(_ocr_quality_score(text), _ocr_quality_score("### ???"))

    def test_invalid_pdf_is_reported_as_a_client_error(self):
        with self.assertRaises(HTTPException) as raised:
            extract_pdf_text_sources(b"not a valid pdf")
        self.assertEqual(raised.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
