from sqlalchemy import Column, String, Integer, Float, Date, Text, Index
from .database import Base


class LocationModel(Base):
    __tablename__ = "locations"
    code = Column(String, primary_key=True)
    name = Column(String)
    city = Column(String)
    type = Column(String)           # display category: Office | Branch | Store | Warehouse
    loc_type = Column(String, default="SITE")   # inventory role: STORE | SITE
    parent_store = Column(String)   # null for STOREs; code of parent STORE for SITEs
    contact_person = Column(String)
    phone = Column(String)
    status = Column(String, default="Active")
    area_sqft = Column(Integer, default=0)
    headcount = Column(Integer, default=0)
    num_washrooms = Column(Integer, default=0)
    num_urinals = Column(Integer, default=0)
    num_wcs = Column(Integer, default=0)
    num_wash_basins = Column(Integer, default=0)
    num_pantries = Column(Integer, default=0)
    num_meeting_rooms = Column(Integer, default=0)
    num_ac_units = Column(Integer, default=0)
    num_fans = Column(Integer, default=0)


class VendorModel(Base):
    __tablename__ = "vendors"
    code = Column(String, primary_key=True)
    name = Column(String)
    category = Column(String)
    contact_person = Column(String)
    phone = Column(String)
    email = Column(String)
    city = Column(String)
    address = Column(Text)       # full street address
    gst_no = Column(String)
    pan = Column(String)
    payment_terms = Column(String)
    rating = Column(Float, default=0)
    status = Column(String, default="Active")
    services_offered = Column(String)
    locations_served = Column(String)


class VendorRateCardModel(Base):
    """Uploaded vendor pricing/rate PDFs. Metadata row; file lives on disk under
    <UPLOAD_DIR>/vendors/<vendor_code>/rate-cards/<id>.pdf."""
    __tablename__ = "vendor_rate_cards"
    id           = Column(String, primary_key=True)       # uuid4 hex
    vendor_code  = Column(String, nullable=False)
    file_name    = Column(String, nullable=False)         # original client filename
    stored_name  = Column(String, nullable=False)         # {uuid}.pdf on disk
    file_size    = Column(Integer, default=0)             # bytes
    mime_type    = Column(String, default="application/pdf")
    uploaded_at  = Column(String)                          # ISO-8601 UTC
    uploaded_by  = Column(String)                          # user email
    __table_args__ = (Index('ix_vrc_vendor_code', 'vendor_code'),)


class HKMasterModel(Base):
    __tablename__ = "hk_master"
    code = Column(String, primary_key=True)
    name = Column(String)
    category = Column(String)
    sub_category = Column(String)
    uom = Column(String)
    eco_brand = Column(String)
    eco_price = Column(Float, default=0)
    std_brand = Column(String)
    std_price = Column(Float, default=0)
    prem_brand = Column(String)
    prem_price = Column(Float, default=0)
    recommended = Column(String)
    rate = Column(Float, default=0)
    gst_pct = Column(Float, default=18)
    vendor_code = Column(String)
    rol = Column(Integer, default=20)
    max_stock = Column(Integer, default=100)
    lead_days = Column(Integer, default=5)
    status = Column(String, default="Active")


class ItemModel(Base):
    __tablename__ = "items"
    code = Column(String, primary_key=True)
    name = Column(String)
    category = Column(String)
    sub_category = Column(String)
    uom = Column(String)
    brand_tier = Column(String)
    vendor_code = Column(String)
    rate = Column(Float, default=0)
    gst_pct = Column(Float, default=18)
    rol = Column(Integer, default=0)
    max_stock = Column(Integer, default=0)
    lead_days = Column(Integer, default=5)
    status = Column(String, default="Active")
    master_group = Column(String)           # legacy string (kept for backward compat during migration)
    master_group_id = Column(Integer)       # FK to master_groups.id


class ConsumptionNormModel(Base):
    __tablename__ = "consumption_norms"
    id = Column(Integer, primary_key=True, autoincrement=True)
    item_code = Column(String)
    item_name = Column(String)
    category = Column(String)
    basis = Column(String)
    norm_value = Column(Float)
    norm_unit = Column(String)
    rate = Column(Float)
    cost_per_unit = Column(Float)
    frequency = Column(String)
    remarks = Column(Text)


