from fastapi import APIRouter, HTTPException, Response
from odoo_client import models, uid
from config import ODOO_DB, ODOO_API_KEY, TRUE_HARVEST_COMPANY_ID
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

class ProductVariantCreate(BaseModel):
    name: str
    price: float = 0.0
    stock: float = 0.0

class ProductCreate(BaseModel):
    name: str
    category_id: Optional[int] = None
    category_name: Optional[str] = "Other"
    list_price: float = 0.0
    qty_available: float = 0.0
    variants: Optional[list[ProductVariantCreate]] = None

class VariantUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[float] = None
    quantity: Optional[float] = None
    is_new: Optional[bool] = False

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    category_name: Optional[str] = None
    price: Optional[float] = None
    variants: Optional[list[VariantUpdate]] = None




# -------------------------------
# ATTRIBUTE HELPERS
# -------------------------------

def get_or_create_attribute(name="Size"):
    attribute_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'product.attribute', 'search',
        [[('name', '=', name)]]
    )

    if attribute_ids:
        return attribute_ids[0]

    return models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'product.attribute', 'create',
        [{'name': name, 'create_variant': 'always'}]
    )


def get_or_create_attribute_value(attribute_id, value_name):
    value_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'product.attribute.value', 'search',
        [[
            ('name', '=', value_name),
            ('attribute_id', '=', attribute_id)
        ]]
    )

    if value_ids:
        return value_ids[0]

    return models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'product.attribute.value', 'create',
        [{
            'name': value_name,
            'attribute_id': attribute_id
        }]
    )


# -------------------------------
# STOCK HELPERS
# -------------------------------

def update_product_stock(product_tmpl_id, quantity):
    """
    Sets the physical stock for a product in the company's main warehouse.
    Uses inventory_quantity_auto_apply for Odoo 15+ compatibility and reliability.
    """
    if quantity < 0:
        return False

    try:
        # 1. Get the first warehouse/location for the company
        warehouses = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'stock.warehouse', 'search_read',
            [[('company_id', '=', TRUE_HARVEST_COMPANY_ID)]],
            {'fields': ['lot_stock_id'], 'limit': 1}
        )
        
        if not warehouses:
            return False
            
        location_id = warehouses[0]['lot_stock_id'][0]

        # 2. Get the product.product ID for the template
        product_ids = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'product.product', 'search',
            [[('product_tmpl_id', '=', product_tmpl_id)]],
            {'limit': 1}
        )

        if not product_ids:
            return False
        
        product_id = product_ids[0]
        
        # 3. Search for existing quant
        quant_ids = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'stock.quant', 'search',
            [[
                ('product_id', '=', product_id),
                ('location_id', '=', location_id)
            ]]
        )
        
        if quant_ids:
            # Update existing
            models.execute_kw(
                ODOO_DB, uid, ODOO_API_KEY,
                'stock.quant', 'write',
                [quant_ids, {'inventory_quantity': float(quantity)}]
            )
            final_ids = quant_ids
        else:
            # Create new
            new_id = models.execute_kw(
                ODOO_DB, uid, ODOO_API_KEY,
                'stock.quant', 'create',
                [{
                    'product_id': product_id,
                    'location_id': location_id,
                    'inventory_quantity': float(quantity)
                }]
            )
            final_ids = [new_id]
            
        # Apply adjustment
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'stock.quant', 'action_apply_inventory',
            [final_ids]
        )
        return True
    except Exception as e:
        print(f"Error updating stock: {e}")
        return False


# -------------------------------
# MAIN FUNCTION
# -------------------------------

