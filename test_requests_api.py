import requests

API_BASE = "http://localhost:8003"
try:
    response = requests.get(f"{API_BASE}/orders?only_requests=true")
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Found {len(data)} requests.")
        for r in data:
            print(f"- {r['order_ref']} | {r['customer_name']} | {r['status']}")
    else:
        print(f"Error: {response.text}")
except Exception as e:
    print(f"Connection Error: {e}")
