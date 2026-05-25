from odoo_client import models, uid
from config import ODOO_DB, ODOO_API_KEY

def check_partner_fields():
    fields = models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'res.partner', 'fields_get', [], {'attributes': ['string']})
    relevant = [f for f in fields if 'comment' in f or 'note' in f]
    print(f"Relevant partner fields: {relevant}")

if __name__ == "__main__":
    check_partner_fields()
