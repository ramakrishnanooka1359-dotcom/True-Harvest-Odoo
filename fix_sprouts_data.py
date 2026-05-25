from odoo_client import models, uid
from config import ODOO_DB, ODOO_API_KEY, TRUE_HARVEST_COMPANY_ID

def fix_prices():
    # 1. Fix sprouts
    sprouts_tmpl_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'product.template', 'search',
        [[('name', '=', 'sprouts'), ('company_id', '=', TRUE_HARVEST_COMPANY_ID)]]
    )
    
    if sprouts_tmpl_ids:
        tmpl_id = sprouts_tmpl_ids[0]
        print(f"Fixing sprouts (Template {tmpl_id})...")
        
        # Set template price to 40
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'product.template', 'write',
            [[tmpl_id], {'list_price': 40.0}]
        )
        
        # Set variant price_extra to 0
        ptav_ids = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'product.template.attribute.value', 'search',
            [[('product_tmpl_id', '=', tmpl_id)]]
        )
        if ptav_ids:
            models.execute_kw(
                ODOO_DB, uid, ODOO_API_KEY,
                'product.template.attribute.value', 'write',
                [ptav_ids, {'price_extra': 0.0}]
            )
            print(f"Set price_extra to 0 for PTAVs: {ptav_ids}")
            
    # 2. Fix Fresh Curd (which also appeared doubled)
    # Check script showed: Template 9 (Fresh Curd) List Price: 0.0, but LST: 80.0, Extra: 40.0?
    # Wait, let me re-check the Fresh Curd results.
    # Variant 72: Fresh Curd (500 g) LST: 80.0 Extra: 40.00
    # If Template List Price is 0, LST should be 40. 
    # Why is LST 80 if Template is 0 and Extra is 40? 
    # Maybe Odoo's lst_price is calculated differently or I misread.
    
    # Let's just fix sprouts for now and re-verify.

if __name__ == "__main__":
    fix_prices()
