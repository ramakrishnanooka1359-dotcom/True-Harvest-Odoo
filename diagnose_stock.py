from odoo_client import models, uid
from config import ODOO_DB, ODOO_API_KEY, TRUE_HARVEST_COMPANY_ID

def diagnose_stock():
    print(f"Diagnosing for Company ID: {TRUE_HARVEST_COMPANY_ID}")
    
    # 1. Dashboard Logic: Active Products qty_available
    products = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'product.product', 'search_read',
        [[('company_id', '=', TRUE_HARVEST_COMPANY_ID), ('active', '=', True)]],
        {'fields': ['id', 'display_name', 'qty_available']}
    )
    dashboard_total = sum(p['qty_available'] for p in products)
    print(f"\nDashboard logic total (Active Products): {dashboard_total}")
    
    # 2. Hubs Logic: Internal Locations quants
    locations = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.location', 'search_read',
        [[('company_id', '=', TRUE_HARVEST_COMPANY_ID), ('usage', '=', 'internal')]],
        {'fields': ['id', 'display_name']}
    )
    loc_ids = [l['id'] for l in locations]
    print(f"Internal Locations: {[l['display_name'] for l in locations]}")
    
    quants = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.quant', 'search_read',
        [[('location_id', 'in', loc_ids), ('quantity', '>', 0)]],
        {'fields': ['id', 'product_id', 'location_id', 'quantity']}
    )
    hubs_total = sum(q['quantity'] for q in quants)
    print(f"Hubs logic total (Quants in Internal Locations): {hubs_total}")
    
    # 3. Find the difference
    print("\n--- Breakdown of Quants vs Product Qty ---")
    quant_sums = {}
    for q in quants:
        pid = q['product_id'][0]
        pname = q['product_id'][1]
        quant_sums[pid] = quant_sums.get(pid, 0) + q['quantity']
    
    product_map = {p['id']: p for p in products}
    
    all_pids = set(quant_sums.keys()) | set(product_map.keys())
    
    for pid in sorted(all_pids):
        q_qty = quant_sums.get(pid, 0)
        p_info = product_map.get(pid)
        p_qty = p_info['qty_available'] if p_info else 0
        p_name = p_info['display_name'] if p_info else f"Unknown (ID: {pid})"
        
        if not p_info:
            # Check if product exists but is inactive
            inactive_p = models.execute_kw(
                ODOO_DB, uid, ODOO_API_KEY,
                'product.product', 'search_read',
                [[('id', '=', pid)]],
                {'fields': ['display_name', 'active']}
            )
            if inactive_p:
                p_name = f"{inactive_p[0]['display_name']} (INACTIVE)"
            else:
                p_name = f"External Product (ID: {pid})"
            
        if q_qty != p_qty:
            print(f"Product: {p_name}")
            print(f"  Quant Qty: {q_qty}")
            print(f"  Product Qty_Available: {p_qty}")
            print(f"  Diff: {q_qty - p_qty}")

if __name__ == "__main__":
    diagnose_stock()
