from odoo_client import models, uid
from config import ODOO_DB, ODOO_API_KEY, TRUE_HARVEST_COMPANY_ID

# Search for locations belonging to the company
locations = models.execute_kw(
    ODOO_DB, uid, ODOO_API_KEY,
    'stock.location', 'search_read',
    [[('company_id', '=', TRUE_HARVEST_COMPANY_ID), ('usage', '=', 'internal')]],
    {'fields': ['id', 'display_name', 'name']}
)

print("Internal Locations for Company 3:")
for loc in locations:
    print(f"ID: {loc['id']}, Name: {loc['display_name']}")

# Also check for warehouses
warehouses = models.execute_kw(
    ODOO_DB, uid, ODOO_API_KEY,
    'stock.warehouse', 'search_read',
    [[('company_id', '=', TRUE_HARVEST_COMPANY_ID)]],
    {'fields': ['id', 'name', 'code', 'lot_stock_id']}
)

print("\nWarehouses for Company 3:")
for wh in warehouses:
    print(f"ID: {wh['id']}, Name: {wh['name']}, Code: {wh['code']}, Main Location ID: {wh['lot_stock_id']}")
