import unittest

from app.api.grn_extraction import (
    _extract_item_rows,
    _mark_row_for_review,
    _pdf_pages_needing_image_fallback,
    _line_item_quality,
    _choose_pdf_page_rows,
    _append_pdf_description_continuation,
    _invoice_number_from_nearby_label,
    _extract_pdf_table_line_items,
    _extract_fields,
    _clean_item_description,
)


class GRNItemDescriptionCleanupTests(unittest.TestCase):
    def test_removes_explicit_serial_number_from_item_name(self):
        self.assertEqual(_clean_item_description("01. Lizol Floor Cleaner"), "Lizol Floor Cleaner")
        self.assertEqual(_clean_item_description("2) Harpic Toilet Cleaner"), "Harpic Toilet Cleaner")
        self.assertEqual(_clean_item_description("Sr. No. 3 - M Fold Napkin"), "M Fold Napkin")

    def test_preserves_numbers_that_are_part_of_product_names(self):
        self.assertEqual(_clean_item_description("15 W LED Fitting Light"), "15 W LED Fitting Light")
        self.assertEqual(_clean_item_description("2 Ltr White Phenyl"), "2 Ltr White Phenyl")
        self.assertEqual(
            _clean_item_description("15 W LED Fitting Light", expected_serial=1),
            "15 W LED Fitting Light",
        )
        self.assertEqual(
            _clean_item_description("2 Ltr White Phenyl", expected_serial=2),
            "2 Ltr White Phenyl",
        )

    def test_removes_bare_serial_only_when_it_matches_row_sequence(self):
        self.assertEqual(
            _clean_item_description("1 SS CATORI PLATE", expected_serial=1),
            "SS CATORI PLATE",
        )
        self.assertEqual(
            _clean_item_description("2 Harpic Toilet Cleaner", expected_serial=2),
            "Harpic Toilet Cleaner",
        )


class EmptyItemMasterQuery:
    def all(self):
        return []


class EmptyItemMasterDB:
    def query(self, _model):
        return EmptyItemMasterQuery()


class GRNPDFPageFallbackTests(unittest.TestCase):
    def test_mixed_pdf_ocr_only_targets_pages_without_coordinate_rows(self):
        rows = [
            {"item_name": "Digital page item", "_source_page_index": 0},
            {"item_name": "Another digital item", "_source_page_index": 2},
        ]
        self.assertEqual(_pdf_pages_needing_image_fallback(4, rows), [1, 3])

    def test_pdf_page_fallback_respects_max_page_limit(self):
        self.assertEqual(_pdf_pages_needing_image_fallback(35, []), list(range(30)))

    def test_pdf_page_with_uncertain_rows_is_retried_with_ocr(self):
        rows = [
            {"item_name": "Complete item", "_source_page_index": 0, "needs_review": False},
            {"item_name": "Missing rate item", "_source_page_index": 1, "needs_review": True},
        ]
        self.assertEqual(_pdf_pages_needing_image_fallback(3, rows), [1, 2])

    def test_pdf_page_is_retried_when_text_parser_suggests_a_missing_row(self):
        rows = [
            {"item_name": "Item one", "_source_page_index": 0, "needs_review": False},
            {"item_name": "Item two", "_source_page_index": 0, "needs_review": False},
        ]
        self.assertEqual(
            _pdf_pages_needing_image_fallback(
                1, rows, expected_row_counts={0: 3}
            ),
            [0],
        )

    def test_pdf_page_is_not_retried_when_row_counts_agree(self):
        rows = [
            {"item_name": "Item one", "_source_page_index": 0, "needs_review": False},
            {"item_name": "Item two", "_source_page_index": 0, "needs_review": False},
        ]
        self.assertEqual(
            _pdf_pages_needing_image_fallback(
                1, rows, expected_row_counts={0: 2}
            ),
            [],
        )

    def test_quality_prefers_complete_consistent_rows(self):
        complete = [{"item_name": "LED Fitting", "recd_qty": 2, "rate": 320, "line_amount": 640}]
        incomplete = [{"item_name": "LED Fitting", "recd_qty": 2, "rate": None, "line_amount": 640}]
        self.assertGreater(_line_item_quality(complete), _line_item_quality(incomplete))

    def test_pdf_page_uses_better_ocr_candidate(self):
        existing = [{"item_name": "LED Fitting", "recd_qty": 2, "rate": None, "line_amount": 640}]
        candidate = [{"item_name": "LED Fitting", "recd_qty": 2, "rate": 320, "line_amount": 640}]
        self.assertIs(_choose_pdf_page_rows(existing, candidate), candidate)

    def test_pdf_page_keeps_existing_rows_when_ocr_is_worse(self):
        existing = [{"item_name": "LED Fitting", "recd_qty": 2, "rate": 320, "line_amount": 640}]
        candidate = [{"item_name": "LED Fitting", "recd_qty": 2, "rate": None, "line_amount": 640}]
        self.assertIs(_choose_pdf_page_rows(existing, candidate), existing)


