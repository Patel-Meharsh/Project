import unittest

from app.api._ledger_reference import (
    find_reference_invoice,
    find_kalyan_reference_from_rows,
)


class ReferenceInvoiceMatchTests(unittest.TestCase):
    def test_each_confirmed_invoice_matches_by_labelled_number_without_gstin(self):
        cases = [
            ("GST/7518/26-27", 12),
            ("SHE/0117/26-27", 5),
            ("ECS/367/26-27", 1),
            ("468", 12),
            ("IDI26-27I0702", 24),
        ]
        for invoice_no, expected_rows in cases:
            with self.subTest(invoice_no=invoice_no):
                document_text = (
                    f"Invoice No: {invoice_no}\n"
                    "Buyer: Nintec Systems Limited"
                )
                record = find_reference_invoice(document_text)
                self.assertIsNotNone(record)
                self.assertEqual(record["invoice_no"], invoice_no)
                self.assertEqual(len(record["items"]), expected_rows)

    def test_kalyan_matches_from_at_least_eleven_complete_item_signatures(self):
        reference_rows = [
            ("SS CATORI PLATE", 2, 35.00),
            ("SS NUT-BOLT", 4, 15.00),
            ("WHITE CEMENT", 3, 40.00),
            ("COLLAPSIBLE WASTE PIPE", 2, 60.00),
            ("PIPE CONNECTION", 1, 255.00),
            ("TEFLON TAP", 2, 18.00),
            ("JALARAM PAD&TEN CHAL LOCK", 1, 150.00),
            ("S.S & BRASS WESTCUPLIN", 1, 429.00),
            ("PVC WALL PLUGS", 1, 59.00),
            ("SILICONE ASTRAL", 2, 160.00),
            ("SILICON JADOO-G", 1, 300.00),
            ("M-SEAL", 4, 20.00),
        ]
        rows = [
            {"item_name": name, "recd_qty": qty, "rate": rate}
            for name, qty, rate in reference_rows
        ]
        rows[0]["item_name"] = "SS CATORI PLATE OCR"
        self.assertEqual(
            find_kalyan_reference_from_rows(rows)["vendor_name"],
            "Kalyan Hardware",
        )

    def test_kalyan_does_not_match_when_only_ten_rows_agree(self):
        reference_rows = [
            ("SS CATORI PLATE", 2, 35.00),
            ("SS NUT-BOLT", 4, 15.00),
            ("WHITE CEMENT", 3, 40.00),
            ("COLLAPSIBLE WASTE PIPE", 2, 60.00),
            ("PIPE CONNECTION", 1, 255.00),
            ("TEFLON TAP", 2, 18.00),
            ("JALARAM PAD&TEN CHAL LOCK", 1, 150.00),
            ("S.S & BRASS WESTCUPLIN", 1, 429.00),
            ("PVC WALL PLUGS", 1, 59.00),
            ("SILICONE ASTRAL", 2, 160.00),
            ("SILICON JADOO-G", 1, 300.00),
            ("M-SEAL", 4, 20.00),
        ]
        rows = [
            {"item_name": name, "recd_qty": qty, "rate": rate}
            for name, qty, rate in reference_rows
        ]
        rows[0]["recd_qty"] = 99
        rows[1]["rate"] = 999
        self.assertIsNone(find_kalyan_reference_from_rows(rows))

    def test_does_not_match_without_a_labelled_invoice_number(self):
        document_text = "GST/7518/26-27"
        self.assertIsNone(find_reference_invoice(document_text))

    def test_does_not_match_an_invoice_number_that_is_not_exact(self):
        document_text = "Invoice No: 469"
        self.assertIsNone(find_reference_invoice(document_text))


if __name__ == "__main__":
    unittest.main()
