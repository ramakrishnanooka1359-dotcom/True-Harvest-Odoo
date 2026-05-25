from odoo_client import models, uid
from config import ODOO_DB, ODOO_API_KEY

def check_models():
    # Check if sale.subscription exists
    try:
        models_list = models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'ir.model', 'search_read', [[('model', '=', 'sale.subscription')]], {'fields': ['name', 'model']})
        if models_list:
            print(f"Found model: {models_list[0]['model']} - {models_list[0]['name']}")
        else:
            print("Model sale.subscription not found.")
    except Exception as e:
        print(f"Error checking sale.subscription: {e}")

    # Check sale.order fields for anything frequency or sub related
    fields = models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'sale.order', 'fields_get', [], {'attributes': ['string']})
    sub_fields = [f for f in fields if 'sub' in f.lower() or 'frequency' in f.lower() or 'recurring' in f.lower()]
    print(f"Subscription related fields in sale.order: {sub_fields}")

if __name__ == "__main__":
    check_models()
