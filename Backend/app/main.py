import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from .api.routes import router
from .database import engine
from . import models
from .config import settings
from fastapi.responses import Response

_PLACEHOLDER_KEY = "CHANGE-ME-use-a-real-secret-in-production"
if settings.ENVIRONMENT == "production" and settings.SECRET_KEY == _PLACEHOLDER_KEY:
    raise RuntimeError("SECRET_KEY is still the placeholder value. Set a real secret in .env before running in production.")
if settings.ENVIRONMENT != "production" and settings.SECRET_KEY == _PLACEHOLDER_KEY:
    logging.warning("SECRET_KEY is using the default placeholder — set a real value in .env")


models.Base.metadata.create_all(bind=engine)

from sqlalchemy import text

with engine.begin() as conn:
    # Add line_items column to grns if missing
    has_col = conn.execute(text(
        "SELECT 1 FROM information_schema.columns WHERE table_name='grns' AND column_name='line_items'"
    )).fetchone()
    if not has_col:
        conn.execute(text("ALTER TABLE public.grns ADD COLUMN line_items TEXT"))

    # Add compound index on inventory(item_code, location_code) if missing
    has_idx = conn.execute(text(
        "SELECT 1 FROM pg_indexes WHERE tablename='inventory' AND indexname='ix_inventory_item_location'"
    )).fetchone()
    if not has_idx:
        conn.execute(text("CREATE INDEX ix_inventory_item_location ON inventory (item_code, location_code)"))

    # Add loc_type column to locations if missing
    has_loc_type = conn.execute(text(
        "SELECT 1 FROM information_schema.columns WHERE table_name='locations' AND column_name='loc_type'"
    )).fetchone()
    if not has_loc_type:
        conn.execute(text("ALTER TABLE public.locations ADD COLUMN loc_type VARCHAR DEFAULT 'SITE'"))

    # Add parent_store column to locations if missing
    has_parent_store = conn.execute(text(
        "SELECT 1 FROM information_schema.columns WHERE table_name='locations' AND column_name='parent_store'"
    )).fetchone()
    if not has_parent_store:
        conn.execute(text("ALTER TABLE public.locations ADD COLUMN parent_store VARCHAR"))

    # Seed loc_type: STORE-CH is the central store; CH-* are consumption sites
    conn.execute(text(
        "UPDATE locations SET loc_type = 'STORE', parent_store = NULL WHERE code = 'STORE-CH'"
    ))
    conn.execute(text(
        "UPDATE locations SET loc_type = 'SITE', parent_store = 'STORE-CH' "
        "WHERE code LIKE 'CH-%' AND code != 'STORE-CH'"
    ))
    # Default anything still NULL to SITE
    conn.execute(text(
        "UPDATE locations SET loc_type = 'SITE' WHERE loc_type IS NULL"
    ))

    # Create indexes if missing (idempotent migrations)
    _indexes = [
        ("ix_pr_status",        "purchase_requisitions", "status"),
        ("ix_pr_item_code",     "purchase_requisitions", "item_code"),
        ("ix_pr_location_code", "purchase_requisitions", "location_code"),
        ("ix_po_status",        "purchase_orders",       "status"),
        ("ix_po_vendor_code",   "purchase_orders",       "vendor_code"),
        ("ix_po_item_code",     "purchase_orders",       "item_code"),
        ("ix_grn_status",       "grns",                  "status"),
        ("ix_grn_vendor_code",  "grns",                  "vendor_code"),
        ("ix_grn_po_no",        "grns",                  "po_no"),
        ("ix_iss_item_code",    "issuance_log",          "item_code"),
        ("ix_iss_location_code","issuance_log",          "location_code"),
        ("ix_iss_month",        "issuance_log",          "month"),
        ("ix_ret_item_code",    "returns_log",           "item_code"),
        ("ix_ret_vendor_code",  "returns_log",           "vendor_code"),
        ("ix_ret_status",       "returns_log",           "status"),
        ("ix_svc_location_code","third_party_services",  "location_code"),
        ("ix_evt_type",         "event_log",             "event_type"),
        ("ix_evt_ts",           "event_log",             "ts"),
    ]
    for idx_name, tbl, col in _indexes:
        exists = conn.execute(text(
            "SELECT 1 FROM pg_indexes WHERE tablename=:tbl AND indexname=:idx"
        ), {"tbl": tbl, "idx": idx_name}).fetchone()
        if not exists:
            conn.execute(text(f"CREATE INDEX {idx_name} ON {tbl} ({col})"))

    # Composite index on event_log(entity, entity_id)
    if not conn.execute(text(
        "SELECT 1 FROM pg_indexes WHERE tablename='event_log' AND indexname='ix_evt_entity'"
    )).fetchone():
        conn.execute(text("CREATE INDEX ix_evt_entity ON event_log (entity, entity_id)"))

    # ── New column migrations ────────────────────────────────────────────────
    _new_cols = [
        ("inventory",              "last_grn_no",        "VARCHAR"),
        ("issuance_log",           "issued_to_location",  "VARCHAR"),
        ("purchase_orders",        "po_type",             "VARCHAR DEFAULT 'Routine'"),
        ("purchase_requisitions",  "line_items",          "TEXT"),
        ("purchase_orders",        "line_items",          "TEXT"),
        ("purchase_orders",        "subject",             "VARCHAR"),
        ("purchase_orders",        "contact_person",      "VARCHAR"),
        ("vendors",                "address",             "TEXT"),
        ("items",                  "master_group",        "VARCHAR"),
        ("items",                  "master_group_id",     "INTEGER"),
        ("master_groups",          "created_at",          "VARCHAR"),
        ("master_groups",          "updated_at",          "VARCHAR"),
        ("categories",             "master_group",        "VARCHAR"),
    ]
    for tbl, col, col_type in _new_cols:
        # Check table exists before trying to alter it
        tbl_exists = conn.execute(text(
            "SELECT 1 FROM information_schema.tables WHERE table_name=:tbl"
        ), {"tbl": tbl}).fetchone()
        if not tbl_exists:
            continue
        has = conn.execute(text(
            "SELECT 1 FROM information_schema.columns WHERE table_name=:tbl AND column_name=:col"
        ), {"tbl": tbl, "col": col}).fetchone()
        if not has:
            conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN {col} {col_type}"))

    # ── Vendor rate cards table (create if missing on existing DBs) ──────────
    has_vrc = conn.execute(text(
        "SELECT 1 FROM information_schema.tables WHERE table_name='vendor_rate_cards'"
    )).fetchone()
    if not has_vrc:
        conn.execute(text("""
            CREATE TABLE vendor_rate_cards (
                id           VARCHAR PRIMARY KEY,
                vendor_code  VARCHAR NOT NULL,
                file_name    VARCHAR NOT NULL,
                stored_name  VARCHAR NOT NULL,
                file_size    INTEGER DEFAULT 0,
                mime_type    VARCHAR DEFAULT 'application/pdf',
                uploaded_at  VARCHAR,
                uploaded_by  VARCHAR
            )
        """))
        conn.execute(text("CREATE INDEX ix_vrc_vendor_code ON vendor_rate_cards (vendor_code)"))

    # ── Master Group data migration: string → FK ─────────────────────────────
    # Step 1: Ensure master_groups table has entries for all unique string values
    mg_table_exists = conn.execute(text(
        "SELECT 1 FROM information_schema.tables WHERE table_name='master_groups'"
    )).fetchone()
    items_has_mg = conn.execute(text(
        "SELECT 1 FROM information_schema.columns WHERE table_name='items' AND column_name='master_group'"
    )).fetchone()
    items_has_mg_id = conn.execute(text(
        "SELECT 1 FROM information_schema.columns WHERE table_name='items' AND column_name='master_group_id'"
    )).fetchone()

    if mg_table_exists and items_has_mg and items_has_mg_id:
        # Extract unique group names from items that have a string but no FK yet
        unmapped = conn.execute(text(
            "SELECT DISTINCT master_group FROM items "
            "WHERE master_group IS NOT NULL AND master_group != '' "
            "AND (master_group_id IS NULL)"
        )).fetchall()

        for (grp_name,) in unmapped:
            # Create master_group record if it doesn't exist
            existing = conn.execute(text(
                "SELECT id FROM master_groups WHERE name = :name"
            ), {"name": grp_name}).fetchone()
            if not existing:
                import datetime as _mdt
                conn.execute(text(
                    "INSERT INTO master_groups (name, status, created_at) VALUES (:name, 'Active', :ts)"
                ), {"name": grp_name, "ts": _mdt.datetime.utcnow().isoformat()})

        # Step 2: Map items.master_group_id from items.master_group string
        conn.execute(text(
            "UPDATE items SET master_group_id = mg.id "
            "FROM master_groups mg "
            "WHERE items.master_group = mg.name "
            "AND items.master_group_id IS NULL"
        ))

