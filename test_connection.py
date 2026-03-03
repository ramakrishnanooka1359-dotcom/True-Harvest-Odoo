from odoo_client import uid, models
from config import ODOO_DB, ODOO_API_KEY

def test_connection():
    try:
        print(f"Authenticated with UID: {uid}")
        # Try to search for one product to verify models access
        product = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'product.template', 'search_count',
            [[]]
        )
        print(f"Connection successful. Found {product} products.")
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    test_connection()