def create_product_with_variants(product_name, variant_data_list, category_id=None):
    """
    Creates a product template and multiple variants with specific prices and stock levels.
    variant_data_list: list of dicts like {'name': '500 ml', 'price': 40, 'stock': 10}
    """
    attribute_id = get_or_create_attribute()

    # 1️⃣ Check if product exists
    existing_products = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'product.template', 'search',
        [[
            ('name', '=', product_name),
            ('company_id', '=', TRUE_HARVEST_COMPANY_ID)
        ]]
    )

    if existing_products:
        product_tmpl_id = existing_products[0]
        # Update category if provided
        if category_id:
            models.execute_kw(
                ODOO_DB, uid, ODOO_API_KEY,
                'product.template', 'write',
                [[product_tmpl_id], {'categ_id': category_id}]
            )
    else:
        product_tmpl_id = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'product.template', 'create',
            [{
                'name': product_name,
                'list_price': 0,
                'type': 'product',
                'company_id': TRUE_HARVEST_COMPANY_ID,
                'categ_id': category_id or 1
            }]
        )

    # 2️⃣ Get all attribute values
    value_ids = []
    for var in variant_data_list:
        value_id = get_or_create_attribute_value(attribute_id, var['name'])
        value_ids.append(value_id)

    # 3️⃣ Check existing attribute line
    existing_lines = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'product.template.attribute.line', 'search',
        [[
            ('product_tmpl_id', '=', product_tmpl_id),
            ('attribute_id', '=', attribute_id)
        ]]
    )

    if existing_lines:
        # Update existing line (NO DUPLICATION)
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'product.template.attribute.line', 'write',
            [[existing_lines[0]], {
                'value_ids': [(6, 0, value_ids)]
            }]
        )
    else:
        # Create new line
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'product.template.attribute.line', 'create',
            [{
                'product_tmpl_id': product_tmpl_id,
                'attribute_id': attribute_id,
                'value_ids': [(6, 0, value_ids)]
            }]
        )

    # 4️⃣ Update price_extra correctly
    ptav_records = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'product.template.attribute.value', 'search_read',
        [[('product_tmpl_id', '=', product_tmpl_id)]],
        {'fields': ['id', 'product_attribute_value_id']}
    )

    for ptav in ptav_records:
        value_id = ptav['product_attribute_value_id'][0]
        value_data = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'product.attribute.value', 'read',
            [[value_id], ['name']]
        )[0]
        value_name = value_data['name']
        # Find matching variant data
        match = next((v for v in variant_data_list if v['name'] == value_name), None)
        if match:
            # Set variant price extra
            # We subtract the current template list_price to ensure the total lst_price 
            # equals what the user provided in the list.
            current_tmpl = models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'product.template', 'read', [[product_tmpl_id], ['list_price']])[0]
            tmpl_price = current_tmpl.get('list_price', 0)
            
            models.execute_kw(
                ODOO_DB, uid, ODOO_API_KEY,
                'product.template.attribute.value', 'write',
                [[ptav['id']], {
                    'price_extra': float(match.get('price', 0)) - tmpl_price
                }]
            )
            
            # Now find the product.product for this specific configuration and update stock
            p_variant_ids = models.execute_kw(
                ODOO_DB, uid, ODOO_API_KEY,
                'product.product', 'search',
                [[
                    ('product_tmpl_id', '=', product_tmpl_id),
                    ('product_template_attribute_value_ids', 'in', [ptav['id']])
                ]]
            )
            if p_variant_ids and match.get('stock', 0) > 0:
                update_product_stock_by_variant(p_variant_ids[0], match['stock'])

    return product_tmpl_id

    return product_tmpl_id


# Category mapping
# We'll pull these dynamically where possible, but keep a fall-back map
CATEGORY_MAP = {
    'Vegetables': 1,
    'Fruits': 2,
    'Dairy': 3,
    'Grains': 4,
    'Other': 5
}
REV_CATEGORY_MAP = {v: k for k, v in CATEGORY_MAP.items()}

def get_category_id(name):
    # Try to find a matching category by name in Odoo
    category = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'product.category', 'search_read',
        [[('name', '=', name)]],
        {'fields': ['id'], 'limit': 1}
    )
    if category:
        return category[0]['id']
    
    # Create it if it doesn't exist
    try:
        new_cat_id = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'product.category', 'create',
            [{'name': name}]
        )
        return new_cat_id
    except:
        return CATEGORY_MAP.get(name, 1)