app = FastAPI(
    title="Gateway Group Inventory API",
    description="Inventory, Procurement & Budget Management System",
    version="1.0.0",
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.ENVIRONMENT != "production" else None,
)

# Build allowed origins from env
origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]


# Always allow localhost in development
if settings.ENVIRONMENT != "production":
    origins += ["http://localhost:5173", "http://localhost:3000", "http://localhost:80"]

# Safety net: if ALLOWED_ORIGINS not set in production, log a loud warning
# but still allow the known production domain so the site doesn't go dark
if settings.ENVIRONMENT == "production" and not origins:
    import logging
    logging.warning("ALLOWED_ORIGINS not set — using safe fallback")
    origins = [
        "https://opex.vaanilabs.ai"
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if settings.ENVIRONMENT == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Cache-Control"] = "no-store"
    return response

app.include_router(router, prefix="/api")

@app.get("/")
def root():
    return {"message": "Gateway Inventory API", "version": "1.0.0"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/debug/routes")
def debug_routes():
    """List all registered routes — useful for verifying production deployment."""
    import os
    routes = []
    for r in app.routes:
        if hasattr(r, 'methods') and hasattr(r, 'path'):
            routes.append({"path": r.path, "methods": sorted(r.methods)})
    xlsx_candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "stockitems.xlsx"),
        os.path.join(os.getcwd(), "stockitems.xlsx"),
        os.path.join(os.getcwd(), "app", "stockitems.xlsx"),
    ]
    xlsx_found = [c for c in xlsx_candidates if os.path.exists(c)]
    return {
        "total_routes": len(routes),
        "environment": settings.ENVIRONMENT,
        "stockitems_xlsx": xlsx_found or "NOT FOUND",
        "cwd": os.getcwd(),
        "routes": routes,
    }

# ── Startup route logger — confirms what's actually registered ────────────
logging.basicConfig(level=logging.INFO)
_logger = logging.getLogger("gateway")
_logger.info("CORS origins: %s", origins)
_logger.info("Environment: %s", settings.ENVIRONMENT)
_route_count = 0
for _r in app.routes:
    if hasattr(_r, 'methods') and hasattr(_r, 'path'):
        _route_count += 1
_logger.info("Total routes registered: %d", _route_count)
# Log critical routes specifically
_critical = ["/api/master-groups/seed-from-excel", "/api/purchase-orders/{po_no}/pdf", "/api/purchase-orders/from-pr/{pr_no}"]
for _cp in _critical:
    _found = any(hasattr(r, 'path') and r.path == _cp for r in app.routes)
    _logger.info("Route %s: %s", _cp, "REGISTERED" if _found else "MISSING")