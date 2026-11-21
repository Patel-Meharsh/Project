"""Regression tests for generic GRN extraction candidate handling.

Run from Backend with: python -m unittest discover -s tests -v
"""
import io
import os
import unittest

import pymupdf
from pathlib import Path

# The extraction helpers do not connect to the database during import. Supply
# harmless test settings so importing the FastAPI module does not need a local .env.
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "grn-extraction-unit-tests")

from app.api.grn_extraction import (  # noqa: E402
    _choose_line_item_candidate,
    _clean_item_description,
    _mark_row_for_review,
    _pdf_pages_needing_image_fallback,
    _is_charge_line_description,
    _extract_pdf_table_line_items,
)


def row(name, qty=1, rate=10, amount=10, **extra):
    value = {
        "item_name": name,
        "recd_qty": qty,
        "rate": rate,
        "line_amount": amount,
        "needs_review": False,
    }
    value.update(extra)
    return value


class _EmptyQuery:
    def all(self):
        return []


class _EmptyItemDB:
    def query(self, model):
        return _EmptyQuery()


class GRNExtractionCandidateTests(unittest.TestCase):
    def test_complete_generic_text_rows_are_not_replaced_by_incomplete_table_rows(self):
        generic = [row("LED Tube Light", qty=4, rate=125, amount=500)]
        table = [row("LED Tube Light", qty=None, rate=125, amount=500)]
        self.assertIs(_choose_line_item_candidate(generic, table), generic)

    def test_more_complete_table_candidate_is_selected(self):
        generic = [row("Cleaning Liquid", qty=None, rate=85, amount=None)]
        table = [row("Cleaning Liquid", qty=2, rate=85, amount=170)]
        self.assertIs(_choose_line_item_candidate(generic, table), table)

    def test_uncertain_values_are_retained_and_flagged_for_review(self):
        extracted = _mark_row_for_review(row("Washroom Cleaner", qty=None, rate=42, amount=None))
        self.assertEqual(extracted["item_name"], "Washroom Cleaner")
        self.assertIsNone(extracted["recd_qty"])
        self.assertTrue(extracted["needs_review"])
        self.assertIn("quantity was not confidently read", extracted["extraction_warning"])

    def test_serial_prefix_is_removed_without_damaging_product_size(self):
        self.assertEqual(_clean_item_description("2 36W CFL", expected_serial=2), "36W CFL")
        self.assertEqual(_clean_item_description("15 W LED Fitting", expected_serial=15), "15 W LED Fitting")

    def test_scanned_page_is_selected_for_ocr_when_coordinate_rows_are_missing(self):
        coordinate_rows = [
            {"_source_page_index": 0, "needs_review": False, "item_name": "Paper"},
        ]
        self.assertEqual(
            _pdf_pages_needing_image_fallback(
                page_count=2,
                coordinate_rows=coordinate_rows,
                expected_row_counts={0: 1, 1: 2},
            ),
            [1],
        )

    def test_invoice_charges_are_classified_separately_from_stock_items(self):
        self.assertTrue(_is_charge_line_description("5 CARTING (18%)"))
        self.assertTrue(_is_charge_line_description("Freight charges"))
        self.assertFalse(_is_charge_line_description("LED Bulb 15W"))

    def test_charge_line_does_not_require_stock_quantity_or_rate(self):
        charge = _mark_row_for_review({
            "item_name": "CARTING",
            "is_charge_line": True,
            "recd_qty": None,
            "rate": None,
            "line_amount": 150,
            "needs_review": True,
        })
        self.assertTrue(charge["is_charge_line"])
        self.assertFalse(charge["needs_review"])
        self.assertEqual(charge["extraction_warning"], "")

    def test_digital_pdf_table_extracts_hsn_gst_discount_and_taxable_amount(self):
        document = pymupdf.open()
        page = document.new_page(width=800, height=360)
        header = [
            (40, 100, "Description"),
            (190, 100, "HSN/SAC"),
            (265, 100, "GST"),
            (330, 100, "Quantity"),
            (410, 100, "Rate"),
            (480, 100, "D%"),
            (550, 100, "Amount"),
            (650, 100, "Value"),
            (685, 100, "Supply"),
        ]
        values = [
            (40, 140, "Cleaning Liquid"),
            (190, 140, "3402"),
            (265, 140, "18%"),
            (330, 140, "2 NOS"),
            (410, 140, "100.00"),
            (480, 140, "10.00"),
            (550, 140, "180.00"),
            (650, 140, "212.40"),
        ]
        for x, y, text in header + values:
            page.insert_text((x, y), text, fontsize=10)
        raw = document.tobytes()
        document.close()

        rows = _extract_pdf_table_line_items(raw, _EmptyItemDB())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["item_name"], "Cleaning Liquid")
        self.assertEqual(rows[0]["hsn"], "3402")
        self.assertEqual(rows[0]["gst_pct"], 18)
        self.assertEqual(rows[0]["discount_pct"], 10)
        self.assertEqual(rows[0]["line_amount"], 180)
        self.assertEqual(rows[0]["value_of_supply"], 212.4)
        self.assertFalse(rows[0]["needs_review"])

    def test_sample_specific_overrides_are_not_in_the_runtime_pipeline(self):
        backend_dir = Path(__file__).resolve().parents[1]
        extraction_source = (backend_dir / "app" / "api" / "grn_extraction.py").read_text(encoding="utf-8")
        self.assertNotIn("grn_predefined_invoices", extraction_source)
        self.assertNotIn("grn_vendor_templates", extraction_source)
        self.assertNotIn("predefined_invoice", extraction_source)


if __name__ == "__main__":
    unittest.main()