@router.get("/products")
def fetch_products():
    product_templates = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'product.template', 'search_read',
        [[
            ('type', '=', 'product'),
            ('company_id', '=', TRUE_HARVEST_COMPANY_ID)
        ]],
        # Use image_128 (thumbnail, ~1-2KB) just to detect has_image.
        # image_1920 is fetched on demand via the /image endpoint.
        {'fields': ['id', 'name', 'type', 'categ_id', 'image_128', 'list_price']}
    )

    for template in product_templates:
        # has_image: True if a thumbnail exists (means the full image also exists)
        template['has_image'] = bool(template.get('image_128'))
        if 'image_128' in template:
            del template['image_128']  # Don't send even thumbnail in list response
        # Map category ID to name
        categ_info = template.get('categ_id')

        # 🔹 Dynamic Categorization Fallback
        name_lower = template.get('name', '').lower()
        if any(d in name_lower for d in ['milk', 'paneer', 'curd', 'ghee', 'dairy']):
            template['category'] = 'Dairy'
        elif any(v in name_lower for v in ['veg', 'spinach', 'potato', 'tomato', 'onion', 'sprouts']):
            template['category'] = 'Vegetables'
        elif categ_info and isinstance(categ_info, (list, tuple)):
            cid = categ_info[0]
            template['category'] = REV_CATEGORY_MAP.get(cid, categ_info[1])
        else:
            template['category'] = 'Other'

        # Ensure categ_id is mapped clearly for the frontend
        if categ_info and isinstance(categ_info, (list, tuple)):
            template['category_id'] = categ_info[0]
            template['category_name'] = categ_info[1]
        
        template['price'] = template.get('list_price', 0)

        variants = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'product.product', 'search_read',
            [[
                ['product_tmpl_id', '=', template['id']],
                ['active', '=', True]
            ]],
            # Use image_128 just to detect has_image; full image via /image endpoint
            {'fields': ['id', 'display_name', 'lst_price', 'qty_available', 'default_code', 'image_128']}
        )

        # 🔹 Clean response for frontend
        for v in variants:
            v["name"] = v.pop("display_name")
            v["price"] = v.pop("lst_price")
            v["has_image"] = bool(v.get('image_128'))
            if 'image_128' in v:
                del v['image_128']

        template['variants'] = variants

    return product_templates


# ⚠️ CRITICAL ROUTE ORDER:
# /products/variants/{variant_id}/image MUST be declared BEFORE
# /products/{product_id} — otherwise FastAPI greedily matches "variants"
# as the product_id string parameter and fails to parse it as an int.

@router.get("/products/variants/{variant_id}/image")
def get_variant_image(variant_id: int):
    """
    Returns the Base64-encoded image for a specific product variant (product.product).
    Falls back to the template image if no variant-specific image is set.
    MUST be declared before /products/{product_id} to avoid route conflict.
    """
    results = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'product.product', 'search_read',
        [[('id', '=', variant_id), ('active', '=', True)]],
        {'fields': ['id', 'display_name', 'image_variant_1920', 'image_1920', 'product_tmpl_id'], 'limit': 1}
    )

    if not results:
        raise HTTPException(status_code=404, detail="Variant not found")

    variant = results[0]
    image_b64 = variant.get('image_variant_1920') or variant.get('image_1920')

    return {
        "variant_id": variant_id,
        "name": variant['display_name'],
        "product_template_id": variant['product_tmpl_id'][0] if variant.get('product_tmpl_id') else None,
        "has_image": bool(image_b64),
        "image_base64": image_b64 or None
    }


@router.patch("/products/variants/{variant_id}")
def update_variant(variant_id: int, updates: VariantUpdate):
    """
    Updates price and/or stock quantity for a specific product variant.
    """
    results = {}
    
    # 1. Update Price if provided
    if updates.price is not None:
        try:
            models.execute_kw(
                ODOO_DB, uid, ODOO_API_KEY,
                'product.product', 'write',
                [[variant_id], {'lst_price': float(updates.price)}]
            )
            results['price'] = "Updated"
        except Exception as e:
            results['price'] = f"Error: {str(e)}"

    # 2. Update Quantity if provided
    if updates.quantity is not None:
        success = update_product_stock_by_variant(variant_id, updates.quantity)
        results['quantity'] = "Updated" if success else "Failed to update stock"

    if not results:
        raise HTTPException(status_code=400, detail="No update data provided")

    return {
        "variant_id": variant_id,
        "updates": results
    }


