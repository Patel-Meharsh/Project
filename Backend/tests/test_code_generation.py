import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app import models
from app.api.routes import next_code


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
            ],
        )
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

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

    def test_vendor_codes_keep_vendor_prefix(self):
        result = next_code("vendor", None, self.db, None)
        self.assertEqual(result["code"], "VND-001")

    def test_unknown_entity_is_rejected(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as error:
            next_code("unknown", None, self.db, None)
        self.assertEqual(error.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
