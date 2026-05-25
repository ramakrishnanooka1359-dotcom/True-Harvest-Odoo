import requests
import json

BASE_URL = "http://localhost:8003"

def test_price_update_logic():
    # 1. Get current sprouts variant info
    response = requests.get(f"{BASE_URL}/products")
    sprouts = next((p for p in response.json() if p['name'].lower() == 'sprouts'), None)
    product_id = sprouts['id']
    print(f"Initial - Template Price: {sprouts['price']}, Variant Price: {sprouts['variants'][0]['price']}")
    
    # 2. Update price to 50 via Template PATCH
    update_data = {"price": 50.0}
    requests.patch(f"{BASE_URL}/products/{product_id}", json=update_data)
    
    # 3. Check results
    response = requests.get(f"{BASE_URL}/products")
    sprouts = next((p for p in response.json() if p['name'].lower() == 'sprouts'), None)
    print(f"After Update to 50 - Template Price: {sprouts['price']}, Variant Price: {sprouts['variants'][0]['price']}")
    
    if sprouts['variants'][0]['price'] == 50.0:
        print("✅ SUCCESS: Price updated correctly without doubling.")
    else:
        print(f"❌ FAILURE: Price doubled! Variant price is {sprouts['variants'][0]['price']}")

    # 4. Reset to 40
    requests.patch(f"{BASE_URL}/products/{product_id}", json={"price": 40.0})
    print("Reset sprouts to 40.")

if __name__ == "__main__":
    test_price_update_logic()
