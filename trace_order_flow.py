import xmlrpc.client
import os
from dotenv import load_dotenv

load_dotenv()

ODOO_URL = "http://54.157.185.157:8069"
ODOO_DB = "Odoo-Inventory"
ODOO_USER = "nookaramakrishna6789@gmail.com"
ODOO_API_KEY = "06cac53071aeddb384253735d05396079fb2256d"

common = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/common')
uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_API_KEY, {})
models = xmlrpc.client.ServerProxy(f'{ODOO_URL}/xmlrpc/2/object')

def trace_order(name):
    print(f"\n=== Document Trace for {name} ===")
    
    # 1. Sale Order
    orders = models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'sale.order', 'search_read', [[('name', '=', name)]], {'fields': ['name', 'state', 'invoice_status', 'tag_ids']})
    if not orders:
        print("Order not found.")
        return
    
    so = orders[0]
    print(f"Sales Order: {so['name']} | State: {so['state']} | Invoice: {so['invoice_status']}")
    
    # 2. Pickings (Deliveries/Returns)
    pickings = models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'stock.picking', 'search_read', [[('origin', '=', name)]], {'fields': ['name', 'state', 'picking_type_id']})
    print("\nDeliveries / Returns (Stock):")
    for p in pickings:
        p_type = p['picking_type_id'][1]
        print(f"  - {p['name']} ({p_type}): {p['state']}")
        
    # 3. Invoices (Customer Invoices / Credit Notes)
    invoices = models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'account.move', 'search_read', [[('invoice_origin', '=', name)]], {'fields': ['name', 'state', 'move_type']})
    print("\nInvoices / Credit Notes (Accounting):")
    for inv in invoices:
        type_label = "Invoice" if inv['move_type'] == 'out_invoice' else "Credit Note (Refund)" if inv['move_type'] == 'out_refund' else inv['move_type']
        print(f"  - {inv['name']} ({type_label}): {inv['state']}")

    # 4. Tags (Dashboard Requests)
    if so['tag_ids']:
        tags = models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'crm.tag', 'read', [so['tag_ids']], {'fields': ['name']})
        print(f"\nDashboard Tags (User Requests): {[t['name'] for t in tags]}")
    else:
        print("\nNo Dashboard Tags found.")

if __name__ == "__main__":
    # From previous check, Order #94 is likely S00096
    trace_order("S00096")
    trace_order("S00094")
