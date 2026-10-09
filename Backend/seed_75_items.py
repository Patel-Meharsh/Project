"""Upsert the 75 Items-page records supplied by the user into the items table.

Run from Backend/: python seed_75_items.py
This script changes only rows in the items table; it does not delete records.
"""
from app.database import SessionLocal
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

def main():
    codes = [row[0] for row in ROWS]
    if len(ROWS) != 75 or len(set(codes)) != 75:
        raise RuntimeError(f"Expected 75 unique items; found {len(ROWS)} rows and {len(set(codes))} unique codes")
    db = SessionLocal()
    added = updated = 0
    try:
        for code, name, category, group, uom, rate, gst, rol, lead, vendor in ROWS:
            obj = db.query(models.ItemModel).filter(models.ItemModel.code == code).first()
            if obj is None:
                obj = models.ItemModel(code=code)
                db.add(obj)
                added += 1
            else:
                updated += 1
            obj.name = name
            obj.category = category
            obj.sub_category = group or None
            obj.uom = uom
            obj.brand_tier = "Economy" if code == "HK-035" else "Standard"
            obj.vendor_code = vendor or None
            obj.rate = rate
            obj.gst_pct = gst
            obj.rol = rol
            obj.max_stock = max(rol * 2, 0)
            obj.lead_days = lead
            obj.status = "Active"
        db.commit()
        active_count = db.query(models.ItemModel).filter(models.ItemModel.status == "Active").count()
        seeded_count = db.query(models.ItemModel).count()
        print(f"75 source records processed: {added} added, {updated} updated.")
        print(f"Items table totals: {seeded_count} total rows, {active_count} active rows.")
        if active_count < 75:
            print("Note: there may be additional active rows beyond the 75 source records.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    main()
