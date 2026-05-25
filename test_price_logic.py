import requests
import json

BASE_URL = "http://localhost:8003" # Assuming backend runs on 8003 from metadata

def test_order_price():
    # 1. Fetch products to get the sprouts variant ID
    response = requests.get(f"{BASE_URL}/products")
    products = response.json()
    
    sprouts = next((p for p in products if p['name'].lower() == 'sprouts'), None)
    if not sprouts:
        print("Sprouts product not found in /products")
        return
        
    print(f"Product: {sprouts['name']}, Template Price: {sprouts['price']}")
    
    variant = sprouts['variants'][0]
    print(f"Variant: {variant['name']}, ID: {variant['id']}, Price in /products: {variant['price']}")
    
    # 2. Create an order
    order_data = {
        "customer_name": "Test Customer",
        "customer_email": "test@example.com",
        "lines": [
            {
                "product_id": variant['id'],
                "quantity": 1
            }
        ]
    }
    
    response = requests.post(f"{BASE_URL}/orders", json=order_data)
    if response.status_code != 200:
        print(f"Error creating order: {response.text}")
        return
        
    order_id = response.json()['order_id']
    print(f"Order created with ID: {order_id}")
    
    # 3. Check the order from /orders endpoint
    response = requests.get(f"{BASE_URL}/orders")
    orders = response.json()
    order = next((o for o in orders if o['id'] == order_id), None)
    
    if order:
        print(f"Order Ref: {order['order_ref']}, Total: {order['amount_total']}")
        for line in order['lines']:
            print(f"  Line: {line['product_name']}, Qty: {line['quantity']}, Price Unit: {line['price_unit']}")
    else:
        print("Order not found in /orders list")

if __name__ == "__main__":
    test_order_price()