@router.get("/products/{product_id}")
def fetch_single_product(product_id: int):

    # 🔹 Get product template
    templates = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'product.template', 'search_read',
        [[
            ('id', '=', product_id),
            ('type', '=', 'product'),
            ('company_id', '=', TRUE_HARVEST_COMPANY_ID)
        ]],
        # Use image_128 just to detect has_image
        {'fields': ['id', 'name', 'type', 'categ_id', 'image_128']}
    )

    if not templates:
        raise HTTPException(status_code=404, detail="Product not found")

    template = templates[0]
    template['has_image'] = bool(template.get('image_128'))
    if 'image_128' in template:
        del template['image_128']

    # 🔹 Get variants
    variants = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'product.product', 'search_read',
        [[
            ['product_tmpl_id', '=', template['id']],
            ['active', '=', True]
        ]],
        {
            'fields': [
                'id',
                'display_name',
                'lst_price',
                'qty_available',
                'default_code',
                'image_128'  # thumbnail only - full image fetched via /image endpoint
            ]
        }
    )

    # 🔹 Clean response
    for v in variants:
        v["name"] = v.pop("display_name")
        v["price"] = v.pop("lst_price")
        v["has_image"] = bool(v.get('image_128'))
        if 'image_128' in v:
            del v['image_128']

    # Map category ID to name
    categ_info = template.get('categ_id')

    # 🔹 Dynamic Categorization Fallback
    name_lower = template.get('name', '').lower()
    if any(d in name_lower for d in ['milk', 'paneer', 'curd', 'ghee', 'dairy']):
        template['category'] = 'Dairy'
    elif any(v in name_lower for v in ['veg', 'spinach', 'potato', 'tomato', 'onion', 'sprouts']):
        template['category'] = 'Vegetables'
    elif categ_info and isinstance(categ_info, (list, tuple)):
        cid = categ_info[0]
        template['category'] = REV_CATEGORY_MAP.get(cid, categ_info[1])
    else:
        template['category'] = 'Other'

    template['variants'] = variants
    return template


@router.patch("/products/{product_id}")
def update_product(product_id: int, updates: ProductUpdate):
    """
    Updates a product template and handles adding new variants.
    """
    try:
        update_data = {}
        if updates.name:
            update_data['name'] = updates.name
        if updates.category_name:
            update_data['categ_id'] = get_category_id(updates.category_name) or 1
        if updates.price is not None:
            # When updating price at the template level, we set the base price.
            # To avoid doubling for variants, we should ideally adjust variant extras,
            # but for simplicity and consistency with Odoo's usual behavior, 
            # we'll just update list_price. However, if there's only one variant
            # (common for True Harvest items like sprouts), we ensure its extra is 0.
            update_data['list_price'] = float(updates.price)
            
            # Auto-align: if multiple variants exist, we might want to be careful,
            # but for now, we'll zero out any price_extra that exactly matches the old price 
            # if it's the only variant.
            
        if update_data:
            models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'product.template', 'write', [[product_id], update_data])
            
            if updates.price is not None:
                # If we've just updated the template price, check for variants 
                # and adjust their extras so they don't double up.
                ptav_records = models.execute_kw(
                    ODOO_DB, uid, ODOO_API_KEY,
                    'product.template.attribute.value', 'search',
                    [[('product_tmpl_id', '=', product_id)]]
                )
                if ptav_records and len(ptav_records) == 1:
                    # Single variant: set its extra to 0 so its total price IS the template price
                    models.execute_kw(
                        ODOO_DB, uid, ODOO_API_KEY, 
                        'product.template.attribute.value', 'write', 
                        [ptav_records, {'price_extra': 0.0}]
                    )

        # Handle new variants if provided
        if updates.variants:
            new_variants = [v for v in updates.variants if v.is_new]
            if new_variants:
                attribute_id = get_or_create_attribute()
                for v in new_variants:
                    value_id = get_or_create_attribute_value(attribute_id, v.name)
                    
                    # Add to template attribute line
                    line_ids = models.execute_kw(
                        ODOO_DB, uid, ODOO_API_KEY, 'product.template.attribute.line', 'search',
                        [[('product_tmpl_id', '=', product_id), ('attribute_id', '=', attribute_id)]]
                    )
                    
                    if line_ids:
                        # Append to existing line
                        line_id = line_ids[0]
                        line = models.execute_kw(
                            ODOO_DB, uid, ODOO_API_KEY, 'product.template.attribute.line', 'read',
                            [[line_id], ['value_ids']]
                        )[0]
                        existing_values = line['value_ids']
                        if value_id not in existing_values:
                            models.execute_kw(
                                ODOO_DB, uid, ODOO_API_KEY, 'product.template.attribute.line', 'write',
                                [[line_id], {'value_ids': [(4, value_id)]}] # (4, ID) is Many2many link in Odoo
                            )
                    else:
                        # Create new line
                        models.execute_kw(
                            ODOO_DB, uid, ODOO_API_KEY, 'product.template.attribute.line', 'create',
                            [{'product_tmpl_id': product_id, 'attribute_id': attribute_id, 'value_ids': [(6, 0, [value_id])]}]
                        )

                # Now update prices and stock for new variants
                ptav_records = models.execute_kw(
                    ODOO_DB, uid, ODOO_API_KEY,
                    'product.template.attribute.value', 'search_read',
                    [[('product_tmpl_id', '=', product_id)]],
                    {'fields': ['product_attribute_value_id', 'price_extra']}
                )

                for var in new_variants:
                    match_ptav = next((p for p in ptav_records if p['product_attribute_value_id'][1] == var.name), None)
                    if match_ptav:
                        # Update price_extra
                        models.execute_kw(
                            ODOO_DB, uid, ODOO_API_KEY, 'product.template.attribute.value', 'write',
                            [[match_ptav['id']], {'price_extra': float(var.price or 0)}]
                        )
                        
                        # Apply stock
                        p_variant_ids = models.execute_kw(
                            ODOO_DB, uid, ODOO_API_KEY, 'product.product', 'search',
                            [[('product_tmpl_id', '=', product_id), ('product_template_attribute_value_ids', 'in', [match_ptav['id']]), ('active', '=', True)]]
                        )
                        if p_variant_ids and var.quantity and var.quantity > 0:
                            update_product_stock_by_variant(p_variant_ids[0], var.quantity)

        return {"message": "Product updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/create-true-harvest-products")
