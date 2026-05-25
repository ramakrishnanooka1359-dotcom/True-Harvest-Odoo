import sys
import random
from fastapi.testclient import TestClient
from main import app
from odoo_client import models as odoo_models, uid as odoo_uid
from config import ODOO_DB, ODOO_API_KEY, TRUE_HARVEST_COMPANY_ID

client = TestClient(app)

def verify_odoo_partner(partner_id: int, expected_role: str):
    """Utility to query Odoo and verify the auto-provisioned partner has correct fields and company."""
    print(f"Verifying partner {partner_id} in Odoo...")
    partner = odoo_models.execute_kw(
        ODOO_DB, odoo_uid, ODOO_API_KEY,
        'res.partner', 'read',
        [[partner_id]],
        {'fields': ['name', 'email', 'company_id', 'supplier_rank', 'category_id']}
    )[0]
    
    print(f"-> Odoo Partner Name: {partner['name']}")
    print(f"-> Odoo Company ID: {partner['company_id']}")
    print(f"-> Odoo Supplier Rank: {partner['supplier_rank']}")
    print(f"-> Odoo Tags (Category): {partner['category_id']}")
    
    # Assert company_id is strictly locked to Company 3 (True Harvest)
    assert partner['company_id'][0] == TRUE_HARVEST_COMPANY_ID, "FAILED: Company isolation breached!"
    print("-> [OK] STRICT COMPANY ISOLATION PASSED!")
    
    if expected_role == 'vendor':
        assert partner['supplier_rank'] > 0, "FAILED: Supplier rank was not set!"
        print("-> [OK] SUPPLIER RANK PASSED!")
    elif expected_role == 'delivery_boy':
        assert len(partner['category_id']) > 0, "FAILED: Delivery boy tag was not set!"
        print("-> [OK] DELIVERY BOY TAGGING PASSED!")

def test_vendor_lifecycle():
    print("\n=============================================")
    print("TESTING DECOUPLED VENDOR LIFECYCLE...")
    print("=============================================")
    
    # Generate a unique email to avoid constraint collisions
    rand_id = random.randint(1000, 9999)
    email = f"vendor_{rand_id}@trueharvest.com"
    password = "secure_password_123"
    
    # 1. Register the Vendor
    print(f"1. Registering local Vendor with email: {email}...")
    reg_response = client.post(
        "/auth/register",
        json={
            "name": f"Green Earth Fruits {rand_id}",
            "email": email,
            "password": password,
            "phone": "+15550199",
            "role": "vendor",
            "store_name": f"Green Earth Store {rand_id}",
            "store_address": "456 Organic Way",
            "odoo_location_id": 12  # Dummy location
        }
    )
    print(f"Status: {reg_response.status_code}")
    assert reg_response.status_code == 200, f"Registration failed: {reg_response.text}"
    reg_data = reg_response.json()
    odoo_partner_id = reg_data["odoo_partner_id"]
    print(f"-> Local user ID created: {reg_data['user_id']}")
    print(f"-> Odoo partner ID created: {odoo_partner_id}")
    
    # 2. Verify Odoo Partner
    verify_odoo_partner(odoo_partner_id, 'vendor')
    
    # 3. Test Login
    print("2. Testing local authentication login...")
    login_response = client.post(
        "/auth/login",
        json={"username": email, "password": password}
    )
    print(f"Status: {login_response.status_code}")
    assert login_response.status_code == 200, f"Login failed: {login_response.text}"
    login_data = login_response.json()
    print("-> [OK] LOGIN SUCCESSFUL!")
    print(f"-> Token generated: {login_data['access_token'][:30]}...")
    print(f"-> Logged in as: {login_data['name']} (Role: {login_data['role']})")
    assert login_data["role"] == "vendor"
    assert login_data["odoo_partner_id"] == odoo_partner_id

def test_delivery_boy_lifecycle():
    print("\n=============================================")
    print("TESTING DECOUPLED DELIVERY BOY LIFECYCLE...")
    print("=============================================")
    
    rand_id = random.randint(1000, 9999)
    email = f"rider_{rand_id}@trueharvest.com"
    password = "rider_password_456"
    
    # 1. Register the Delivery Boy
    print(f"1. Registering local Delivery Boy with email: {email}...")
    reg_response = client.post(
        "/auth/register",
        json={
            "name": f"Speedy Courier {rand_id}",
            "email": email,
            "password": password,
            "phone": "+15550299",
            "role": "delivery_boy",
            "vehicle_type": "bike",
            "license_plate": f"RIDER-{rand_id}"
        }
    )
    print(f"Status: {reg_response.status_code}")
    assert reg_response.status_code == 200, f"Registration failed: {reg_response.text}"
    reg_data = reg_response.json()
    odoo_partner_id = reg_data["odoo_partner_id"]
    print(f"-> Local user ID created: {reg_data['user_id']}")
    print(f"-> Odoo partner ID created: {odoo_partner_id}")
    
    # 2. Verify Odoo Partner
    verify_odoo_partner(odoo_partner_id, 'delivery_boy')
    
    # 3. Test Login
    print("2. Testing local authentication login...")
    login_response = client.post(
        "/auth/login",
        json={"username": email, "password": password}
    )
    print(f"Status: {login_response.status_code}")
    assert login_response.status_code == 200, f"Login failed: {login_response.text}"
    login_data = login_response.json()
    print("-> [OK] LOGIN SUCCESSFUL!")
    print(f"-> Token generated: {login_data['access_token'][:30]}...")
    print(f"-> Logged in as: {login_data['name']} (Role: {login_data['role']})")
    assert login_data["role"] == "delivery_boy"
    assert login_data["odoo_partner_id"] == odoo_partner_id

if __name__ == "__main__":
    try:
        test_vendor_lifecycle()
        test_delivery_boy_lifecycle()
        print("\n[SUCCESS] ALL ARCHITECTURAL DECOUPLED AUTH & SYNC TESTS PASSED SUCCESSFULLY!")
        sys.exit(0)
    except AssertionError as e:
        print(f"\n[FAIL] Assertion Failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[FAIL] Test Failed: {e}")
        sys.exit(1)
