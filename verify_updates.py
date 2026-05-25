import requests
import json

BASE_URL = "http://localhost:8003"

def test_update_variant(variant_id, price=None, quantity=None):
    url = f"{BASE_URL}/products/variants/{variant_id}"
    payload = {}
    if price is not None:
        payload["price"] = price
    if quantity is not None:
        payload["quantity"] = quantity
        
    print(f"Testing PATCH {url} with payload: {payload}")
    try:
        response = requests.patch(url, json=payload)
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # Curd (500g) variant ID is 72
    test_update_variant(72, price=45.0, quantity=55.0)
