import requests
import base64

BASE_URL = "http://localhost:8003"

def test_image_endpoints():
    print("--- Testing Image Endpoints ---")
    
    # 1. Get products to find an ID
    try:
        response = requests.get(f"{BASE_URL}/products")
        products = response.json()
        if not products:
            print("No products found to test with.")
            return
        
        product_id = products[0]['id']
        variant_id = products[0]['variants'][0]['id'] if products[0].get('variants') else None
        
        # 2. Test Template Image
        print(f"Testing Product Template Image (ID: {product_id})...")
        tmpl_res = requests.get(f"{BASE_URL}/products/{product_id}/image")
        tmpl_data = tmpl_res.json()
        print(f"Template Response: {tmpl_data.get('name')} | Has Image: {tmpl_data.get('has_image')}")
        
        # 3. Test Variant Image
        if variant_id:
            print(f"Testing Product Variant Image (ID: {variant_id})...")
            var_res = requests.get(f"{BASE_URL}/products/variants/{variant_id}/image")
            var_data = var_res.json()
            print(f"Variant Response: {var_data.get('name')} | Has Image: {var_data.get('has_image')}")
            
    except Exception as e:
        print(f"Error during testing: {e}")

if __name__ == "__main__":
    test_image_endpoints()
