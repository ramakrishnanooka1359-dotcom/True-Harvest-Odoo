from odoo_client import models, uid
from config import ODOO_DB, ODOO_API_KEY, TRUE_HARVEST_COMPANY_ID

def check_detailed_prices():
    # Search for all templates
    templates = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'product.template', 'search_read',
        [[('company_id', '=', TRUE_HARVEST_COMPANY_ID)]],
        {'fields': ['id', 'name', 'list_price']}
    )
    
    for t in templates:
        print(f"Template {t['id']}: {t['name']}")
        print(f"  List Price: {t['list_price']}")
        
        # Search for variants
        variants = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'product.product', 'search_read',
            [[('product_tmpl_id', '=', t['id'])]],
            {'fields': ['id', 'display_name', 'lst_price', 'price_extra']}
        )
        
        for v in variants:
            print(f"  Variant {v['id']}: {v['display_name']}")
            print(f"    lst_price: {v['lst_price']}")
            print(f"    price_extra (on variant): {v.get('price_extra')}")
            
            # Check the PTAVs for this variant
            read_res = models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'product.product', 'read', [[v['id']], ['product_template_attribute_value_ids']])
            if read_res:
                ptav_ids = models.execute_kw(
                    ODOO_DB, uid, ODOO_API_KEY,
                    'product.template.attribute.value', 'search_read',
                    [[('id', 'in', read_res[0]['product_template_attribute_value_ids'])]],
                    {'fields': ['id', 'display_name', 'price_extra']}
                )
                for ptav in ptav_ids:
                    print(f"    PTAV {ptav['id']}: {ptav['display_name']} -> price_extra: {ptav['price_extra']}")
        print("-" * 30)

if __name__ == "__main__":
    check_detailed_prices()
