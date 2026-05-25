import requests
import json

API_BASE = "http://localhost:8003"

def test_filtering():
    print("--- Testing Order Filtering ---")
    
    # 1. Fetch all orders
    print("\nFetching all orders...")
    res_all = requests.get(f"{API_BASE}/orders")
    all_orders = res_all.json()
    print(f"Total orders: {len(all_orders)}")
    
    # 2. Fetch instant orders
    print("\nFetching instant orders (?type=instant)...")
    res_instant = requests.get(f"{API_BASE}/orders?type=instant")
    instant_orders = res_instant.json()
    print(f"Found {len(instant_orders)} instant orders.")
    for o in instant_orders:
        print(f" - {o['order_ref']} | Customer: {o['customer_name']}")

    # 3. Fetch subscription orders
    print("\nFetching subscription orders (?type=subscription)...")
    res_sub = requests.get(f"{API_BASE}/orders?type=subscription")
    sub_orders = res_sub.json()
    print(f"Found {len(sub_orders)} subscription orders.")
    
    # 4. Verify no overlap (optional, depending on if any were tagged)
    instant_ids = {o['id'] for o in instant_orders}
    sub_ids = {o['id'] for o in sub_orders}
    overlap = instant_ids.intersection(sub_ids)
    
    if overlap:
        print(f"\n[WARNING] Found overlap: {overlap}")
    else:
        print("\n[SUCCESS] No overlap between instant and subscription orders.")

if __name__ == "__main__":
    try:
        test_filtering()
    except Exception as e:
        print(f"Error: {e}")
