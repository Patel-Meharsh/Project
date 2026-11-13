import unittest

from app.api._ledger_reference import find_reference_invoice


class ReferenceInvoiceMatchTests(unittest.TestCase):
    def test_each_confirmed_invoice_matches_by_labelled_number_without_gstin(self):
        cases = [
            ("24AAEFK4814G1ZM", "GST/7518/26-27", 12),
            ("24AKKPB1553H1ZJ", "SHE/0117/26-27", 5),
            ("24BFWPS4186R2Z3", "ECS/367/26-27", 1),
            ("24ACYPP9230H1Z2", "468", 12),
            ("24EOTPR7394K1ZS", "IDI26-27I0702", 24),
        ]
        for gstin, invoice_no, expected_rows in cases:
            with self.subTest(invoice_no=invoice_no):
                document_text = (
                    f"Invoice No: {invoice_no}\n"
                    "Buyer: Nintec Systems Limited"
                )
                record = find_reference_invoice(document_text)
                self.assertIsNotNone(record)
                self.assertEqual(record["invoice_no"], invoice_no)
                self.assertEqual(len(record["items"]), expected_rows)

    def test_does_not_match_without_a_labelled_invoice_number(self):
        document_text = "GST/7518/26-27"
        self.assertIsNone(find_reference_invoice(document_text))

    def test_does_not_match_an_invoice_number_that_is_not_exact(self):
        document_text = "Invoice No: 469"
        self.assertIsNone(find_reference_invoice(document_text))


if __name__ == "__main__":
    unittest.main()
