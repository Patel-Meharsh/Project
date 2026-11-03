import unittest
from types import SimpleNamespace

import pymupdf

from app.api.grn_predefined_invoices import PREDEFINED_INVOICES, extract_predefined_invoice


class Query:
    def __init__(self, values):
        self.values = values

    def filter_by(self, **kwargs):
        return Query([
            value for value in self.values
            if all(getattr(value, key, None) == expected for key, expected in kwargs.items())
        ])

    def all(self):
        return self.values

    def first(self):
        return self.values[0] if self.values else None


class FakeDB:
    def __init__(self):
        self.vendors = [
            SimpleNamespace(code="VND-015", name="Shri Hari Electrical", gst_no="24AKKPB1553H1ZJ"),
            SimpleNamespace(code="VND-011", name="K P Mat House", gst_no="24AAEFK4814G1ZM"),
            SimpleNamespace(code="VND-012", name="Ideal Office Needs", gst_no="24EOTPR7394K1ZS"),
            SimpleNamespace(code="VND-013", name="Eco care solutions", gst_no="24BFWPS4186R2Z3"),
        ]

    def query(self, model):
        return Query(self.vendors if model.__name__ == "VendorModel" else [])


class PredefinedInvoiceTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()

    def make_pdf(self, text):
        document = pymupdf.open()
        page = document.new_page()
        page.insert_text((40, 60), text, fontsize=12)
        raw = document.tobytes()
        document.close()
        return raw

    def test_all_five_exact_invoice_templates_return_fixed_rows(self):
        cases = [
            ("shri_hari_electric", "SHRI HARI ELECTRIC Invoice No SHE/0117/26-27", 4, "SHE/0117/26-27"),
            ("ideal_office_needs", "IDEAL OFFICE NEEDS Invoice No IDI26-27I0702", 24, "IDI26-27/0702"),
            ("eco_care_solutions", "ECO CARE SOLUTIONS Invoice No ECS/367/26-27", 1, "ECS/367/26-27"),
            ("kp_mat_house", "K P MAT HOUSE Invoice No GST/7518/26-27", 12, "GST/7518/26-27"),
            ("kalyan_hardware", "KALYAN HARDWARE Invoice No:468", 12, "468"),
        ]
        for template, invoice_text, expected_count, invoice_no in cases:
            with self.subTest(template=template):
                result = extract_predefined_invoice(self.make_pdf(invoice_text), "application/pdf", self.db)
                self.assertIsNotNone(result)
                self.assertEqual(result["temporary_template"], template)
                self.assertTrue(result["predefined_invoice"])
                self.assertEqual(result["fields"]["invoice_no"], invoice_no)
                self.assertEqual(len(result["line_items"]), expected_count)
                self.assertTrue(all(row["source"] == "predefined_vendor_template" for row in result["line_items"]))

    def test_shri_hari_uses_exact_36w_cfl_and_carting_charge(self):
        result = extract_predefined_invoice(
            self.make_pdf("SHRI HARI ELECTRIC Invoice No SHE/0117/26-27"),
            "application/pdf", self.db,
        )
        cfl = result["line_items"][1]
        self.assertEqual((cfl["item_name"], cfl["recd_qty"], cfl["rate"], cfl["line_amount"]),
                         ("36W CFL", 1.0, 220.0, 220.0))
        self.assertTrue(result["line_items"][-1]["is_charge_line"])
        self.assertEqual(result["line_items"][-1]["line_amount"], 150.0)

    def test_ideal_office_preserves_all_24_rows_and_repeated_lines(self):
        result = extract_predefined_invoice(
            self.make_pdf("IDEAL OFFICE NEEDS Invoice No IDI26-27I0702"),
            "application/pdf", self.db,
        )
        self.assertEqual(len(result["line_items"]), 24)
        self.assertEqual(result["line_items"][0]["item_name"], "M Fold Paper professional")
        self.assertEqual(result["line_items"][11]["item_name"], "M Fold Paper professional")
        self.assertEqual(result["line_items"][13]["item_name"], "M Fold Paper professional")
        self.assertAlmostEqual(sum(row["line_amount"] for row in result["line_items"]), 40470.00, places=2)

    def test_kp_mat_house_values_match_scanned_invoice(self):
        result = extract_predefined_invoice(
            self.make_pdf("K P MAT HOUSE Invoice No GST/7518/26-27"),
            "application/pdf", self.db,
        )
        self.assertEqual(len(result["line_items"]), 12)
        self.assertEqual(
            (result["line_items"][4]["item_name"], result["line_items"][4]["recd_qty"],
             result["line_items"][4]["rate"], result["line_items"][4]["line_amount"]),
            ("Godrej Aer Spray Mogra", 5.0, 76.27, 381.35),
        )
        self.assertAlmostEqual(sum(row["line_amount"] for row in result["line_items"]), 4009.85, places=2)

    def test_kalyan_preserves_unreadable_pvc_rate_and_confirmed_pipe_rate(self):
        result = extract_predefined_invoice(
            self.make_pdf("KALYAN HARDWARE Invoice No:468"),
            "application/pdf", self.db,
        )
        pipe = result["line_items"][3]
        pvc = result["line_items"][8]
        self.assertEqual((pipe["rate"], pipe["line_amount"]), (60.0, 101.70))
        self.assertEqual(pipe["unit"], "WATER PIPE-H")
        self.assertIsNone(pvc["rate"])
        self.assertTrue(pvc["needs_review"])
        self.assertEqual(pvc["line_amount"], 29.50)
        self.assertEqual(pvc["extraction_warning"], "Warning - The rate for this line item is unreadable.")

    def test_unrecognized_invoice_does_not_use_fixed_supplier_data(self):
        result = extract_predefined_invoice(
            self.make_pdf("SHRI HARI ELECTRIC Invoice No SHE/0118/26-27"),
            "application/pdf", self.db,
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
