# fix_all_values.py
from app.database import SessionLocal
from app import models
import json

db = SessionLocal()

# Fix GRNs
grns = db.query(models.GRNModel).all()
for g in grns:
    if g.line_items:
        lis = json.loads(g.line_items)
        g.total_value = sum(
            float(li.get("accepted_qty") or 0) * float(li.get("rate") or 0)
            for li in lis
        )

# Fix Inventory
stocks = db.query(models.InventoryModel).all()
for inv in stocks:
    closing = inv.opening_stock + inv.stock_in - inv.stock_out
    inv.value = closing * (inv.rate or 0)

db.commit()
print("Fixed all values")