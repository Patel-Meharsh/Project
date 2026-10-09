"""Add/update the supplied vendor directory and 24 locations without clearing operational data.

Run from Backend/: python seed_vendors_locations.py
This script is intentionally additive/upsert-only. It does NOT reset items, inventory,
purchase requisitions, purchase orders, GRNs, users, or other operational records.
"""
from app.database import SessionLocal, engine
from app import models

# code, name, category, phone, email, rating, payment terms
VENDORS = [
    ("VND-011", "K P Mat House", "Washroom Supplies", "70466 11777", "kpmathouse@yahoo.co.in", 4.4, "Net 30"),
    ("VND-012", "Ideal Office Need", "Washroom Supplies", "9619073966", "idealoffice.sales@gmail.com", 0, "Net 30"),
    ("VND-013", "Eco care solutions", "Washroom Supplies", "9825015522", "info@ecocare.solutions", 0, "Net 30"),
    ("VND-014", "Rentokil", "Washroom Supplies", "8087666926", "rihi.accounts@rentokil-initial.com", 0, "Net 30"),
    ("VND-015", "Shri Hari electrical", "Electrical", "9426484858", "shriharielectrical4@gmail.com", 0, "Net 30"),
    ("VND-016", "P-Square Marketing", "Wall Paint", "99255 11122", "psm1102@gmail.com", 0, "Net 30"),
    ("VND-017", "Veer Enetrprise", "RO-AMC", "9265124169", "", 5, "Advance"),
    ("VND-018", "Om Enterprises", "Stationery", "9824643085", "", 4, "Net 30"),
    ("VND-019", "The trophy studio", "Welcome Kit", "9904524250", "", 4, "Net 30"),
    ("VND-020", "Shree Printshop", "Printing", "9979690077", "", 4, "Net 30"),
    ("VND-021", "Laxmi Ply Wood", "Furniture Material", "+91 99049 10077", "", 4, "Net 15"),
    ("VND-022", "R B Trading Co,", "Electrical Material - Lights & Others", "+91 90330 77332", "", 4, "Net 30"),
    ("VND-023", "ChakravartiSanjiv kumar", "R&M Furniture & Chairs", "9228149773", "", 4, "Net 30"),
    ("VND-024", "Jay Ambe Decor - Arvind bhai", "R&M Furniture & Chairs", "9879618579", "", 4, "Net 30"),
    ("VND-025", "Balaji Furniture - Suresh Bhai", "Furniture Material", "8118843287", "", 4, "Net 30"),
    ("VND-026", "Hem Singh", "Colour Work", "123456", "", 4, "Net 30"),
    ("VND-027", "Jalaram Marketing", "Welcome Kit", "09428106548", "jmarketing501@gmail.com", 4, "Net 30"),
    ("VND-028", "T M Solutech Pvt Ltd", "Visual Studio & Microsoft", "07947717070", "info@tmsolutech.com", 4, "Net 30"),
    ("VND-029", "Krishna Stationary", "Stationery", "9898046444", "krishnastationary98@gmail.com", 4, "Net 30"),
]

