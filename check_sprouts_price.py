from odoo_client import models, uid
from config import ODOO_DB, ODOO_API_KEY, TRUE_HARVEST_COMPANY_ID

def check_sprouts():
    # Search for sprouts template
    templates = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'product.template', 'search_read',
        [[('name', '=', 'sprouts'), ('company_id', '=', TRUE_HARVEST_COMPANY_ID)]],
        {'fields': ['id', 'name', 'list_price']}
    )
    
    print("--- Product Templates ---")
    for t in templates:
        print(f"ID: {t['id']}, Name: {t['name']}, list_price: {t['list_price']}")
        
        # Search for variants
        variants = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'product.product', 'search_read',
            [[('product_tmpl_id', '=', t['id'])]],
            {'fields': ['id', 'display_name', 'lst_price', 'price_extra']}
        )
        
        print(f"  --- Variants for Template {t['id']} ---")
        for v in variants:
            print(f"  ID: {v['id']}, Name: {v['display_name']}, lst_price: {v['lst_price']}, price_extra: {v.get('price_extra')}")
            
            # Check ptav (product template attribute value) for price_extra
            ptav_ids = models.execute_kw(
                ODOO_DB, uid, ODOO_API_KEY,
                'product.template.attribute.value', 'search_read',
                [[('product_tmpl_id', '=', t['id'])]],
                {'fields': ['id', 'display_name', 'price_extra']}
            )
            print("    --- PTAVs ---")
            for ptav in ptav_ids:
                print(f"    ID: {ptav['id']}, Name: {ptav['display_name']}, price_extra: {ptav['price_extra']}")

if __name__ == "__main__":
    check_sprouts()