class InventoryModel(Base):
    __tablename__ = "inventory"
    id = Column(Integer, primary_key=True, autoincrement=True)
    item_code = Column(String)
    location_code = Column(String)
    vendor_code = Column(String, index=True)
    rate = Column(Float, default=0)
    opening_stock = Column(Float, default=0)
    stock_in = Column(Float, default=0)
    stock_out = Column(Float, default=0)
    last_grn_no = Column(String)   # most recent GRN that affected this row
    __table_args__ = (Index('ix_inventory_item_location', 'item_code', 'location_code'),)


class PurchaseRequisitionModel(Base):
    __tablename__ = "purchase_requisitions"
    pr_no = Column(String, primary_key=True)
    pr_date = Column(Date)
    item_code = Column(String)         # legacy single-item (backward compat)
    req_qty = Column(Float)            # legacy single-item qty
    location_code = Column(String)
    department = Column(String)
    requested_by = Column(String)
    priority = Column(String, default="Normal")
    required_date = Column(Date)
    justification = Column(Text)
    status = Column(String, default="Draft")
    approved_by = Column(String)
    approval_date = Column(Date)
    po_ref = Column(String)
    line_items = Column(Text)          # JSON: [{item_code, item_name, qty, uom, rate}]
    __table_args__ = (
        Index('ix_pr_status', 'status'),
        Index('ix_pr_item_code', 'item_code'),
        Index('ix_pr_location_code', 'location_code'),
    )


class PurchaseOrderModel(Base):
    __tablename__ = "purchase_orders"
    po_no = Column(String, primary_key=True)
    po_date = Column(Date)
    pr_ref = Column(String)
    vendor_code = Column(String)
    item_code = Column(String)         # legacy single-item (backward compat)
    uom = Column(String)
    qty_ordered = Column(Float)
    rate = Column(Float)
    gst_pct = Column(Float, default=18)
    delivery_date = Column(Date)
    delivery_location = Column(String)
    terms = Column(String)
    subject = Column(String)           # PO subject line (for PDF header)
    contact_person = Column(String)    # vendor contact for PO
    status = Column(String, default="Draft")
    po_type = Column(String, default="Routine")  # Routine, AMC, One-Time, Emergency
    received_qty = Column(Float, default=0)
    balance_qty = Column(Float, default=0)
    line_items = Column(Text)          # JSON: [{item_code, description, qty, uom, rate, gst_pct}]
    __table_args__ = (
        Index('ix_po_status', 'status'),
        Index('ix_po_vendor_code', 'vendor_code'),
        Index('ix_po_item_code', 'item_code'),
    )


class GRNModel(Base):
    __tablename__ = "grns"
    grn_no = Column(String, primary_key=True)
    grn_date = Column(Date)
    invoice_no = Column(String)
    po_no = Column(String)
    vendor_code = Column(String)
    item_code = Column(String)
    recd_qty = Column(Float)
    accepted_qty = Column(Float)
    rejected_qty = Column(Float, default=0)
    uom = Column(String)
    rate = Column(Float)
    received_by = Column(String)
    inspected_by = Column(String)
    store_location = Column(String)
    batch_lot = Column(String)
    status = Column(String, default="Pending Inspection")
    remarks = Column(Text)
    line_items = Column(Text)   # JSON array of {item_code,item_name,vendor_code,vendor_name,recd_qty,accepted_qty}
    __table_args__ = (
        Index('ix_grn_status', 'status'),
        Index('ix_grn_vendor_code', 'vendor_code'),
        Index('ix_grn_po_no', 'po_no'),
    )


class IssuanceLogModel(Base):
    __tablename__ = "issuance_log"
    issue_id = Column(String, primary_key=True)
    date = Column(Date)
    month = Column(Integer)
    quarter = Column(Integer)
    item_code = Column(String)
    qty = Column(Float)
    uom = Column(String)
    rate = Column(Float)
    location_code = Column(String)
    department = Column(String)
    issued_to = Column(String)
    issued_by = Column(String)
    issued_to_location = Column(String)  # site/location items are going TO
    remarks = Column(Text)
    __table_args__ = (
        Index('ix_iss_item_code', 'item_code'),
        Index('ix_iss_location_code', 'location_code'),
        Index('ix_iss_month', 'month'),
    )


