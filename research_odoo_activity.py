from odoo_client import models, uid
from config import ODOO_DB, ODOO_API_KEY, TRUE_HARVEST_COMPANY_ID
from datetime import date, timedelta

def research_activity():
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    
    print(f"Researching activity for {today} and {yesterday}...")
    
    # 1. SALES: sale.order.line for today
    sales_lines = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.order.line', 'search_read',
        [[
            ('company_id', '=', TRUE_HARVEST_COMPANY_ID),
            ('order_id.state', 'in', ['sale', 'done']),
            ('order_id.date_order', '>=', f'{today} 00:00:00')
        ]],
        {'fields': ['product_id', 'product_uom_qty', 'order_id']}
    )
    print(f"\nFound {len(sales_lines)} sales lines for today.")
    for line in sales_lines[:5]:
        print(f"  - Product: {line['product_id'][1]}, Qty: {line['product_uom_qty']}, Order: {line['order_id'][1]}")

    # 2. STOCK ADDITIONS: stock.move for today
    # destination_location.usage == 'internal' AND source_location.usage != 'internal'
    stock_moves = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.move', 'search_read',
        [[
            ('company_id', '=', TRUE_HARVEST_COMPANY_ID),
            ('state', '=', 'done'),
            ('date', '>=', f'{today} 00:00:00'),
            ('location_dest_id.usage', '=', 'internal'),
            ('location_id.usage', '!=', 'internal')
        ]],
        {'fields': ['product_id', 'product_uom_qty', 'location_id', 'location_dest_id', 'reference']}
    )
    print(f"\nFound {len(stock_moves)} stock additions for today.")
    for move in stock_moves[:5]:
        print(f"  - Product: {move['product_id'][1]}, Qty: {move['product_uom_qty']}, Ref: {move['reference']}")
        print(f"    From {move['location_id'][1]} To {move['location_dest_id'][1]}")

if __name__ == "__main__":
    research_activity()