# code, name, city, area sqft, headcount, washrooms, AC units, fans, pantries, phone, location type
LOCATIONS = [
    ("STORE-CH", "Central Store - CH", "Ahmedabad", 1440, 5, 2, 2, 7, 0, "9537461980", "STORE"),
    ("HQ-1B", "Corporate HQ - 1B", "Ahmedabad", 1440, 0, 2, 9, 16, 0, "6359771502", "SITE"),
    ("HQ-2A", "Corporate HQ - 2A", "Ahmedabad", 1440, 62, 1, 16, 13, 0, "6359645304", "SITE"),
    ("HQ-3B1", "Corporate HQ - 3B1", "Ahmedabad", 1440, 46, 1, 7, 10, 0, "7383322612", "SITE"),
    ("HQ-3A1", "Corporate HQ - 3A1", "Ahmedabad", 1440, 38, 1, 7, 7, 0, "7849921878", "SITE"),
    ("HQ-4A1", "Corporate HQ - 4A1", "Ahmedabad", 1440, 68, 3, 13, 22, 0, "8758215174", "SITE"),
    ("HQ-5A1", "Corporate HQ - 5A1", "Ahmedabad", 0, 0, 0, 0, 0, 0, "9601619381", "SITE"),
    ("HQ-B81", "Corporate HQ - B81", "Ahmedabad", 1440, 5, 1, 13, 9, 1, "6351855460", "SITE"),
    ("GANDHINAGAR", "Gandhinagar Site", "Gandhinagar", 3000, 16, 2, 8, 10, 1, "9925561139", "SITE"),
    ("BARODA", "Baroda Office", "Baroda", 1200, 25, 1, 4, 1, 0, "7990022114", "SITE"),
    ("RAJKOT", "Rajkot Office", "Rajkot", 1000, 29, 1, 10, 8, 1, "8320903795", "SITE"),
    ("PUNE", "Pune Office", "Pune", 1200, 25, 1, 7, 2, 1, "8446667909", "SITE"),
    ("HQ-B82", "Corporate HQ - B82", "Ahmedabad", 0, 0, 0, 0, 0, 0, "9571678573", "SITE"),
    ("HQ-A82", "Corporate HQ - A82", "Ahmedabad", 1440, 10, 1, 4, 4, 0, "7851987775", "SITE"),
    ("HQ-A91", "Corporate HQ - A91", "Ahmedabad", 1440, 33, 1, 17, 17, 0, "7984474647", "SITE"),
    ("HQ-3B2", "Corporate HQ - 3B2", "Ahmedabad", 1440, 38, 1, 8, 7, 0, "7600986704", "SITE"),
    ("HQ-5B1", "Corporate HQ - 5B1", "Ahmedabad", 1440, 40, 0, 8, 8, 0, "7357466509", "SITE"),
    ("HQ-6A", "Corporate HQ - 6A", "Ahmedabad", 1440, 10, 2, 7, 4, 0, "9601619381", "SITE"),
    ("HQ-1A1", "Corporate HQ - 1A1", "Ahmedabad", 1440, 34, 3, 8, 9, 1, "8320425118", "SITE"),
    ("HQ-1A2", "Corporate HQ - 1A2", "Ahmedabad", 1440, 1, 1, 5, 8, 0, "8320425118", "SITE"),
    ("HQ-10A1", "Corporate HQ-10A1", "Ahmedabad", 1500, 1, 1, 0, 5, 1, "6359645306", "SITE"),
    ("HQ-10A2", "Corporate HQ-10A2", "Ahmedabad", 1440, 35, 1, 8, 4, 0, "", "SITE"),
    ("HQ-10A3", "Corporate HQ-10A3", "Ahmedabad", 1440, 32, 2, 6, 11, 0, "", "SITE"),
    ("HQ-10A4", "Corporate HQ-10A4", "Ahmedabad", 1440, 33, 1, 8, 5, 0, "", "SITE"),
]


def main():
    if len(VENDORS) != 19 or len({r[0] for r in VENDORS}) != 19:
        raise RuntimeError("Expected 19 unique vendors")
    if len(LOCATIONS) != 24 or len({r[0] for r in LOCATIONS}) != 24:
        raise RuntimeError("Expected 24 unique locations")

    models.Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        for code, name, category, phone, email, rating, terms in VENDORS:
            row = db.query(models.VendorModel).filter_by(code=code).first()
            if row is None:
                row = models.VendorModel(code=code)
                db.add(row)
            row.name = name
            row.category = category
            row.phone = phone
            row.email = email
            row.rating = rating
            row.payment_terms = terms
            row.city = "Ahmedabad"
            row.status = "Active"

        for code, name, city, area, people, washrooms, acs, fans, pantries, phone, loc_type in LOCATIONS:
            row = db.query(models.LocationModel).filter_by(code=code).first()
            if row is None:
                row = models.LocationModel(code=code)
                db.add(row)
            row.name = name
            row.city = city
            row.type = "Store" if loc_type == "STORE" else "Office"
            row.loc_type = loc_type
            row.parent_store = None if loc_type == "STORE" else "STORE-CH"
            row.status = "Active"
            row.phone = phone
            row.area_sqft = area
            row.headcount = people
            row.num_washrooms = washrooms
            row.num_ac_units = acs
            row.num_fans = fans
            row.num_pantries = pantries

        db.commit()
        print(f"Vendors upserted: {db.query(models.VendorModel).count()} total (19 supplied)")
        print(f"Locations upserted: {db.query(models.LocationModel).count()} total (24 supplied)")
        print("Existing operational records were not cleared.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
