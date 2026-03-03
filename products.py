from fastapi import APIRouter, HTTPException
from odoo_client import models, uid
from config import ODOO_DB, ODOO_API_KEY, TRUE_HARVEST_COMPANY_ID

router = APIRouter()




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
# MAIN FUNCTION
# -------------------------------

def create_product_with_variants(product_name, size_price_dict):
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
    else:
        product_tmpl_id = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'product.template', 'create',
            [{
                'name': product_name,
                'list_price': 0,
                'type': 'product',
                'company_id': TRUE_HARVEST_COMPANY_ID
            }]
        )

    # 2️⃣ Get all attribute values
    value_ids = []
    for size in size_price_dict.keys():
        value_id = get_or_create_attribute_value(attribute_id, size)
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

        if value_name in size_price_dict:
            models.execute_kw(
                ODOO_DB, uid, ODOO_API_KEY,
                'product.template.attribute.value', 'write',
                [[ptav['id']], {
                    'price_extra': size_price_dict[value_name]
                }]
            )

    return product_tmpl_id


@router.get("/products")
def fetch_products():
    product_templates = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'product.template', 'search_read',
        [[
            ('type', '=', 'product'),
            ('company_id', '=', TRUE_HARVEST_COMPANY_ID)
        ]],
        {'fields': ['id', 'name', 'type']}
    )

    for template in product_templates:
        variants = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'product.product', 'search_read',
            [[
                ['product_tmpl_id', '=', template['id']],
                ['active', '=', True]
            ]],
            {'fields': ['id', 'display_name', 'lst_price', 'qty_available', 'default_code']}
        )

        # 🔹 Clean response for frontend
        for v in variants:
            v["name"] = v.pop("display_name")
            v["price"] = v.pop("lst_price")

        template['variants'] = variants


    return product_templates


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
        {'fields': ['id', 'name', 'type']}
    )

    if not templates:
        raise HTTPException(status_code=404, detail="Product not found")

    template = templates[0]

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
                'default_code'
            ]
        }
    )

    # 🔹 Clean response
    for v in variants:
        v["name"] = v.pop("display_name")
        v["price"] = v.pop("lst_price")

    template["variants"] = variants

    return template


@router.post("/create-true-harvest-products")
def create_true_harvest_products():

    create_product_with_variants("Milk", {
        "500 ml": 40,
        "1 L": 80
    })

    create_product_with_variants("Ghee", {
        "500 ml": 400,
        "1 L": 800
    })

    create_product_with_variants("Paneer", {
        "500 g": 200,
        "1 kg": 400
    })

    create_product_with_variants("Curd", {
        "500 g": 40,
        "1 kg": 80
    })

    return {"message": "True Harvest products created successfully"}


