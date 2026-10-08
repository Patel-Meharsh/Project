from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import date, datetime


# --- Location ---
class LocationBase(BaseModel):
    code: str
    name: str
    city: Optional[str] = None
    type: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = "Active"
    area_sqft: Optional[float] = 0
    headcount: Optional[int] = 0
    num_washrooms: Optional[int] = 0
    num_urinals: Optional[int] = 0
    num_wcs: Optional[int] = 0
    num_wash_basins: Optional[int] = 0
    num_pantries: Optional[int] = 0
    num_meeting_rooms: Optional[int] = 0
    num_ac_units: Optional[int] = 0
    num_fans: Optional[int] = 0

class LocationCreate(LocationBase): pass
class LocationUpdate(LocationBase): pass
class Location(LocationBase):
    id: int
    created_at: Optional[datetime] = None
    class Config: from_attributes = True


# --- Vendor ---
class VendorBase(BaseModel):
    code: str
    name: str
    category: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    city: Optional[str] = None
    gst_no: Optional[str] = None
    pan: Optional[str] = None
    payment_terms: Optional[str] = None
    rating: Optional[float] = 0
    status: Optional[str] = "Active"

class VendorCreate(VendorBase): pass
class VendorUpdate(VendorBase): pass
class Vendor(VendorBase):
    id: int
    created_at: Optional[datetime] = None
    class Config: from_attributes = True


# --- Item ---
class ItemBase(BaseModel):
    code: str
    name: str
    category: Optional[str] = None
    sub_category: Optional[str] = None
    uom: Optional[str] = None
    brand_tier: Optional[str] = None
    vendor_code: Optional[str] = None
    rate: Optional[float] = 0
    gst_pct: Optional[float] = 18
    reorder_level: Optional[float] = 0
    max_stock: Optional[float] = 0
    lead_days: Optional[int] = 5
    status: Optional[str] = "Active"

class ItemCreate(ItemBase): pass
class ItemUpdate(ItemBase): pass
class Item(ItemBase):
    id: int
    created_at: Optional[datetime] = None
    class Config: from_attributes = True


# --- Consumption Norm ---
class ConsumptionNormBase(BaseModel):
    item_code: str
    basis: Optional[str] = None
    norm_value: Optional[float] = 0
    norm_unit: Optional[str] = None
    frequency: Optional[str] = "Monthly"
    remarks: Optional[str] = None

class ConsumptionNormCreate(ConsumptionNormBase): pass
class ConsumptionNorm(ConsumptionNormBase):
    id: int
    class Config: from_attributes = True


# --- Inventory ---
class InventoryBase(BaseModel):
    item_code: str
    location_code: str
    opening_stock: Optional[float] = 0
    closing_stock: Optional[float] = 0

class InventoryCreate(InventoryBase): pass
class InventoryUpdate(BaseModel):
    opening_stock: Optional[float] = None
    closing_stock: Optional[float] = None

class Inventory(InventoryBase):
    id: int
    updated_at: Optional[datetime] = None
    class Config: from_attributes = True

class InventoryDetail(BaseModel):
    id: int
    item_code: str
    item_name: str
    category: str
    uom: str
    location_code: str
    location_name: str
    vendor_code: Optional[str]
    rate: float
    opening_stock: float
    stock_in: float
    stock_out: float
    closing_stock: float
    reorder_level: float
    status: str
    value: float
    class Config: from_attributes = True


# --- Purchase Requisition ---
class PRBase(BaseModel):
    pr_no: str
    pr_date: date
    item_code: str
    req_qty: float
    location_code: Optional[str] = None
    department: Optional[str] = None
    requested_by: Optional[str] = None
    priority: Optional[str] = "Normal"
    required_date: Optional[date] = None
    justification: Optional[str] = None
    status: Optional[str] = "Draft"
    approved_by: Optional[str] = None
    approval_date: Optional[date] = None
    po_ref: Optional[str] = None

class PRCreate(PRBase): pass
class PRUpdate(BaseModel):
    status: Optional[str] = None
    approved_by: Optional[str] = None
    approval_date: Optional[date] = None
    po_ref: Optional[str] = None

