from fastapi import APIRouter, HTTPException
from odoo_client import models, uid
from config import ODOO_DB, ODOO_API_KEY, TRUE_HARVEST_COMPANY_ID

router = APIRouter()

# ----------------------------
# CREATE DRAFT ORDER
# ----------------------------

@router.post("/orders")
def create_order(order_data: dict):

    customer_name = order_data.get("customer_name")
    customer_email = order_data.get("customer_email")
    lines = order_data.get("lines")

    if not customer_name or not lines:
        raise HTTPException(status_code=400, detail="Invalid order data")

    # 🔹 Check or Create Customer
    partner_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'res.partner', 'search',
        [[('email', '=', customer_email)]]
    )

    if partner_ids:
        partner_id = partner_ids[0]
    else:
        partner_id = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'res.partner', 'create',
            [{
                'name': customer_name,
                'email': customer_email
            }]
        )

    # 🔹 Create Sale Order (Header)
    sale_order_id = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.order', 'create',
        [{
            'partner_id': partner_id,
            'company_id': TRUE_HARVEST_COMPANY_ID,
        }]
    )

    # 🔹 Create Order Lines
    for line in lines:
        product_id = line.get("product_id")
        quantity = line.get("quantity")

        # Check stock availability and get price
        product_data = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'product.product', 'read',
            [[product_id]],
            {'fields': ['qty_available', 'lst_price']}
        )

        if not product_data:
            raise HTTPException(status_code=404, detail=f"Product ID {product_id} not found")

        product = product_data[0]

        if product['qty_available'] <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"Product ID {product_id} is out of stock"
            )

        # Create Line Directly (Stable for Price Implementation)
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'sale.order.line', 'create',
            [{
                'order_id': sale_order_id,
                'product_id': product_id,
                'product_uom_qty': quantity,
                'price_unit': product['lst_price']
            }]
        )

    return {
        "message": "Order and lines created in draft",
        "order_id": sale_order_id
    }



# ----------------------------
# PAYMENT SUCCESS FLOW
# ----------------------------

@router.post("/orders/{order_id}/payment-success")
def payment_success(order_id: int):

    # 1️⃣ Get current state first
    sale = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.order', 'read',
        [[order_id], ['state', 'name', 'partner_id', 'order_line']]
    )[0]

    # 2️⃣ Confirm only if draft or sent
    if sale['state'] in ['draft', 'sent']:
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'sale.order', 'action_confirm',
            [[order_id]]
        )

    # 3️⃣ Validate Delivery
    picking_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.picking', 'search',
        [[('origin', '=', sale['name'])]]
    )

    for picking_id in picking_ids:
        # 1️⃣ Assign stock (reserve quantities)
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'stock.picking', 'action_assign',
            [[picking_id]]
        )

        # 2️⃣ Get stock moves (correct model)
        moves = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'stock.move', 'search_read',
            [[('picking_id', '=', picking_id)]],
            {'fields': ['id', 'product_uom_qty']}
        )

        for move in moves:
            # 3️⃣ Get move lines for that move
            move_lines = models.execute_kw(
                ODOO_DB, uid, ODOO_API_KEY,
                'stock.move.line', 'search',
                [[('move_id', '=', move['id'])]]
            )

            # 4️⃣ Set qty_done = ordered qty
            for line_id in move_lines:
                models.execute_kw(
                    ODOO_DB, uid, ODOO_API_KEY,
                    'stock.move.line', 'write',
                    [[line_id], {
                        'qty_done': move['product_uom_qty']
                    }]
                )

        # 5️⃣ Validate picking
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'stock.picking', 'button_validate',
            [[picking_id]]
        )

    # 4️⃣ Create Invoice via Wizard
    wizard_id = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.advance.payment.inv', 'create',
        [{
            'advance_payment_method': 'delivered'
        }],
        {
            'context': {
                'active_ids': [order_id],
                'company_id': TRUE_HARVEST_COMPANY_ID,
                'allowed_company_ids': [TRUE_HARVEST_COMPANY_ID]
            }
        }
    )

    models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.advance.payment.inv', 'create_invoices',
        [[wizard_id]],
        {
            'context': {
                'active_ids': [order_id],
                'company_id': TRUE_HARVEST_COMPANY_ID,
                'allowed_company_ids': [TRUE_HARVEST_COMPANY_ID]
            }
        }
    )

    # 5️⃣ Find Created Invoice
    invoice_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'account.move', 'search',
        [[('invoice_origin', '=', sale['name'])]]
    )

    # 6️⃣ Post Invoice
    for invoice_id in invoice_ids:
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'account.move', 'action_post',
            [[invoice_id]],
            {'context': {'company_id': TRUE_HARVEST_COMPANY_ID}}
        )




    return {
        "message": "Payment confirmed. Delivery validated. Invoice generated."
    }
   