class MonthlyBudgetModel(Base):
    __tablename__ = "monthly_budget"
    id = Column(Integer, primary_key=True, autoincrement=True)
    item_code = Column(String)
    location_code = Column(String)
    month = Column(Integer)
    budget_qty = Column(Float, default=0)
    budget_value = Column(Float, default=0)
    actual_qty = Column(Float, default=0)
    actual_value = Column(Float, default=0)


class ReturnLogModel(Base):
    __tablename__ = "returns_log"
    return_id = Column(String, primary_key=True)
    return_date = Column(Date)
    grn_ref = Column(String)
    item_code = Column(String)
    item_name = Column(String)
    qty_returned = Column(Float)
    uom = Column(String)
    vendor_code = Column(String)
    reason = Column(String)
    status = Column(String, default="Pending")
    credit_note = Column(String)
    remarks = Column(Text)
    __table_args__ = (
        Index('ix_ret_item_code', 'item_code'),
        Index('ix_ret_vendor_code', 'vendor_code'),
        Index('ix_ret_status', 'status'),
    )


class ThirdPartyServiceModel(Base):
    __tablename__ = "third_party_services"
    id = Column(Integer, primary_key=True, autoincrement=True)
    location_code = Column(String)
    service_type = Column(String)   # Cleaning, Security, Pest Control, etc
    vendor_code = Column(String)
    vendor_name = Column(String)
    vendor_contact = Column(String)
    contract_start = Column(Date)
    contract_end = Column(Date)
    monthly_cost = Column(Float, default=0)
    scope = Column(Text)
    status = Column(String, default="Active")
    __table_args__ = (
        Index('ix_svc_location_code', 'location_code'),
    )


class UserModel(Base):
    __tablename__ = "users"
    id            = Column(Integer, primary_key=True, autoincrement=True)
    email         = Column(String, unique=True, nullable=False)
    full_name     = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    role          = Column(String, default="observer")   # super_admin | admin | analyst | observer
    department    = Column(String)
    phone         = Column(String)
    avatar_color  = Column(String, default="#f0a500")
    is_active     = Column(String, default="true")
    created_at    = Column(String)                        # ISO string, avoids DateTime import
    last_login    = Column(String)


class EventLogModel(Base):
    """Immutable append-only event log — every state change in the system.
    Feeds the future ML/analytics layer. Never delete rows from this table."""
    __tablename__ = "event_log"
    id            = Column(Integer, primary_key=True, autoincrement=True)
    ts            = Column(String, nullable=False)          # ISO-8601 UTC timestamp
    event_type    = Column(String, nullable=False)          # grn.created, issuance.created, pr.status_changed …
    entity        = Column(String, nullable=False)          # grn | pr | po | issuance | return | inventory | user
    entity_id     = Column(String, nullable=False)          # primary key of the affected row
    actor_id      = Column(Integer)                         # users.id (null = system)
    actor_role    = Column(String)
    location_code = Column(String)
    item_code     = Column(String)
    vendor_code   = Column(String)
    qty           = Column(Float)
    rate          = Column(Float)
    value         = Column(Float)                           # qty × rate
    before_state  = Column(Text)                            # JSON snapshot before change
    after_state   = Column(Text)                            # JSON snapshot after change
    meta          = Column(Text)                            # free JSON for extra fields
    __table_args__ = (
        Index('ix_evt_entity', 'entity', 'entity_id'),
        Index('ix_evt_type', 'event_type'),
        Index('ix_evt_ts', 'ts'),
    )


class CategoryModel(Base):
    """Hierarchical category system. parent_id=NULL means top-level category."""
    __tablename__ = "categories"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    name         = Column(String, nullable=False)
    parent_id    = Column(Integer)       # NULL = top-level, set = sub-category
    master_group = Column(String)        # linked master group name
    description  = Column(String)
    status       = Column(String, default="Active")


class MasterGroupModel(Base):
    """Item master groups: HK Benchmark, Electrical, Stationery, etc."""
    __tablename__ = "master_groups"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String, nullable=False, unique=True)
    description = Column(String)
    status      = Column(String, default="Active")
    created_at  = Column(String)      # ISO timestamp
    updated_at  = Column(String)      # ISO timestamp