class PR(PRBase):
    id: int
    created_at: Optional[datetime] = None
    class Config: from_attributes = True

class PRDetail(PR):
    item_name: Optional[str] = None
    item_rate: Optional[float] = None
    est_value: Optional[float] = None
    location_name: Optional[str] = None
    class Config: from_attributes = True


# --- Purchase Order ---
class POBase(BaseModel):
    po_no: str
    po_date: date
    pr_ref: Optional[str] = None
    vendor_code: str
    item_code: str
    uom: Optional[str] = None
    qty_ordered: float
    rate: float
    delivery_date: Optional[date] = None
    delivery_location: Optional[str] = None
    terms: Optional[str] = None
    status: Optional[str] = "Draft"

class POCreate(POBase): pass
class POUpdate(BaseModel):
    status: Optional[str] = None
    received_qty: Optional[float] = None

class PO(POBase):
    id: int
    amount: Optional[float] = None
    gst_pct: Optional[float] = None
    gst_amt: Optional[float] = None
    total: Optional[float] = None
    received_qty: Optional[float] = 0
    balance_qty: Optional[float] = None
    created_at: Optional[datetime] = None
    class Config: from_attributes = True

class PODetail(PO):
    vendor_name: Optional[str] = None
    item_name: Optional[str] = None
    class Config: from_attributes = True


# --- GRN ---
class GRNBase(BaseModel):
    grn_no: str
    grn_date: date
    invoice_no: Optional[str] = None
    po_no: Optional[str] = None
    vendor_code: str
    item_code: str
    recd_qty: float
    accepted_qty: float
    rejected_qty: Optional[float] = 0
    uom: Optional[str] = None
    rate: Optional[float] = None
    received_by: Optional[str] = None
    inspected_by: Optional[str] = None
    store_location: Optional[str] = None
    batch_lot: Optional[str] = None
    expiry_date: Optional[date] = None
    status: Optional[str] = "Pending Inspection"
    remarks: Optional[str] = None

class GRNCreate(GRNBase): pass
class GRNUpdate(BaseModel):
    status: Optional[str] = None
    accepted_qty: Optional[float] = None
    rejected_qty: Optional[float] = None
    remarks: Optional[str] = None

class GRN(GRNBase):
    id: int
    amount: Optional[float] = None
    created_at: Optional[datetime] = None
    class Config: from_attributes = True

class GRNDetail(GRN):
    vendor_name: Optional[str] = None
    item_name: Optional[str] = None
    class Config: from_attributes = True


# --- Issuance ---
class IssuanceBase(BaseModel):
    issue_id: str
    issue_date: date
    item_code: str
    qty: float
    uom: Optional[str] = None
    location_code: Optional[str] = None
    to_dept: Optional[str] = None
    issued_to: Optional[str] = None
    issued_by: Optional[str] = None
    remarks: Optional[str] = None

class IssuanceCreate(IssuanceBase): pass
class Issuance(IssuanceBase):
    id: int
    month: Optional[int] = None
    quarter: Optional[int] = None
    rate: Optional[float] = None
    value: Optional[float] = None
    created_at: Optional[datetime] = None
    class Config: from_attributes = True

class IssuanceDetail(Issuance):
    item_name: Optional[str] = None
    location_name: Optional[str] = None
    class Config: from_attributes = True


# --- Dashboard / Analytics ---
class DashboardKPIs(BaseModel):
    pending_prs: int
    open_pos: int
    pending_grns: int
    ytd_po_value: float
    total_items: int
    below_rol: int
    stock_value: float
    active_vendors: int

class BudgetVsActual(BaseModel):
    item_code: str
    item_name: str
    category: str
    uom: str
    budget_qty: float
    budget_value: float
    actual_qty: float
    actual_value: float
    variance_qty: float
    variance_value: float
    variance_pct: float
    status: str

class CategoryBudget(BaseModel):
    category: str
    monthly: float
    quarterly: float
    half_yearly: float
    yearly: float
    pct_of_total: float

class LocationBudget(BaseModel):
    location_code: str
    location_name: str
    area_sqft: float
    headcount: int
    monthly: float
    yearly: float
    rate_per_sqft: float
    rate_per_person: float
