"""Reset sample data to exactly the user's 75 active items and 74 stock-register rows.

WARNING: This intentionally clears seeded operational/master data in this database.
It preserves user accounts so existing logins continue to work.
Run from Backend/: python seed.py
"""
from app.database import SessionLocal, engine
from app import models

# code, name, category, group, UOM, rate, GST %, ROL, lead days, vendor code
ROWS = [
("HK-018","Vim Soap","Cleaning Chemicals","", "Piece",27,18,4,7,"VND-012"),
("HK-013","Microfiber duster","Cleaning Tools","", "Piece",32,5,10,7,"VND-012"),
("HK-020","Garbage Bag 19*21","Waste Management","", "Roll",32,18,5,7,"VND-012"),
("HK-023","Wet Mop Refil with Clip","Cleaning Tools","", "Set",60,18,5,7,"VND-012"),
("HK-021","Soft Broom","Cleaning Tools","", "Piece",55,0,3,7,"VND-012"),
("HK-016","Urinal Screen Think Fresh","Washroom Supplies","", "Piece",50,18,15,7,"VND-012"),
("HK-019","Garbage Bag 40*50","Waste Management","", "Kg",85,18,5,7,"VND-012"),
("DG-002","Jumbo Waffle Maker","Diwali Gifts","Diwali Gifts","Nos",0,18,0,5,""),
("DG-003","India Art Villa","Diwali Gifts","Diwali Gifts","Nos",0,18,0,5,""),
("DG-004","Sandwich Maker","Diwali Gifts","Diwali Gifts","Nos",0,18,0,5,""),
("DG-005","Milton Tiffin","Diwali Gifts","Diwali Gifts","Nos",0,18,0,5,""),
("DG-006","Cooker","Diwali Gifts","Diwali Gifts","Nos",0,18,0,5,""),
("DG-007","Kettle","Diwali Gifts","Diwali Gifts","Nos",0,18,0,5,""),
("DG-008","Tiffin","Diwali Gifts","Diwali Gifts","Nos",0,18,0,5,""),
("WK-001","Mug","Welcome Kit","Welcome Kit","Nos",0,18,0,5,""),
("WK-002","Laptop Bag","Welcome Kit","Welcome Kit","Nos",0,18,0,5,""),
("WK-003","Foundation Bag","Welcome Kit","Welcome Kit","Nos",0,18,0,5,""),
("WK-004","Box","Welcome Kit","Welcome Kit","Nos",0,18,0,5,""),
("ST-001","White (Big) Notepad","Stationery","Stationery","Nos",0,18,0,5,""),
("ST-002","White (Small) Notepad","Stationery","Stationery","Nos",0,18,0,5,""),
("ST-003","Black Notepad","Stationery","Stationery","Nos",0,18,0,5,""),
("WK-005","Water Bottle","Welcome Kit","Welcome Kit","Nos",480,18,20,15,"VND-014"),
("HK-001","Taski Suma Drain","Cleaning Chemicals","", "Liter",167,18,1,7,"VND-011"),
("HK-002","Taski R2","Cleaning Chemicals","", "Liter",140,18,1,7,"VND-011"),
("HK-003","Taski R1","Cleaning Chemicals","", "Liter",200.2,18,1,7,"VND-011"),
("HK-004","White phenyl","Cleaning Chemicals","", "Liter",19,18,2,7,"VND-011"),
("HK-005","Taski R6","Cleaning Chemicals","", "Liter",111,18,1,7,"VND-011"),
("HK-006","Harpic","Cleaning Chemicals","", "Liter",197,18,2,7,"VND-011"),
("HK-007","Colin","Cleaning Chemicals","", "Liter",184,5,2,7,"VND-011"),
("HK-008","Lizol","Cleaning Chemicals","", "Liter",177,5,1,7,"VND-011"),
("HK-009","Sanitizer","Cleaning Chemicals","", "Liter",110,18,1,7,"VND-011"),
("HK-010","M Fold Napkin","Washroom Supplies","", "Pack",31,18,90,7,"VND-012"),
("HK-011","Toilet Tissue Roll","Washroom Supplies","", "Pack",17,18,75,7,"VND-012"),
("HK-012","Face Tissue","Washroom Supplies","", "Pack",55,18,12,7,"VND-012"),
("HK-014","Microfiber duster coral","Cleaning Tools","", "Piece",70,5,5,7,"VND-012"),
("HK-015","Scotch Brite","Cleaning Tools","", "Piece",8,18,2,7,"VND-012"),
("HK-017","Room freshner Odonil","Washroom Supplies","", "Bottle",65,18,5,7,"VND-012"),
("HK-022","Dry Mop Set Micor Fibre","Cleaning Tools","", "Set",390,18,5,7,"VND-012"),
("HK-024","Nylon Scrubber","Cleaning Tools","", "Piece",3,18,2,7,"VND-012"),
("HK-025","Garbage Bag Small","Waste Management","", "Roll",29,18,5,7,"VND-012"),
("HK-026","Detol Handwash 900ml","Washroom Supplies","", "Liter",117,18,2,7,"VND-012"),
("HK-027","Vimbar Liquid","Cleaning Chemicals","", "Liter",105,18,2,7,"VND-012"),
("HK-028","Hit Black","Washroom Supplies","", "Bottle",244,18,2,7,"VND-012"),
("HK-029","Hit Red","Washroom Supplies","", "Bottle",244,18,2,7,"VND-012"),
("HK-030","All Out Refil","Washroom Supplies","", "Piece",60,18,5,7,"VND-012"),
("HK-031","All Out Machine with refil","Washroom Supplies","", "Set",75,18,5,7,"VND-012"),
("HK-032","Air-Freshner","Washroom Supplies","", "Piece",465,18,55,0,"VND-015"),
("HK-033","Sanitary Hygiene","Waste Management","", "Pack",5.5,18,4,0,"VND-013"),
("HK-034","Foam liquid","Washroom Supplies","", "Liter",110,18,1,7,"VND-013"),
("HK-035","Hard Broom","Cleaning Tools","", "Piece",55,0,5,7,"VND-011"),
("HK-036","Sanitory Pad","Waste Management","", "Piece",5.5,18,50,7,"VND-013"),
("HK-037","Pump Vaccum press","Cleaning Tools","", "Piece",35,18,2,7,"VND-011"),
("HK-038","Tile Brush","Cleaning Tools","", "Piece",15,18,5,7,"VND-011"),
("HK-039","Sponge whips","Cleaning Tools","", "Piece",15,18,5,7,"VND-011"),
("HK-040","Toilet Brush","Washroom Supplies","", "Piece",30,18,5,7,"VND-011"),
("ST-004","Ball Pen","Stationery","Stationery","Nos",0,18,0,5,""),
("EL-001","6 Amp Switch","Electrical Refurbished","Electrical Refurbished","Nos",0,18,0,5,""),
("EL-002","6 Amp Socket","Electrical Refurbished","Electrical Refurbished","Nos",0,18,0,5,""),
("EL-003","2 Modular Plate","Electrical Refurbished","Electrical Refurbished","Nos",0,18,0,5,""),
("EL-004","4 Modular Plate","Electrical Refurbished","Electrical Refurbished","Nos",0,18,0,5,""),
("EL-005","6 Modular Plate","Electrical Refurbished","Electrical Refurbished","Nos",0,18,0,5,""),
("EL-006","8 Modular Plate","Electrical Refurbished","Electrical Refurbished","Nos",0,18,0,5,""),
("EL-007","16 Modular Plate","Electrical Refurbished","Electrical Refurbished","Nos",0,18,0,5,""),
("EL-008","Socket Type Regulator","Electrical Refurbished","Electrical Refurbished","Nos",0,18,0,5,""),
("EL-009","16 Amp Switch","Electrical Refurbished","Electrical Refurbished","Nos",0,18,0,5,""),
("EL-010","16 Amp Socket","Electrical Refurbished","Electrical Refurbished","Nos",0,18,0,5,""),
("DG-001","Air Fryer","Diwali Gifts","Diwali Gifts","Nos",0,18,0,5,""),
("DG-009","Burgner Cooker Set","Diwali Gifts","Diwali Gifts","Piece",982,18,0,0,""),
("DG-010","Wonderchef Toaster","Diwali Gifts","Diwali Gifts","Piece",1100,18,0,1,""),
("DG-013","Cello Caseroll","Diwali Gifts","Diwali Gifts","Piece",737,18,20,5,""),
("SL-001","Visual Studio License","Visual Studio & Microsoft","Software License","Piece",42000,18,30,10,""),
("EM-001","15 W LED Fitting Light","Electrical Material - Lights & Others","Electrical Material","Piece",390,18,10,5,"VND-016"),
("ST-005","Coppier Paper A/4 - Reflec-Extra White","Stationery","Stationery","Pack",250,0,3,5,"VND-017"),
("ST-006","Duracell-A4-Ultra","Stationery","Stationery","Piece",55,0,5,5,"VND-017"),
("ST-007","Box File","Stationery","Stationery","Piece",58,0,5,5,"VND-017"),
]

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

