"""
Seed script: Parse stockitems.xlsx and create Master Groups + Items in the database.

Excel structure (detected):
- Row 0: empty
- Row 1: Group headers at columns 4, 7, 10, 13 (every 3 cols starting at 4)
- Rows 2-N: Item names in the first col of each group, quantities in the next col
- Last data row: "Total" row (skip)
- Columns 1-2: Summary totals (skip)

Idempotent: safe to re-run — skips existing groups and items.

Usage:
  cd backend
  python seed_from_excel.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from datetime import datetime
from app.database import SessionLocal
from app import models

# ── Configuration ────────────────────────────────────────────────────────────
EXCEL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stockitems.xlsx")

# Group prefix mapping: cleaned group name → item code prefix
GROUP_PREFIXES = {
    "Diwali Gifts":            "DG",
    "Welcome Kit":             "WK",
    "Stationery":              "ST",
    "Electrical Refurbished":  "EL",
    "Electrical":              "EL",
}


def clean_group_name(raw: str) -> str:
    """Clean raw header like 'Diwali Gifts Stock' → 'Diwali Gifts'"""
    name = raw.strip()
    # Special mappings for known headers
    OVERRIDES = {
        "Electrical Stock (Refurbished Items)": "Electrical Refurbished",
    }
    if name in OVERRIDES:
        return OVERRIDES[name]
    # Remove "Stock" suffix
    for suffix in ["Stock", "stock"]:
        if name.endswith(suffix):
            name = name[:name.rfind(suffix)].strip()
    # Clean parenthetical if present
    if "(" in name:
        name = name[:name.index("(")].strip()
    return name


def get_prefix(group_name: str) -> str:
    """Get the 2-letter prefix for a group."""
    for key, prefix in GROUP_PREFIXES.items():
        if key.lower() in group_name.lower():
            return prefix
    # Auto-generate: first letters of each word
    words = group_name.split()
    if len(words) >= 2:
        return (words[0][0] + words[1][0]).upper()
    return group_name[:2].upper()


def parse_excel(filepath: str) -> dict:
    """Parse the Excel file and return {group_name: [{name, qty}, ...]}"""
    df = pd.read_excel(filepath, header=None)

    # Detect group columns from Row 1 (header row)
    header_row = 1
    groups = {}

    for col_idx in range(df.shape[1]):
        val = df.iloc[header_row, col_idx]
        if pd.notna(val) and isinstance(val, str) and val not in ("All Items", "Total"):
            # This is a group header
            name_col = col_idx
            qty_col = col_idx + 1  # quantity is always the next column

            group_name = clean_group_name(val)
            items = []

            # Read items from row 2 downward
            for row_idx in range(header_row + 1, df.shape[0]):
                item_name = df.iloc[row_idx, name_col]
                item_qty = df.iloc[row_idx, qty_col] if qty_col < df.shape[1] else None

                if pd.isna(item_name) or not str(item_name).strip():
                    continue

                name_str = str(item_name).strip()

                # Skip "Total" rows
                if name_str.lower() == "total":
                    continue

                qty = 0
                if pd.notna(item_qty):
                    try:
                        qty = int(float(item_qty))
                    except (ValueError, TypeError):
                        qty = 0

                items.append({"name": name_str, "qty": qty})

            if items:
                groups[group_name] = items

    return groups


def seed(dry_run=False):
    """Seed database from Excel."""
    print(f"\n{'='*60}")
    print(f"  SEED FROM EXCEL: {EXCEL_FILE}")
    print(f"{'='*60}\n")

    if not os.path.exists(EXCEL_FILE):
        print(f"ERROR: File not found: {EXCEL_FILE}")
        return

    # Parse Excel
    groups = parse_excel(EXCEL_FILE)

    print(f"Detected {len(groups)} Master Groups:\n")
    for gname, items in groups.items():
        prefix = get_prefix(gname)
        print(f"  [{prefix}] {gname} — {len(items)} items")
        for it in items:
            print(f"       {it['name']} (qty: {it['qty']})")

    if dry_run:
        print("\n[DRY RUN] No database changes made.")
        return

    # Connect to DB
    db = SessionLocal()

    try:
        groups_created = 0
        groups_existing = 0
        items_created = 0
        items_existing = 0

        for group_name, item_list in groups.items():
            prefix = get_prefix(group_name)

            # ── Create or find Master Group ──────────────────────────────
            mg = db.query(models.MasterGroupModel).filter_by(name=group_name).first()
            if mg:
                groups_existing += 1
                print(f"\n  [EXISTS] Master Group: {group_name} (id={mg.id})")
            else:
                mg = models.MasterGroupModel(
                    name=group_name,
                    description=f"Items from {group_name} category",
                    status="Active",
                    created_at=datetime.utcnow().isoformat(),
                )
                db.add(mg)
                db.flush()  # Get the ID
                groups_created += 1
                print(f"\n  [CREATED] Master Group: {group_name} (id={mg.id})")

            # ── Find existing items with this prefix to continue numbering ─
            existing_codes = db.query(models.ItemModel.code).filter(
                models.ItemModel.code.like(f"{prefix}-%")
            ).all()
            existing_nums = []
            for (code,) in existing_codes:
                try:
                    num = int(code.replace(f"{prefix}-", ""))
                    existing_nums.append(num)
                except (ValueError, TypeError):
                    pass
            next_num = (max(existing_nums) + 1) if existing_nums else 1

            # Also build a set of existing item names for this group (dedup check)
            existing_names = {
                i.name.strip().lower()
                for i in db.query(models.ItemModel).filter_by(master_group_id=mg.id).all()
                if i.name
            }

            # ── Create items ─────────────────────────────────────────────
            for it in item_list:
                item_name = it["name"]

                # Check for duplicate by name within this group
                if item_name.strip().lower() in existing_names:
                    items_existing += 1
                    print(f"    [EXISTS] {item_name}")
                    continue

                item_code = f"{prefix}-{str(next_num).zfill(3)}"
                next_num += 1

                # Infer UOM from name
                uom = "Nos"
                name_lower = item_name.lower()
                if any(w in name_lower for w in ["liter", "litre"]):
                    uom = "Liter"
                elif any(w in name_lower for w in ["kg", "kilo"]):
                    uom = "Kg"
                elif any(w in name_lower for w in ["pack", "set"]):
                    uom = "Pack"
                elif any(w in name_lower for w in ["roll"]):
                    uom = "Roll"
                elif any(w in name_lower for w in ["pair"]):
                    uom = "Pair"
                elif any(w in name_lower for w in ["meter", "metre"]):
                    uom = "Meter"

                item = models.ItemModel(
                    code=item_code,
                    name=item_name,
                    category=group_name,       # category = same as master group for now
                    sub_category="",
                    uom=uom,
                    brand_tier="Standard",
                    vendor_code="",
                    rate=0,
                    gst_pct=18,
                    rol=0,
                    max_stock=0,
                    lead_days=5,
                    status="Active",
                    master_group=group_name,    # legacy string
                    master_group_id=mg.id,      # FK
                )
                db.add(item)
                items_created += 1
                existing_names.add(item_name.strip().lower())
                print(f"    [CREATED] {item_code} — {item_name} (qty: {it['qty']})")

        db.commit()

        print(f"\n{'='*60}")
        print(f"  SEED COMPLETE")
        print(f"{'='*60}")
        print(f"  Master Groups: {groups_created} created, {groups_existing} existing")
        print(f"  Items:         {items_created} created, {items_existing} existing")
        print(f"{'='*60}\n")

    except Exception as e:
        db.rollback()
        print(f"\nERROR: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv or "-n" in sys.argv
    if dry:
        print("[DRY RUN MODE — no DB changes]")
    seed(dry_run=dry)
