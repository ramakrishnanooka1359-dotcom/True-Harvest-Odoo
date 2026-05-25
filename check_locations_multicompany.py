from odoo_client import models, uid
from config import ODOO_DB, ODOO_API_KEY

def check_virtual_locations():
    print("Querying virtual partner locations in Odoo...")
    locations = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.location', 'search_read',
        [[('name', 'in', ['Customers', 'Vendors'])]],
        {'fields': ['id', 'name', 'complete_name', 'company_id']}
    )
    for loc in locations:
        print(f"ID: {loc['id']} | Complete Name: {loc['complete_name']} | Company setting: {loc.get('company_id')}")

if __name__ == "__main__":
    check_virtual_locations()