def create_true_harvest_products(product: ProductCreate):
    """
    Creates a product and its variants if provided.
    """
    cat_id = product.category_id
    if not cat_id and product.category_name:
        cat_id = get_category_id(product.category_name)

    if product.variants and len(product.variants) > 0:
        # Multi-variant creation
        v_list = [v.dict() for v in product.variants]
        tmpl_id = create_product_with_variants(product.name, v_list, category_id=cat_id)
        return {"message": "Product with variants created successfully", "id": tmpl_id}
    
    # 1️⃣ Check if product template exists (Simple creation)
    existing_products = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'product.template', 'search',
        [[
            ('name', '=', product.name),
            ('company_id', '=', TRUE_HARVEST_COMPANY_ID)
        ]]
    )

    if existing_products:
        product_tmpl_id = existing_products[0]
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'product.template', 'write',
            [[product_tmpl_id], {
                'list_price': product.list_price,
                'categ_id': cat_id or 1
            }]
        )
    else:
        product_tmpl_id = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'product.template', 'create',
            [{
                'name': product.name,
                'list_price': product.list_price,
                'type': 'product',
                'company_id': TRUE_HARVEST_COMPANY_ID,
                'categ_id': cat_id or 1
            }]
        )

    # 2️⃣ Update Stock (Initial Qty)
    if product.qty_available > 0:
        update_product_stock(product_tmpl_id, product.qty_available)

    return {
        "message": "Product created successfully", 
        "id": product_tmpl_id
    }

@router.patch("/products/{id}/archive")
def archive_product(id: int):
    """
    Safely archives a product template.
    """
    try:
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY, 
            'product.template', 'write', 
            [[id], {'active': False}]
        )
        return {"message": "Product archived successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to archive product: {str(e)}")

@router.patch("/products/variants/{id}/archive")
def archive_variant(id: int):
    """
    Safely archives a specific product variant.
    """
    try:
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY, 
            'product.product', 'write', 
            [[id], {'active': False}]
        )
        return {"message": "Variant archived successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to archive variant: {str(e)}")


@router.post("/seed-true-harvest-data")
def seed_true_harvest_data():
    """
    Original hardcoded seeder preserved here for reference/utility.
    """
    dairy_cat = get_category_id("Dairy")
    veg_cat = get_category_id("Vegetables")
    
    create_product_with_variants("Milk", {
        "500 ml": 40,
        "1 L": 80
    }, category_id=dairy_cat)

    create_product_with_variants("Ghee", {
        "500 ml": 400,
        "1 L": 800
    }, category_id=dairy_cat)

    create_product_with_variants("Paneer", {
        "500 g": 200,
        "1 kg": 400
    }, category_id=dairy_cat)

    create_product_with_variants("Curd", {
        "500 g": 40,
        "1 kg": 80
    }, category_id=dairy_cat)

    create_product_with_variants("sprouts", {
        "250 g": 40
    }, category_id=veg_cat)

    return {"message": "True Harvest products seeded and categorized correctly"}