# code, name, city, area sqft, headcount, washrooms, AC units, fans, pantries, phone
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

CLEAR_MODELS = [
    models.EventLogModel, models.ReturnLogModel, models.IssuanceLogModel,
    models.GRNModel, models.PurchaseOrderModel, models.PurchaseRequisitionModel,
    models.MonthlyBudgetModel, models.ThirdPartyServiceModel,
    models.ConsumptionNormModel, models.VendorRateCardModel, models.InventoryModel,
    models.ItemModel, models.HKMasterModel, models.MasterGroupModel,
    models.CategoryModel, models.VendorModel, models.LocationModel,
]

def main():
    codes = [row[0] for row in ROWS]
    if len(ROWS) != 75 or len(set(codes)) != 75:
        raise RuntimeError(f"Expected 75 unique items; found {len(ROWS)} rows and {len(set(codes))} unique codes")

    models.Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # Deliberate reset of sample/business data; user accounts are preserved.
        for model in CLEAR_MODELS:
            db.query(model).delete(synchronize_session=False)

        location_codes = [row[0] for row in LOCATIONS]
        if len(LOCATIONS) != 24 or len(set(location_codes)) != 24:
            raise RuntimeError("Expected 24 unique locations")
        vendor_codes = [row[0] for row in VENDORS]
        if len(VENDORS) != 19 or len(set(vendor_codes)) != 19:
            raise RuntimeError("Expected 19 unique vendors")

        for code, name, city, area, people, washrooms, acs, fans, pantries, phone, loc_type in LOCATIONS:
            db.add(models.LocationModel(
                code=code, name=name, city=city, type="Store" if loc_type == "STORE" else "Office",
                loc_type=loc_type, parent_store=None if loc_type == "STORE" else "STORE-CH",
                status="Active", contact_person="", phone=phone,
                area_sqft=area, headcount=people, num_washrooms=washrooms,
                num_ac_units=acs, num_fans=fans, num_pantries=pantries,
            ))
        for code, name, category, phone, email, rating, payment_terms in VENDORS:
            db.add(models.VendorModel(
                code=code, name=name, category=category, city="Ahmedabad",
                contact_person="", phone=phone, email=email, payment_terms=payment_terms,
                rating=rating, status="Active"
            ))

        for code, name, category, group, uom, rate, gst, rol, lead, vendor in ROWS:
            db.add(models.ItemModel(
                code=code, name=name, category=category,
                sub_category=group or None, uom=uom,
                brand_tier="Economy" if code == "HK-035" else "Standard",
                vendor_code=vendor or None, rate=rate, gst_pct=gst,
                rol=rol, max_stock=max(rol * 2, 0), lead_days=lead,
                status="Active"
            ))
        db.flush()

        # Exactly 74 stock-register rows; Microsoft Visual Studio License (SL-001) excluded.
        for code, name, category, group, uom, rate, gst, rol, lead, vendor in ROWS:
            if code == "SL-001":
                continue
            db.add(models.InventoryModel(
                item_code=code, location_code="STORE-CH",
                vendor_code=vendor or None, rate=rate,
                opening_stock=0, stock_in=0, stock_out=0, last_grn_no=None
            ))
        db.commit()

        location_count = db.query(models.LocationModel).count()
        vendor_count = db.query(models.VendorModel).count()
        active_items = db.query(models.ItemModel).filter(models.ItemModel.status == "Active").count()
        item_total = db.query(models.ItemModel).count()
        stock_rows = db.query(models.InventoryModel).count()
        pr_count = db.query(models.PurchaseRequisitionModel).count()
        po_count = db.query(models.PurchaseOrderModel).count()
        grn_count = db.query(models.GRNModel).count()
        print(f"Locations: {location_count} (expected 24); Vendors: {vendor_count} (expected 19)")
        print(f"Items: {item_total} total, {active_items} active (expected 75 / 75)")
        print(f"Stock Register: {stock_rows} rows (expected 74; SL-001 excluded)")
        print(f"Purchase Requisitions: {pr_count}; Purchase Orders: {po_count}; GRNs: {grn_count} (all expected 0)")
        if (location_count, vendor_count, item_total, active_items, stock_rows, pr_count, po_count, grn_count) != (24, 19, 75, 75, 74, 0, 0, 0):
            raise RuntimeError("Post-reset validation failed; inspect database state before using the app.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    main()
