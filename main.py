from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import date
from products import router as products_router
from orders import router as orders_router
from activity import router as activity_router
from admin_actions import router as admin_router
from auth import router as auth_router
from delivery import router as delivery_router
from consignment import router as consignment_router
from barcodes import router as barcodes_router
from odoo_client import models, uid
from config import ODOO_DB, ODOO_API_KEY, TRUE_HARVEST_COMPANY_ID
from database import engine
from models import Base

# Auto-create local database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="True Harvest-Odoo", version="1.0.0")


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:5174", "http://127.0.0.1:5174",
        "http://localhost:5175", "http://127.0.0.1:5175",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(products_router)
app.include_router(orders_router)
app.include_router(activity_router)
app.include_router(admin_router)
app.include_router(delivery_router)
app.include_router(consignment_router)
app.include_router(barcodes_router)



@app.get("/dashboard/stats")
def dashboard_stats(target_date: str = None):
    today = target_date if target_date else date.today().isoformat()

    # 1️⃣ Active/Draft sale orders (Packing Unit), excluding subscription templates
    draft_orders = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.order', 'search_count',
        [[
            ('state', 'in', ['draft', 'sent']),
            ('company_id', '=', TRUE_HARVEST_COMPANY_ID),
            ('origin', '!=', '[SUBSCRIPTION_MASTER]')
        ]]
    )

    # 2️⃣ Confirmed orders processing in warehouse (sale_order state = 'sale')
    confirmed_orders = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.order', 'search_count',
        [[('state', '=', 'sale'), ('company_id', '=', TRUE_HARVEST_COMPANY_ID)]]
    )

    # 3️⃣ Outgoing pickings that are ready / in progress (Out for Delivery)
    out_for_delivery = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.picking', 'search_count',
        [[
            ('picking_type_id.code', '=', 'outgoing'),
            ('state', 'in', ['assigned', 'waiting', 'confirmed']),
            ('company_id', '=', TRUE_HARVEST_COMPANY_ID)
        ]]
    )

    # 4️⃣ Delivered today (pickings validated today)
    # We use a simpler query first to check if records exist, then narrow down
    delivered_today = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.picking', 'search_count',
        [[
            ('state', '=', 'done'),
            ('date_done', '>=', f'{today} 00:00:00'),
            ('date_done', '<=', f'{today} 23:59:59'),
            ('company_id', '=', TRUE_HARVEST_COMPANY_ID),
            ('picking_type_id.code', '=', 'outgoing')
        ]]
    )

    # 5️⃣ Total qty on hand across all True Harvest products (Warehouse stock metric)
    products = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'product.product', 'search_read',
        [[('company_id', '=', TRUE_HARVEST_COMPANY_ID), ('active', '=', True)]],
        {'fields': ['qty_available']}
    )
    total_stock = sum(p['qty_available'] for p in products)

    return {
        "target_date": today,
        "packing_unit": draft_orders,
        "warehouse_items": confirmed_orders,
        "warehouse_total_stock": total_stock,
        "out_for_delivery": out_for_delivery,
        "delivered_today": delivered_today,
    }


@app.get("/warehouses/stock")
def warehouse_stock():
    # 1. Fetch internal locations for the company
    locations = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.location', 'search_read',
        [[('company_id', '=', TRUE_HARVEST_COMPANY_ID), ('usage', '=', 'internal')]],
        {'fields': ['id', 'display_name', 'name']}
    )

    # 2. Fetch quants for these locations, strictly for active products
    location_ids = [loc['id'] for loc in locations]
    quants = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.quant', 'search_read',
        [[
            ('location_id', 'in', location_ids), 
            ('quantity', '>', 0),
            ('product_id.active', '=', True)
        ]],
        {'fields': ['location_id', 'product_id', 'quantity']}
    )

    # 3. Group quants by location and format for frontend
    hubs = []
    for loc in locations:
        loc_stock = [
            {
                "product_id": q['product_id'][0],
                "product_name": q['product_id'][1],
                "quantity": q['quantity']
            }
            for q in quants if q['location_id'][0] == loc['id']
        ]
        
        # Only include locations that are actually used as warehouses (or have stock)
        # to avoid cluttering the UI with technical internal locations
        if not loc_stock:
            continue

        hubs.append({
            "id": loc['id'],
            "name": loc['display_name'],
            "location": loc['name'],
            "stock": sum(item['quantity'] for item in loc_stock),
            "capacity": "Flexible",
            "items": loc_stock
        })

    return hubs