class GRNHeaderFallbackTests(unittest.TestCase):
    def test_vendor_name_fallback_ignores_phone_email_and_prefers_business_heading(self):
        text = (
            "TAX INVOICE\\n"
            "Phone: 9876543210\\n"
            "sales@kalyanhardware.in\\n"
            "KALYAN HARDWARE\\n"
            "GSTIN: 24ABCDE1234F1Z5\\n"
            "Invoice No. KH-102"
        )
        result = _extract_fields(text, EmptyItemMasterDB())
        self.assertEqual(result["fields"]["vendor_name"], "KALYAN HARDWARE")
        self.assertEqual(result["fields"]["vendor_code"], "")

    def test_vendor_name_fallback_rejects_ocr_contact_line(self):
        text = (
            "TAX INVOICE\\n"
            "(N): 9825851575. E-matt t Jtuapa\\n"
            "KALYAN HARDWARE\\n"
            "Invoice No. KH-102"
        )
        result = _extract_fields(text, EmptyItemMasterDB())
        self.assertEqual(result["fields"]["vendor_name"], "KALYAN HARDWARE")

    def test_vendor_name_label_does_not_include_contact_details(self):
        text = (
            "Supplier Name: Kalyan Hardware Phone: 9876543210\\n"
            "Email: sales@kalyanhardware.in\\n"
            "Invoice No. KH-102"
        )
        result = _extract_fields(text, EmptyItemMasterDB())
        self.assertEqual(result["fields"]["vendor_name"], "Kalyan Hardware")

    def test_primary_field_extractor_recovers_separated_ecs_style_invoice_number(self):
        text = (
            "Tax Invoice\nInvoice No. (ORIGINAL FOR RECIPIENT)\n"
            "ECS LOTIONS\nECS/26-27/0081\nDated 12-Oct-26"
        )
        result = _extract_fields(text, EmptyItemMasterDB())
        self.assertEqual(result["fields"]["invoice_no"], "ECS/26-27/0081")

    def test_primary_field_extractor_skips_date_after_invoice_label(self):
        text = "Tax Invoice\nInvoice No.\nDate 25/07/2026\n468"
        result = _extract_fields(text, EmptyItemMasterDB())
        self.assertEqual(result["fields"]["invoice_no"], "468")

    def test_invoice_number_is_found_when_separated_from_label_by_other_header_text(self):
        text = "Tax Invoice\nInvoice No. (ORIGINAL FOR RECIPIENT)\nECS LOTIONS\nECS/26-27/0081\nDated 12-Oct-26"
        self.assertEqual(_invoice_number_from_nearby_label(text), "ECS/26-27/0081")

    def test_invoice_number_fallback_does_not_return_date_or_gstin(self):
        text = "Invoice No.\nGSTIN 24ABCDE1234F1Z5\nDated 12-Oct-26"
        self.assertIsNone(_invoice_number_from_nearby_label(text))

    def test_invoice_number_fallback_accepts_short_numeric_invoice_ids(self):
        self.assertEqual(_invoice_number_from_nearby_label("Invoice No. 468\nDate 25/07/2026"), "468")


    def test_invoice_number_fallback_skips_adjacent_date_label(self):
        text = "Invoice No.\nDate 25/07/2026\n468"
        self.assertEqual(_invoice_number_from_nearby_label(text), "468")


