import xmlrpc.client
from config import ODOO_URL, ODOO_DB, ODOO_USERNAME, ODOO_API_KEY

def check_line_fields():
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    uid = common.authenticate(ODOO_DB, ODOO_USERNAME, ODOO_API_KEY, {})
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
    
    fields = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.return.picking.line', 'fields_get',
        [],
        {'attributes': ['string', 'type', 'required']}
    )
    for field in sorted(fields.keys()):
        print(f"{field}: {fields[field]}")

if __name__ == "__main__":
    check_line_fields()
