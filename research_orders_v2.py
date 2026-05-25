from odoo_client import models, uid
from config import ODOO_DB, ODOO_API_KEY, TRUE_HARVEST_COMPANY_ID

# Get all fields of sale.order to find how to distinguish instant orders (on-demand)
fields = models.execute_kw(
    ODOO_DB, uid, ODOO_API_KEY,
    'sale.order', 'fields_get',
    [],
    {'attributes': ['string', 'help', 'type']}
)

# Print field names that might be relevant
relevant_keywords = ['type', 'on_demand', 'instant', 'subscription', 'recurring', 'delivery', 'kind', 'method']
for field_name, info in fields.items():
    if any(kw in field_name.lower() or kw in (info.get('string') or '').lower() for kw in relevant_keywords):
        print(f"{field_name}: {info.get('string')} ({info.get('type')})")

# Also check a few recent orders to see their values for these fields
recent_orders = models.execute_kw(
    ODOO_DB, uid, ODOO_API_KEY,
    'sale.order', 'search_read',
    [[('company_id', '=', TRUE_HARVEST_COMPANY_ID)]],
    {'fields': ['name', 'state', 'date_order'], 'limit': 10}
)

print("\nRecent Orders Sample:")
for order in recent_orders:
    # Also fetch the full data for one order to inspect all fields
    full_order = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.order', 'read',
        [[order['id']]]
    )[0]
    print(f"Order: {order['name']}, State: {order['state']}, Date: {order['date_order']}")
    # Print fields that have values and look like they could be related to "on-demand" vs "subscription"
    for k, v in full_order.items():
        if v and any(kw in k.lower() for kw in ['type', 'frequency', 'subscription', 'on_demand']):
            print(f"  {k}: {v}")
