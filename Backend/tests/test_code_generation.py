import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app import models
from app.api.routes import next_code, _next_grn_no


class CodeGenerationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(
            self.engine,
            tables=[
                models.ItemModel.__table__,
                models.VendorModel.__table__,
                models.CodeReservationModel.__table__,
                models.GRNModel.__table__,
                models.GRNSequenceModel.__table__,
            ],
        )
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.db.add(models.GRNSequenceModel(id=1, last_number=0))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_item_code_uses_requested_category_prefix_and_existing_maximum(self):
        self.db.add_all([
            models.ItemModel(code="EM-001", name="Light"),
            models.ItemModel(code="EM-004", name="Cable"),
        ])
        self.db.commit()

        result = next_code("item", "EM", self.db, None)

        self.assertEqual(result["code"], "EM-005")

    def test_generated_code_is_reserved_and_next_request_advances(self):
        first = next_code("item", "CL", self.db, None)
        second = next_code("item", "CL", self.db, None)

        self.assertEqual(first["code"], "CL-001")
        self.assertEqual(second["code"], "CL-002")
        self.assertEqual(
            self.db.query(models.CodeReservationModel).filter_by(prefix="CL-").count(),
            2,
        )


    def test_item_sequence_restarts_at_001_when_prefix_has_no_items(self):
        self.db.add_all([
            models.CodeReservationModel(code="W-001", entity="item", prefix="W-"),
            models.CodeReservationModel(code="W-002", entity="item", prefix="W-"),
            models.CodeReservationModel(code="W-003", entity="item", prefix="W-"),
            models.CodeReservationModel(code="W-004", entity="item", prefix="W-"),
            models.CodeReservationModel(code="VND-030", entity="vendor", prefix="VND-"),
        ])
        self.db.commit()

        result = next_code("item", "W", self.db, None)

        self.assertEqual(result["code"], "W-001")
        self.assertEqual(
            self.db.query(models.CodeReservationModel).filter_by(entity="item", prefix="W-").count(),
            1,
        )
        self.assertEqual(
            self.db.query(models.CodeReservationModel).filter_by(code="VND-030").count(),
            1,
        )

    def test_new_item_reservations_are_not_cleared_while_no_items_exist(self):
        first = next_code("item", "CL", self.db, None)
        second = next_code("item", "CL", self.db, None)

        self.assertEqual(first["code"], "CL-001")
        self.assertEqual(second["code"], "CL-002")

    def test_item_sequence_continues_after_highest_existing_item(self):
        self.db.add_all([
            models.ItemModel(code="W-001", name="Cable"),
            models.CodeReservationModel(code="W-001", entity="item", prefix="W-"),
            models.CodeReservationModel(code="W-002", entity="item", prefix="W-"),
        ])
        self.db.commit()

        result = next_code("item", "W", self.db, None)

        self.assertEqual(result["code"], "W-003")

    def test_vendor_codes_keep_vendor_prefix(self):
        result = next_code("vendor", None, self.db, None)
        self.assertEqual(result["code"], "VND-001")


    def test_grn_counter_advances_only_with_committed_save(self):
        sequence = self.db.query(models.GRNSequenceModel).filter_by(id=1).first()
        sequence.last_number = 4
        self.db.commit()

        allocated = _next_grn_no(self.db)
        self.assertEqual(allocated, "GRN-005")

        # A cancelled/failed save rolls back the counter update.
        self.db.rollback()
        sequence = self.db.query(models.GRNSequenceModel).filter_by(id=1).first()
        self.assertEqual(sequence.last_number, 4)

        self.assertEqual(_next_grn_no(self.db), "GRN-005")
        self.db.commit()

    def test_grn_counter_does_not_reuse_number_after_grn_deletion(self):
        self.db.add(models.GRNModel(grn_no="GRN-004"))
        sequence = self.db.query(models.GRNSequenceModel).filter_by(id=1).first()
        sequence.last_number = 4
        self.db.commit()

        self.assertEqual(_next_grn_no(self.db), "GRN-005")
        self.db.commit()

        self.db.query(models.GRNModel).filter_by(grn_no="GRN-004").delete()
        self.db.commit()
        self.assertEqual(_next_grn_no(self.db), "GRN-006")
        self.db.commit()

    def test_grn_number_cannot_be_preallocated_through_next_code(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as error:
            next_code("grn", None, self.db, None)
        self.assertEqual(error.exception.status_code, 400)

    def test_unknown_entity_is_rejected(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as error:
            next_code("unknown", None, self.db, None)
        self.assertEqual(error.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
