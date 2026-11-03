import unittest
from types import SimpleNamespace

from app.api.grn_vendor_templates import apply_temporary_vendor_template, _override_kalyan_unit_cells


class Query:
    def __init__(self, values):
        self.values = values

    def filter_by(self, **kwargs):
        return Query([value for value in self.values if all(getattr(value, key, None) == expected for key, expected in kwargs.items())])

    def all(self):
        return self.values

    def first(self):
        return self.values[0] if self.values else None


class FakeDB:
    def __init__(self):
        self.vendors = [
            SimpleNamespace(code="VND-015", name="Shri Hari Electrical"),
            SimpleNamespace(code="VND-011", name="K P Mat House"),
            SimpleNamespace(code="VND-012", name="Ideal Office Needs"),
            SimpleNamespace(code="VND-013", name="Eco care solutions"),
        ]
        self.items = []

    def query(self, model):
        return Query(self.vendors if model.__name__ == "VendorModel" else self.items)


class TemporaryVendorTemplateTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()

    def result(self, rows=None):
        return {"fields": {}, "line_items": rows or [], "warnings": []}

    def test_shri_hari_uses_directory_vendor_and_includes_carting_charge(self):
        result = self.result([{"item_name": "1 15 W LED FITTING", "recd_qty": 2, "rate": 320, "line_amount": 640}])
        text = "SHRI HARI ELECTRIC\nCARTING (18%)\n150.00"
        output = apply_temporary_vendor_template(result, text, self.db)
        self.assertEqual(output["fields"]["vendor_code"], "VND-015")
        self.assertEqual(output["line_items"][0]["item_name"], "15 W LED FITTING")
        charge = output["line_items"][1]
        self.assertTrue(charge["is_charge_line"])
        self.assertEqual(charge["line_amount"], 150)
        self.assertIsNone(charge["recd_qty"])
        self.assertIsNone(charge["rate"])

    def test_shri_hari_removes_serial_joined_to_36w_cfl_description(self):
        result = self.result([
            {"item_name": "1 15 W LED FITTING", "recd_qty": 2, "rate": 320},
            {"item_name": "236 W CFL", "recd_qty": 1, "rate": 180},
        ])
        output = apply_temporary_vendor_template(result, "SHRI HARI ELECTRIC", self.db)
        self.assertEqual(output["line_items"][0]["item_name"], "15 W LED FITTING")
        self.assertEqual(output["line_items"][1]["item_name"], "36 W CFL")

    def test_kalyan_keeps_vendor_creation_flow_and_marks_unreadable_rate(self):
        result = self.result([
            {"item_name": "COLLAPSIBLE WASTEPIPE", "rate": None},
            {"item_name": "PVC WALL PLUGS", "recd_qty": 1, "rate": 2, "line_amount": 2},
        ])
        result["fields"]["invoice_no"] = "468"
        output = apply_temporary_vendor_template(
            result, "KALYAN HARDWARE\\nGSTIN 24ACYPP9230H1Z2\\n25/07/2026", self.db
        )
        self.assertEqual(output["line_items"][0]["rate"], 60.0)
        row = output["line_items"][1]
        self.assertIsNone(row["rate"])
        self.assertTrue(row["rate_unreadable"])
        self.assertEqual(row["extraction_warning"], "Warning - The rate for this line item is unreadable.")
        self.assertNotIn("vendor_code", output["fields"])
        self.assertEqual(output["fields"]["vendor_gst_no"], "24ACYPP9230H1Z2")

    def test_ecs_vendor_is_resolved_from_directory_and_description_is_normalized(self):
        result = self.result([{"item_name": "ECS LOSTION HAND WASH 5Ltr", "recd_qty": 6, "rate": 550}])
        output = apply_temporary_vendor_template(result, "EcoCare Solutions\nGSTIN 24BFWPS4186R2Z3", self.db)
        self.assertEqual(output["fields"]["vendor_code"], "VND-013")
        self.assertEqual(output["line_items"][0]["item_name"], "ECS Lotion Hand Wash 5Ltr")

    def test_ideal_office_and_kp_mat_vendor_codes_are_applied(self):
        ideal = apply_temporary_vendor_template(self.result(), "IDEAL OFFICE NEEDS\nGSTIN 24EOTPR7394K1ZS", self.db)
        kp = apply_temporary_vendor_template(self.result(), "K P MAT HOUSE\nGSTIN 24AAEFK4814G1ZM", self.db)
        self.assertEqual(ideal["fields"]["vendor_code"], "VND-012")
        self.assertEqual(kp["fields"]["vendor_code"], "VND-011")
        ideal_invoice = apply_temporary_vendor_template(
            self.result(), "IDEAL OFFICE NEEDS\\nInvoice No. IDI26-27I0702", self.db
        )
        self.assertEqual(ideal_invoice["fields"]["invoice_no"], "IDI26-27/0702")

    def test_kalyan_preserves_full_size_like_unit_column_value(self):
        import pymupdf

        document = pymupdf.open()
        page = document.new_page(width=620, height=240)
        for x, y, label in [
            (40, 100, "Description"),
            (280, 100, "Unit"),
            (350, 100, "Qty"),
            (430, 100, "Rate"),
        ]:
            page.insert_text((x, y), label, fontsize=9)
        for x, y, value in [
            (55, 130, "SS Nut-Bolt"),
            (290, 130, "WASAR-3/16"),
            (360, 130, "4.00"),
            (440, 130, "15.00"),
        ]:
            page.insert_text((x, y), value, fontsize=9)
        raw = document.tobytes()
        document.close()

        rows = [{"item_name": "SS Nut-Bolt"}]
        _override_kalyan_unit_cells(raw, rows)
        self.assertEqual(rows[0]["uom"], "WASAR-3/16")
        self.assertEqual(rows[0]["unit"], "WASAR-3/16")

    def test_unrecognized_vendor_uses_generic_result_unchanged(self):
        original = self.result([{"item_name": "Generic item"}])
        output = apply_temporary_vendor_template(original, "UNRELATED SUPPLIER", self.db)
        self.assertNotIn("temporary_template", output)
        self.assertEqual(output["line_items"][0]["item_name"], "Generic item")


if __name__ == "__main__":
    unittest.main()
