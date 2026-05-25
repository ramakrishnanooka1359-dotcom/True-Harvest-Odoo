import requests
import json

try:
    r = requests.get("http://localhost:8003/products")
    print(f"Status: {r.status_code}")
    data = r.json()
    print(json.dumps(data, indent=2))
except Exception as e:
    print(f"Error: {e}")
