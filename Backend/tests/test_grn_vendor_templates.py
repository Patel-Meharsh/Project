import unittest
from types import SimpleNamespace

from app.api.grn_vendor_templates import apply_temporary_vendor_template


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

    def test_kalyan_keeps_vendor_creation_flow_and_marks_unreadable_rate(self):
        result = self.result([{"item_name": "PVC WALL PLUGS", "recd_qty": 1, "rate": 2, "line_amount": 2}])
        output = apply_temporary_vendor_template(result, "KALYAN HARDWARE\nGSTIN 24ACYPP9230H1Z2", self.db)
        row = output["line_items"][0]
        self.assertIsNone(row["rate"])
        self.assertTrue(row["rate_unreadable"])
        self.assertEqual(row["extraction_warning"], "Warning - The rate for this line item is unreadable.")
        self.assertNotIn("vendor_code", output["fields"])

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

    def test_unrecognized_vendor_uses_generic_result_unchanged(self):
        original = self.result([{"item_name": "Generic item"}])
        output = apply_temporary_vendor_template(original, "UNRELATED SUPPLIER", self.db)
        self.assertNotIn("temporary_template", output)
        self.assertEqual(output["line_items"][0]["item_name"], "Generic item")


if __name__ == "__main__":
    unittest.main()
