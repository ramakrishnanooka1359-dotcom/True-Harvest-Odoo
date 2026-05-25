import xmlrpc.client
from config import ODOO_URL, ODOO_DB, ODOO_USERNAME, ODOO_API_KEY, TRUE_HARVEST_COMPANY_ID

def research_wizard():
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    uid = common.authenticate(ODOO_DB, ODOO_USERNAME, ODOO_API_KEY, {})
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
    
    # Get a picking to test with
    picking_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.picking', 'search',
        [[('picking_type_id.code', '=', 'outgoing'), ('state', '=', 'done'), ('company_id', '=', TRUE_HARVEST_COMPANY_ID)]],
        {'limit': 1}
    )
    
    if not picking_ids:
        print("No picking found to test with.")
        return
        
    picking_id = picking_ids[0]
    print(f"Testing with Picking ID: {picking_id}")
    
    # Try to get defaults for the wizard
    defaults = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.return.picking', 'default_get',
        [['picking_id', 'product_return_moves']],
        {'context': {'active_id': picking_id, 'active_model': 'stock.picking'}}
    )
    print(f"Defaults: {defaults}")
    
    # Create wizard with these defaults
    wizard_id = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.return.picking', 'create',
        [defaults],
        {'context': {'active_id': picking_id, 'active_model': 'stock.picking'}}
    )
    print(f"Wizard ID: {wizard_id}")
    
    # Inspect wizard lines
    wizard_data = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.return.picking', 'read',
        [[wizard_id]],
        {'fields': ['product_return_moves']}
    )
    print(f"Wizard Data: {wizard_data}")
    
    if wizard_data[0]['product_return_moves']:
        lines = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'stock.return.picking.line', 'read',
            [wizard_data[0]['product_return_moves']],
            {'fields': ['product_id', 'quantity']}
        )
        print(f"Wizard Lines: {lines}")
    else:
        print("Wizard Lines are EMPTY!")

if __name__ == "__main__":
    research_wizard()
