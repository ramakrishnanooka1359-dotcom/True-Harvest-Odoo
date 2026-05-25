from fastapi.testclient import TestClient
from main import app
from config import ODOO_USERNAME, ODOO_API_KEY
import sys

client = TestClient(app)

def test_login_success():
    print("\nTesting Login with valid credentials...")
    response = client.post(
        "/auth/login",
        json={"username": ODOO_USERNAME, "password": ODOO_API_KEY}
    )
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Token received: {data['access_token'][:20]}...")
        print(f"User Name: {data.get('name')}")
        print(f"User Email: {data.get('email')}")
        print(f"User Mobile: {data.get('mobile')}")
        
        # Verify fields are present
        assert "name" in data
        assert "email" in data
        assert "mobile" in data
        assert "phone" in data
        return True
    else:
        print(f"Error: {response.text}")
        return False

def test_login_failure():
    print("\nTesting Login with invalid credentials...")
    response = client.post(
        "/auth/login",
        json={"username": ODOO_USERNAME, "password": "wrong_password"}
    )
    print(f"Status: {response.status_code}")
    if response.status_code == 401:
        print("Success: 401 Unauthorized received as expected.")
        return True
    else:
        print(f"Error: Expected 401, got {response.status_code}")
        return False

if __name__ == "__main__":
    s1 = test_login_success()
    s2 = test_login_failure()
    
    if s1 and s2:
        print("\nAll auth tests passed!")
        sys.exit(0)
    else:
        print("\nSome auth tests failed.")
        sys.exit(1)
