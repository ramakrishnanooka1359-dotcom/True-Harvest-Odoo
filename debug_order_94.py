import xmlrpc.client
import os
from dotenv import load_dotenv

# Load Odoo connection details
# Assuming we are in True Harvest/true_harvest_api
load_dotenv()

ODOO_URL = "http://54.157.185.157:8069"
ODOO_DB = "Odoo-Inventory"
ODOO_USER = "nookaramakrishna6789@gmail.com"
ODOO_API_KEY = "06cac53071aeddb384253735d05396079fb2256d"

common = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/common')
uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_API_KEY, {})
models = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/object')

order_name = "94" # Based on the screenshot

def check_order(name):
    print(f"Checking Order: {name}")
    # Removed 'locked' as it caused an error
    fields = ['name', 'state', 'invoice_status', 'tag_ids', 'partner_id']
    orders = models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'sale.order', 'search_read', [[('name', '=', name)]], {'fields': fields})
    if not orders:
        # Try search by ID if name 94 is actually ID 94
        try:
            orders = models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'sale.order', 'search_read', [[('id', '=', int(name))]], {'fields': fields})
        except ValueError:
            pass
    
    if orders:
        order = orders[0]
        print(f"Order Found: {order['name']} (ID: {order['id']})")
        print(f"Customer: {order['partner_id'][1]}")
        print(f"State: {order['state']}")
        print(f"Invoice Status: {order['invoice_status']}")
        
        # Check Tags
        tags = models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'crm.tag', 'read', [order['tag_ids']], {'fields': ['name']})
        print(f"Tags: {[t['name'] for t in tags]}")
        
        # Check Invoices
        invoices = models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'account.move', 'search_read', [[('invoice_origin', '=', order['name'])]], {'fields': ['name', 'state', 'move_type']})
        print("Invoices:")
        for inv in invoices:
            print(f"  - {inv['name']} ({inv['move_type']}): {inv['state']}")
            
        # Check Pickings
        pickings = models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'stock.picking', 'search_read', [[('origin', '=', order['name'])]], {'fields': ['name', 'state']})
        print("Pickings:")
        for p in pickings:
            print(f"  - {p['name']}: {p['state']}")
    else:
        print("Order not found.")

if __name__ == "__main__":
    check_order(order_name)
    # Also check SO094 or similar if the name is different
    check_order("S00094")
    # Actually, the screenshot shows #94. In Odoo it might be SO00094 or just 94.