class GRNPDFCoordinateIntegrationTests(unittest.TestCase):
    def test_close_invoice_rows_are_not_merged_by_wide_header_columns(self):
        import pymupdf

        document = pymupdf.open()
        page = document.new_page(width=620, height=240)
        for x, y, label in [
            (40, 100, "Description"),
            (210, 107, "HSN/SAC"),
            (285, 103, "GST"),
            (340, 103, "Quantity"),
            (410, 103, "Rate"),
            (500, 103, "Amount"),
            (560, 103, "Value"),
            (560, 108, "Supply"),
        ]:
            page.insert_text((x, y), label, fontsize=9)
        for x, y, value in [
            (40, 130, "1"),
            (55, 130, "SS CATORI PLATE"),
            (210, 130, "9999"),
            (285, 130, "18"),
            (340, 132, "2.00"),
            (410, 132, "35.00"),
            (500, 134, "70.00"),
            (560, 137, "82.60"),
            (40, 141, "2"),
            (55, 141, "SS NUT-BOLT"),
            (210, 141, "8888"),
            (285, 141, "18"),
            (340, 143, "4.00"),
            (410, 143, "15.00"),
            (500, 145, "60.00"),
            (560, 148, "70.80"),
            (500, 190, "Total"),
        ]:
            page.insert_text((x, y), value, fontsize=9)
        raw = document.tobytes()
        document.close()

        rows = _extract_pdf_table_line_items(raw, EmptyItemMasterDB())
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["item_name"], "SS CATORI PLATE")
        self.assertEqual(rows[0]["recd_qty"], 2.0)
        self.assertEqual(rows[1]["item_name"], "SS NUT-BOLT")
        self.assertEqual(rows[1]["recd_qty"], 4.0)


    def test_separate_unit_column_preserves_uncommon_unit_abbreviation(self):
        import pymupdf

        document = pymupdf.open()
        page = document.new_page(width=620, height=240)
        for x, y, label in [
            (40, 100, "Description"),
            (280, 100, "Unit"),
            (350, 100, "Quantity"),
            (430, 100, "Rate"),
            (520, 100, "Amount"),
        ]:
            page.insert_text((x, y), label, fontsize=9)
        for x, y, value in [
            (55, 130, "PVC Pipe"),
            (290, 130, "RFT"),
            (360, 130, "12"),
            (440, 130, "25.00"),
            (520, 130, "300.00"),
        ]:
            page.insert_text((x, y), value, fontsize=9)

        raw = document.tobytes()
        document.close()

        rows = _extract_pdf_table_line_items(raw, EmptyItemMasterDB())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["unit"], "RFT")
        self.assertEqual(rows[0]["recd_qty"], 12.0)

    def test_full_twenty_four_line_invoice_table_keeps_every_goods_row(self):
        import pymupdf

        document = pymupdf.open()
        page = document.new_page(width=620, height=900)
        for x, y, label in [
            (40, 100, "Description"),
            (210, 100, "HSN/SAC"),
            (285, 100, "GST"),
            (340, 100, "Quantity"),
            (410, 100, "Rate"),
            (500, 100, "Amount"),
        ]:
            page.insert_text((x, y), label, fontsize=9)

        for index in range(1, 25):
            y = 125 + index * 25
            name = "Repeated Cleaning Cloth" if index in (4, 19) else f"Cleaning Supply Item {index:02d}"
            for x, value in [
                (40, str(index)),
                (55, name),
                (210, "48181000"),
                (285, "18%"),
                (340, str(index)),
                (410, "10.00"),
                (500, f"{index * 10:.2f}"),
            ]:
                page.insert_text((x, y), value, fontsize=9)

        raw = document.tobytes()
        document.close()

        rows = _extract_pdf_table_line_items(raw, EmptyItemMasterDB())
        self.assertEqual(len(rows), 24)
        self.assertEqual([row["recd_qty"] for row in rows], [float(i) for i in range(1, 25)])
        self.assertEqual(rows[3]["item_name"], "Repeated Cleaning Cloth")
        self.assertEqual(rows[18]["item_name"], "Repeated Cleaning Cloth")
        self.assertEqual(rows[23]["line_amount"], 240.0)

    def test_stacked_header_and_wrapped_description_are_reconstructed(self):
        import pymupdf

        document = pymupdf.open()
        page = document.new_page(width=620, height=260)
        # Simulate a common invoice whose column labels occupy multiple baselines.
        for x, y, label in [
            (40, 100, "Description"),
            (210, 107, "HSN/SAC"),
            (285, 103, "GST"),
            (340, 103, "Quantity"),
            (410, 103, "Rate"),
            (500, 103, "Amount"),
        ]:
            page.insert_text((x, y), label, fontsize=9)
        # First product description wraps, but its numeric columns stay on the first line.
        for x, y, value in [
            (40, 130, "1"),
            (55, 130, "M Fold Paper"),
            (210, 130, "48181000"),
            (285, 130, "18%"),
            (340, 130, "180 PAC"),
            (410, 130, "31.00 PAC"),
            (500, 130, "5580.00"),
            (55, 140, "professional"),
            (40, 165, "2"),
            (55, 165, "Tissue Roll"),
            (210, 165, "48181000"),
            (285, 165, "18%"),
            (340, 165, "100 NOS"),
            (410, 165, "17.00 NOS"),
            (500, 165, "1700.00"),
            (500, 195, "Total"),
        ]:
            page.insert_text((x, y), value, fontsize=9)
        raw = document.tobytes()
        document.close()

        rows = _extract_pdf_table_line_items(raw, EmptyItemMasterDB())
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["item_name"], "M Fold Paper professional")
        self.assertEqual(rows[0]["recd_qty"], 180.0)
        self.assertEqual(rows[0]["rate"], 31.0)
        self.assertEqual(rows[0]["line_amount"], 5580.0)
        self.assertEqual(rows[1]["item_name"], "Tissue Roll")
        self.assertEqual(rows[1]["recd_qty"], 100.0)
        self.assertEqual(rows[1]["rate"], 17.0)


