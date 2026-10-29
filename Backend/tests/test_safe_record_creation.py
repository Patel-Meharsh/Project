import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import HTTPException

from app.database import Base
from app import models
from app.api.routes import create_item_with_vendor


class SafeRecordCreationTests(unittest.TestCase):
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
                models.MasterGroupModel.__table__,
                models.CategoryModel.__table__,
            ],
        )
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.admin = models.UserModel(role="admin")

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_new_vendor_and_item_are_created_together(self):
        result = create_item_with_vendor(
            {
                "item": {
                    "code": "EM-001",
                    "name": "LED Fitting",
                    "category": "Electrical",
                    "sub_category": "Lighting",
                    "vendor_code": "",
                },
                "vendor": {
                    "code": "VND-001",
                    "name": "Example Electricals",
                    "category": "Electrical",
                    "status": "Active",
                },
            },
            self.db,
            self.admin,
        )

        self.assertEqual(result["item"].vendor_code, "VND-001")
        self.assertIsNotNone(self.db.query(models.VendorModel).filter_by(code="VND-001").first())
        self.assertIsNotNone(self.db.query(models.ItemModel).filter_by(code="EM-001").first())

    def test_new_group_and_category_are_created_for_item(self):
        result = create_item_with_vendor(
            {
                "item": {
                    "code": "HW-001",
                    "name": "Door Hinge",
                    "category": "Door Fittings",
                    "sub_category": "Door Hardware",
                    "master_group": "Hardware",
                },
                "vendor": {
                    "code": "VND-HW-001",
                    "name": "Hardware Supplier",
                    "category": "Hardware",
                    "status": "Active",
                },
            },
            self.db,
            self.admin,
        )

        group = self.db.query(models.MasterGroupModel).filter_by(name="Hardware").one()
        category = self.db.query(models.CategoryModel).filter_by(
            name="Door Fittings", master_group="Hardware"
        ).one()
        self.assertEqual(result["item"].master_group_id, group.id)
        self.assertEqual(result["item"].master_group, "Hardware")
        self.assertEqual(category.name, "Door Fittings")

    def test_existing_group_and_category_are_reused_case_insensitively(self):
        group = models.MasterGroupModel(name="Hardware", status="Active")
        self.db.add(group)
        self.db.flush()
        category = models.CategoryModel(name="Fasteners", master_group="Hardware", status="Active")
        self.db.add(category)
        self.db.commit()

        create_item_with_vendor(
            {
                "item": {
                    "code": "HW-002",
                    "name": "Hex Bolt",
                    "category": "fasteners",
                    "master_group": "hardware",
                },
                "vendor": None,
            },
            self.db,
            self.admin,
        )

        self.assertEqual(self.db.query(models.MasterGroupModel).count(), 1)
        self.assertEqual(self.db.query(models.CategoryModel).count(), 1)
        item = self.db.query(models.ItemModel).filter_by(code="HW-002").one()
        self.assertEqual(item.master_group_id, group.id)
        self.assertEqual(item.master_group, "Hardware")

    def test_item_failure_rolls_back_new_vendor(self):
        self.db.add(models.ItemModel(code="EM-001", name="Existing item"))
        self.db.commit()

        with self.assertRaises(HTTPException) as error:
            create_item_with_vendor(
                {
                    "item": {
                        "code": "EM-001",
                        "name": "Duplicate item",
                        "category": "Electrical",
                    },
                    "vendor": {
                        "code": "VND-002",
                        "name": "Vendor that must roll back",
                        "category": "Electrical",
                    },
                },
                self.db,
                self.admin,
            )

        self.assertEqual(error.exception.status_code, 409)
        self.assertIsNone(self.db.query(models.VendorModel).filter_by(code="VND-002").first())
        self.assertEqual(self.db.query(models.ItemModel).filter_by(code="EM-001").count(), 1)


if __name__ == "__main__":
    unittest.main()
