from odoo_client import models, uid
from config import ODOO_DB, ODOO_API_KEY, TRUE_HARVEST_COMPANY_ID

def check_all_prices():
    # Search for all templates
    templates = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'product.template', 'search_read',
        [[('company_id', '=', TRUE_HARVEST_COMPANY_ID)]],
        {'fields': ['id', 'name', 'list_price']}
    )
    
    print(f"{'Template ID':<12} {'Name':<20} {'List Price':<10}")
    print("-" * 45)
    for t in templates:
        print(f"{t['id']:<12} {t['name']:<20} {t['list_price']:<10}")
        
        # Search for variants
        variants = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'product.product', 'search_read',
            [[('product_tmpl_id', '=', t['id'])]],
            {'fields': ['id', 'display_name', 'lst_price', 'price_extra']}
        )
        
        for v in variants:
            print(f"  -> Variant {v['id']}: {v['display_name']:<30} LST: {v['lst_price']:<10} Extra: {v.get('price_extra'):<10}")

if __name__ == "__main__":
    check_all_prices()
