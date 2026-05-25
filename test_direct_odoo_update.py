from odoo_client import models, uid
from config import ODOO_DB, ODOO_API_KEY, TRUE_HARVEST_COMPANY_ID

def test_direct_update(product_id, target_qty):
    # 1. Get location
    warehouses = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.warehouse', 'search_read',
        [[('company_id', '=', TRUE_HARVEST_COMPANY_ID)]],
        {'fields': ['lot_stock_id'], 'limit': 1}
    )
    location_id = warehouses[0]['lot_stock_id'][0]
    print(f"Location ID: {location_id}")

    # 2. Try updating via inventory_quantity_auto_apply
    print(f"Attempting update to {target_qty} for product {product_id}...")
    
    quant_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.quant', 'search',
        [[('product_id', '=', product_id), ('location_id', '=', location_id)]]
    )
    
    if quant_ids:
        print(f"Found existing quant(s): {quant_ids}")
        # Method 1: inventory_quantity_auto_apply
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'stock.quant', 'write',
            [quant_ids, {'inventory_quantity_auto_apply': float(target_qty)}]
        )
        print("Write to inventory_quantity_auto_apply completed.")
    else:
        print("No quant found, creating new one...")
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'stock.quant', 'create',
            [{
                'product_id': product_id,
                'location_id': location_id,
                'inventory_quantity_auto_apply': float(target_qty)
            }]
        )
        print("Create completed.")

    # 3. Read back
    updated_quants = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.quant', 'search_read',
        [[('product_id', '=', product_id), ('location_id', '=', location_id)]],
        {'fields': ['quantity', 'inventory_quantity_auto_apply']}
    )
    print(f"Post-update search result: {updated_quants}")

if __name__ == "__main__":
    # Test with Curd 500g (ID 72) and target 50.0
    test_direct_update(72, 50.0)
