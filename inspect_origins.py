from odoo_client import models, uid
from config import ODOO_DB, ODOO_API_KEY, TRUE_HARVEST_COMPANY_ID

def inspect_orders():
    orders = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.order', 'search_read',
        [[('company_id', '=', TRUE_HARVEST_COMPANY_ID)]],
        {'fields': ['name', 'origin', 'state', 'date_order'], 'limit': 20}
    )
    
    print("Recent Orders Origin Analysis:")
    for order in orders:
        print(f"Order: {order['name']}, Origin: {order.get('origin')}, State: {order['state']}")

if __name__ == "__main__":
    inspect_orders()
