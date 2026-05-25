from odoo_client import models, uid
from config import ODOO_DB, ODOO_API_KEY, TRUE_HARVEST_COMPANY_ID

def check_quants(variant_id):
    # 1. Get warehouse location
    warehouses = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.warehouse', 'search_read',
        [[('company_id', '=', TRUE_HARVEST_COMPANY_ID)]],
        {'fields': ['lot_stock_id'], 'limit': 1}
    )
    location_id = warehouses[0]['lot_stock_id'][0]
    print(f"Main Location ID: {location_id}")

    # 2. Get variants quants
    quants = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.quant', 'search_read',
        [[
            ('product_id', '=', variant_id),
            ('location_id', '=', location_id)
        ]],
        {'fields': ['id', 'product_id', 'location_id', 'quantity', 'inventory_quantity', 'inventory_quantity_auto_apply', 'inventory_diff_quantity']}
    )
    
    print("\nQuants for Variant {}:".format(variant_id))
    for q in quants:
        print(f"Quant ID: {q['id']}")
        print(f"  Product: {q['product_id']}")
        print(f"  Location: {q['location_id']}")
        print(f"  Available Quantity: {q['quantity']}")
        print(f"  Inventory Quantity: {q['inventory_quantity']}")
        print(f"  Inventory Diff: {q['inventory_diff_quantity']}")
        print(f"  Auto Apply Field: {q.get('inventory_quantity_auto_apply', 'NOT PRESENT')}")

if __name__ == "__main__":
    check_quants(72)