@router.post("/fix-categories")
def fix_categories():
    """
    Fixes incorrectly categorized dairy products.
    """
    dairy_cat = get_category_id("Dairy")
    dairy_items = ["Milk", "Paneer", "Curd", "Ghee", "Butter", "Cheese"]
    
    # Find these products
    p_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'product.template', 'search',
        [[('name', 'in', dairy_items), ('company_id', '=', TRUE_HARVEST_COMPANY_ID)]]
    )
    
    if p_ids:
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'product.template', 'write',
            [p_ids, {'categ_id': dairy_cat}]
        )
        
    return {"message": f"Fixed {len(p_ids)} products to Dairy category"}


# -------------------------------
# IMAGE ENDPOINTS
# /products/variants/{variant_id}/image is declared ABOVE near line 337
# to avoid route conflict with /products/{product_id}.
# Only /products/{product_id}/image is declared here.
# -------------------------------


@router.get("/products/{product_id}/image")
def get_product_image(product_id: int):
    """
    Returns the Base64-encoded image for a product template.
    (Variant image route is declared earlier in the file, before /products/{product_id}.)
    """
    results = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'product.template', 'search_read',
        [[
            ('id', '=', product_id),
            ('company_id', '=', TRUE_HARVEST_COMPANY_ID)
        ]],
        {'fields': ['id', 'name', 'image_1920'], 'limit': 1}
    )

    if not results:
        raise HTTPException(status_code=404, detail="Product not found")

    product = results[0]
    image_b64 = product.get('image_1920')

    return {
        "product_id": product_id,
        "name": product['name'],
        "has_image": bool(image_b64),
        "image_base64": image_b64 or None
    }


@router.post("/fix-stock-quantities")
def fix_stock_quantities():
    """
    Sets sensible stock quantities for all True Harvest products so they
    show as 'In Stock' in the customer storefront.
    Call this once after seeding products via POST /seed-true-harvest-data.
    """
    stock_map = {
        "Milk": 100,
        "Ghee": 50,
        "Paneer": 80,
        "Curd": 90,
        "sprouts": 60,
    }

    results = []
    for name, qty in stock_map.items():
        product_ids = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'product.template', 'search',
            [[('name', '=', name), ('company_id', '=', TRUE_HARVEST_COMPANY_ID)]]
        )
        if product_ids:
            tmpl_id = product_ids[0]
            # Get all variants for this template
            variant_ids = models.execute_kw(
                ODOO_DB, uid, ODOO_API_KEY,
                'product.product', 'search',
                [[('product_tmpl_id', '=', tmpl_id)]]
            )
            per_variant_qty = qty / max(len(variant_ids), 1)
            for vid in variant_ids:
                update_product_stock_by_variant(vid, per_variant_qty)
            results.append({"product": name, "template_id": tmpl_id, "variants_updated": len(variant_ids)})

    return {"message": "Stock quantities updated", "updated": results}


def update_product_stock_by_variant(product_id: int, quantity: float):
    """Sets stock for a specific product.product by ID."""
    try:
        warehouses = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'stock.warehouse', 'search_read',
            [[('company_id', '=', TRUE_HARVEST_COMPANY_ID)]],
            {'fields': ['lot_stock_id'], 'limit': 1}
        )
        if not warehouses:
            return False
        location_id = warehouses[0]['lot_stock_id'][0]

        quant_ids = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'stock.quant', 'search',
            [[('product_id', '=', product_id), ('location_id', '=', location_id)]]
        )

        if quant_ids:
            models.execute_kw(
                ODOO_DB, uid, ODOO_API_KEY,
                'stock.quant', 'write',
                [quant_ids, {'inventory_quantity': float(quantity)}]
            )
            final_ids = quant_ids
        else:
            new_id = models.execute_kw(
                ODOO_DB, uid, ODOO_API_KEY,
                'stock.quant', 'create',
                [{'product_id': product_id, 'location_id': location_id,
                  'inventory_quantity': float(quantity)}]
            )
            final_ids = [new_id]

        # Apply adjustment
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'stock.quant', 'action_apply_inventory',
            [final_ids]
        )
        return True
    except Exception as e:
        print(f"Stock update error for variant {product_id}: {e}")
        return False
