from odoo_client import models, uid
from config import ODOO_DB, ODOO_API_KEY

def sync_quant_companies():
    print("Fetching quants in virtual partner locations (ID 4 and 5) that have empty company settings...")
    quants = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.quant', 'search_read',
        [[
            ('location_id', 'in', [4, 5]),
            ('company_id', '=', False)
        ]],
        {'fields': ['id', 'location_id', 'product_id', 'company_id']}
    )
    
    print(f"Found {len(quants)} shared quants to analyze.")
    updated_count = 0
    
    for q in quants:
        quant_id = q['id']
        product_id = q['product_id'][0]
        product_name = q['product_id'][1]
        location_name = q['location_id'][1]
        
        # Read the product's company settings
        product = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'product.product', 'read',
            [[product_id]],
            {'fields': ['company_id']}
        )[0]
        
        product_company = product.get('company_id')
        if product_company:
            prod_company_id = product_company[0]
            prod_company_name = product_company[1]
            
            print(f"Aligning Quant {quant_id} (Product: '{product_name}' at '{location_name}') to Company '{prod_company_name}' (ID: {prod_company_id})...")
            
            # Update the quant's company_id directly in Odoo via write
            models.execute_kw(
                ODOO_DB, uid, ODOO_API_KEY,
                'stock.quant', 'write',
                [[quant_id], {'company_id': prod_company_id}]
            )
            updated_count += 1
            
    print(f"\nSuccessfully synchronized {updated_count} stock.quant records to their respective companies!")

if __name__ == "__main__":
    sync_quant_companies()
