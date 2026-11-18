"""Tests for reusable, deterministic document-engine primitives."""
import unittest

from app.document_engine import (
    group_words_into_rows,
    line_item_warnings,
    normalize_alphanumeric,
    rank_candidates,
    rows_to_text,
    score_line_item_rows,
    choose_rate_amount,
    extract_table_body_lines,
    normalize_ocr_numeric_text,
    merge_invoice_continuation_lines,
)
from app.document_engine.ocr import _ocr_quality_score, _tesseract_data_to_text
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

    def test_tesseract_tsv_text_reconstruction_preserves_visual_lines(self):
        data = {
            "text": ["LED", "Tube", "2", "PCS"],
            "block_num": [1, 1, 1, 1],
            "par_num": [1, 1, 1, 1],
            "line_num": [1, 1, 2, 2],
            "left": [10, 40, 10, 20],
        }
        self.assertEqual(_tesseract_data_to_text(data), "LED Tube\n2 PCS")

    def test_invoice_ocr_quality_rewards_readable_header_and_item_rows(self):
        text = (
            "TAX INVOICE\nSupplier: Example Electricals\n"
            "GSTIN 24ABCDE1234F1Z5\nInvoice No: EX/123/26-27\n"
            "LED Tube Light 2 PCS 100.00 200.00"
        )
        self.assertGreater(_ocr_quality_score(text), _ocr_quality_score("### ???"))

    def test_row_quality_penalizes_footer_text_as_a_product(self):
        real = [{
            "item_name": "Toilet Brush", "recd_qty": 1,
            "rate": 29, "line_amount": 29,
        }]
        footer = [{
            "item_name": "HDFC Bank Account IFSC Branch", "recd_qty": 1,
            "rate": 29, "line_amount": 29,
        }]
        self.assertGreater(score_line_item_rows(real), score_line_item_rows(footer))

    def test_table_region_stops_before_tax_and_footer(self):
        text = (
            "Supplier: Example\n"
            "Sl No Description of Goods HSN/SAC GST Quantity Rate Amount\n"
            "1 LED Tube 9405 18% 2 PCS 50.00 100.00\n"
            "2 Switch 8536 18% 1 PCS 30.00 30.00\n"
            "Subtotal 130.00\n"
            "CGST 11.70\n"
            "Bank Details HDFC Bank\n"
            "Drug License No GJ-12345"
        )
        rows = extract_table_body_lines(text)
        self.assertEqual(len(rows), 2)
        self.assertIn("LED Tube", rows[0])
        self.assertNotIn("Bank Details", "\\n".join(rows))

    def test_table_header_with_missing_first_character_is_detected(self):
        text = (
            "escription of Goods HSN/SAC GST Quantity Rate Amount\n"
            "1 Soap 3924 18% 2 NO 15.00 30.00\n"
            "Total 30.00"
        )
        rows = extract_table_body_lines(text)
        self.assertEqual(len(rows), 1)
        self.assertIn("Soap", rows[0])

    def test_wrapped_description_stays_with_the_previous_numbered_row(self):
        lines = [
            "5 Godrej AerSpray 33074900 18% 5 BTL 76.27 BTL 381.35",
            "Mogra",
            ": | | |",
            "| | |",
            "6 Godrej AerPocket 33074900 18% 5 NO 50.00 NO 250.00",
            "Lemon",
            "| | F",
            "7 Soft Broom Special 96031000 0% 1 NO 49.00 NO 49.00",
        ]
        merged = merge_invoice_continuation_lines(lines, r"(?:BTL|PKT|NO)")
        self.assertIn("Mogra", merged[0])
        self.assertIn("Godrej AerPocket", merged[1])
        self.assertIn("Lemon", merged[1])
        self.assertIn("Soft Broom", merged[2])
        self.assertEqual(len(merged), 3)

    def test_numeric_ocr_cleanup_and_arithmetic_pair_selection(self):
        self.assertEqual(normalize_ocr_numeric_text("49.S0 29:00 1O5.00"), "49.50 29.00 105.00")
        self.assertEqual(choose_rate_amount([2.0, 29.0], 1.0), (2.0, 29.0))
        # Preserve the OCR evidence if arithmetic cannot distinguish a candidate.
        self.assertEqual(choose_rate_amount([50.0, 280.0], 5.0), (50.0, 280.0))

    def test_invalid_pdf_is_reported_as_a_client_error(self):
        with self.assertRaises(HTTPException) as raised:
            extract_pdf_text_sources(b"not a valid pdf")
        self.assertEqual(raised.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