class GRNPDFDescriptionContinuationTests(unittest.TestCase):
    def test_description_only_line_is_appended_to_previous_item_on_same_page(self):
        rows = [{
            "item_name": "M Fold Paper",
            "_source_page_index": 0,
            "recd_qty": 180,
            "rate": 31,
            "line_amount": 5580,
        }]
        self.assertTrue(_append_pdf_description_continuation(rows, "professional", 0))
        self.assertEqual(rows[0]["item_name"], "M Fold Paper professional")

    def test_continuation_does_not_cross_page_boundaries(self):
        rows = [{"item_name": "Tissue Roll", "_source_page_index": 0}]
        self.assertFalse(_append_pdf_description_continuation(rows, "Plain", 1))
        self.assertEqual(rows[0]["item_name"], "Tissue Roll")

    def test_total_and_header_text_are_not_appended_as_descriptions(self):
        rows = [{"item_name": "LED Fitting", "_source_page_index": 0}]
        self.assertFalse(_append_pdf_description_continuation(rows, "Grand Total", 0))
        self.assertEqual(rows[0]["item_name"], "LED Fitting")


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

    def test_hsn_like_quantity_is_withheld_when_amount_proves_column_shift(self):
        row = _mark_row_for_review(
            self.make_row(recd_qty=9405.0, rate=320.0, line_amount=640.0)
        )
        self.assertIsNone(row["recd_qty"])
        self.assertTrue(row["needs_review"])
        self.assertIn("9405", row["extraction_warning"])
        self.assertIn("HSN/SAC", row["extraction_warning"])

    def test_large_quantity_is_kept_when_line_arithmetic_supports_it(self):
        row = _mark_row_for_review(
            self.make_row(recd_qty=1000.0, rate=1.0, line_amount=1000.0)
        )
        self.assertEqual(row["recd_qty"], 1000.0)
        self.assertFalse(row["needs_review"])

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

    def test_text_parser_preserves_arithmetic_mismatch_for_review(self):
        rows = _extract_item_rows("LED Fitting 2 Nos 320 700", EmptyItemMasterDB())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["rate"], 320.0)
        self.assertEqual(rows[0]["line_amount"], 700.0)
        self.assertTrue(rows[0]["needs_review"])
        self.assertIn("quantity × rate differs from the printed line amount", rows[0]["extraction_warning"])


if __name__ == "__main__":
    unittest.main()
