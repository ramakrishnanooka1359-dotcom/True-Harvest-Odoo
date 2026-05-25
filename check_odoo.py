import xmlrpc.client
import sys
import os

# Add current directory to path to import config and odoo_client
sys.path.append(os.getcwd())

try:
    from config import ODOO_URL, ODOO_DB, ODOO_API_KEY
    from odoo_client import models, uid
    
    print(f"Connecting to {ODOO_URL}...")
    
    categories = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'product.category', 'search_read',
        [[]],
        {'fields': ['id', 'name']}
    )
    
    print("\n--- Odoo Product Categories ---")
    for cat in categories:
        print(f"ID: {cat['id']} | Name: {cat['name']}")
        
    print("\n--- Existing Product Categories ---")
    products = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'product.template', 'search_read',
        [[('name', 'in', ['Milk', 'Paneer', 'Curd', 'Ghee', 'sprouts'])]],
        {'fields': ['name', 'categ_id']}
    )
    for p in products:
        print(f"Product: {p['name']} | Category: {p['categ_id']}")

except Exception as e:
    print(f"Error: {e}")
