from odoo_client import models, uid
from config import ODOO_DB, ODOO_API_KEY

def find_subscription_models():
    # Search for any model containing 'sub' or 'recur'
    all_models = models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'ir.model', 'search_read', 
                                 [('|', ('model', 'ilike', 'sub'), ('model', 'ilike', 'recur'))], 
                                 {'fields': ['model', 'name']})
    
    print("Potential Subscription/Recurring Models:")
    for m in all_models:
        print(f" - {m['model']}: {m['name']}")

if __name__ == "__main__":
    find_subscription_models()
