from odoo_client import models, uid
from config import ODOO_DB, ODOO_API_KEY, TRUE_HARVEST_COMPANY_ID

def test_robust_update(product_id, target_qty):
    # 1. Get location
    warehouses = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.warehouse', 'search_read',
        [[('company_id', '=', TRUE_HARVEST_COMPANY_ID)]],
        {'fields': ['lot_stock_id'], 'limit': 1}
    )
    location_id = warehouses[0]['lot_stock_id'][0]
    
    print(f"Location ID: {location_id}, Product ID: {product_id}, Target Qty: {target_qty}")

    # 2. Search for existing quant
    quant_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.quant', 'search',
        [[('product_id', '=', product_id), ('location_id', '=', location_id)]]
    )
    
    if not quant_ids:
        print("Creating new quant...")
        quant_id = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'stock.quant', 'create',
            [{
                'product_id': product_id,
                'location_id': location_id,
                'inventory_quantity': float(target_qty)
            }]
        )
        quant_ids = [quant_id]
    else:
        print(f"Updating existing quant {quant_ids}...")
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'stock.quant', 'write',
            [quant_ids, {'inventory_quantity': float(target_qty)}]
        )
    
    # 3. KEY STEP: Apply the inventory adjustment
    # In Odoo 15+, action_apply_inventory is an object method
    print(f"Applying inventory adjustment for quants {quant_ids}...")
    try:
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'stock.quant', 'action_apply_inventory',
            [quant_ids]
        )
    except Exception as e:
        print(f"Method action_apply_inventory failed: {e}")
        print("Trying alternative: setting inventory_quantity_auto_apply again (maybe it needs to be alone?)")
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'stock.quant', 'write',
            [quant_ids, {'inventory_quantity_auto_apply': float(target_qty)}]
        )

    # 4. Verify
    updated_quants = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.quant', 'read',
        [quant_ids],
        {'fields': ['quantity', 'inventory_quantity', 'inventory_quantity_auto_apply']}
    )
    print(f"Final Quant state: {updated_quants}")

if __name__ == "__main__":
    test_robust_update(72, 50.0)
