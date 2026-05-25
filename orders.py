from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from pydantic import BaseModel
from datetime import date
from datetime import date
import re
from odoo_client import models, uid
from config import ODOO_DB, ODOO_API_KEY, TRUE_HARVEST_COMPANY_ID

router = APIRouter()

# ----------------------------
# MODELS
# ----------------------------

class ActionRequest(BaseModel):
    action_type: str # 'Cancel', 'Return', 'Replace'
    reason: str
    comment: Optional[str] = ""

# ----------------------------
# LIST ORDERS
# ----------------------------

@router.get("/deliveries")
def get_deliveries(target_date: str = None):
    """Fetch completed deliveries for a specific date."""
    today = target_date if target_date else date.today().isoformat()
    
    pickings = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.picking', 'search_read',
        [[
            ('state', '=', 'done'),
            ('date_done', '>=', f'{today} 00:00:00'),
            ('date_done', '<=', f'{today} 23:59:59'),
            ('company_id', '=', TRUE_HARVEST_COMPANY_ID),
            ('picking_type_id.code', '=', 'outgoing')
        ]],
        {'fields': ['id', 'name', 'partner_id', 'date_done', 'origin', 'state'], 'order': 'date_done desc'}
    )
    
    result = []
    for p in pickings:
        result.append({
            'id': p['name'],
            'odoo_id': p['id'],
            'rider': 'Delivery Partner', 
            'destination': p['partner_id'][1] if p['partner_id'] else 'Unknown',
            'status': 'Delivered',
            'urgency': 'Normal',
            'eta': 'Completed',
            'date': p['date_done'],
            'order_ref': p['origin'] or 'N/A'
        })
    
    return result


@router.get("/dispatch/packing-queue")
def get_packing_queue():
    """Fetch active orders waiting to be packed (draft/sent, excluding subscription masters)."""
    orders = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.order', 'search_read',
        [[
            ('state', 'in', ['draft', 'sent']),
            ('company_id', '=', TRUE_HARVEST_COMPANY_ID),
            ('origin', '!=', '[SUBSCRIPTION_MASTER]')
        ]],
        {
            'fields': ['id', 'name', 'partner_id', 'date_order', 'order_line'],
            'order': 'date_order asc'
        }
    )
    
    result = []
    for order in orders:
        # Check priority logic (e.g., based on origin or a specific field)
        # Assuming 'Normal' for now, or 'Priority' if it's an Instant Order
        is_instant = order.get('origin') == 'Instant Order'
        status = 'Priority' if is_instant else 'Normal'
        
        # Calculate items count based on order lines
        item_count = len(order['order_line']) if order['order_line'] else 0
        
        # Calculate rough wait time (time since order created)
        # Using a static string for now, could be calculated dynamically
        wait_time = "Processing"
        
        result.append({
            'odoo_id': order['id'],
            'id': order['name'],
            'order': f"Order {order['name']}",
            'customer': order['partner_id'][1] if order['partner_id'] else 'Unknown',
            'items': item_count,
            'time': wait_time,
            'status': status
        })
        
    return result



@router.get("/orders")
def list_orders(
    type: Optional[str] = Query(None, description="Filter by type: 'instant' or 'subscription'"),
    customer_email: Optional[str] = Query(None, description="Filter by customer email"),
    only_requests: Optional[bool] = Query(False, description="Filter for orders with pending requests")
):
    """Fetch sale orders for True Harvest from Odoo with status sync."""
    domain = [('company_id', '=', TRUE_HARVEST_COMPANY_ID)]
    
    if only_requests:
         # Find orders with specific "Requested" tags
         tag_ids = models.execute_kw(
             ODOO_DB, uid, ODOO_API_KEY,
             'crm.tag', 'search',
             [[('name', 'ilike', 'Requested')]]
         )
         if tag_ids:
             domain.append(('tag_ids', 'in', tag_ids))
         else:
             return [] # No tags found, so no requests
    
    if customer_email:
        # Find partner by email
        partner_ids = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'res.partner', 'search',
            [[('email', '=', customer_email), ('company_id', '=', False)]]
        )
        if partner_ids:
            domain.append(('partner_id', 'in', partner_ids))
        else:
            return [] # No partner found, no orders to return

    if type == 'instant':
        domain.append(('origin', 'ilike', 'Instant Order%'))
    elif type == 'subscription':
        domain.append(('origin', 'not ilike', 'Instant Order%'))
        domain.append(('origin', '!=', '[SUBSCRIPTION_MASTER]'))
    else:
        domain.append(('origin', '!=', '[SUBSCRIPTION_MASTER]'))

    orders = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.order', 'search_read',
        [domain],
        {
            'fields': ['id', 'name', 'partner_id', 'date_order', 'state', 'amount_total', 'order_line', 'origin', 'tag_ids', 'invoice_status'],
            'order': 'date_order desc',
            'limit': 200,
        }
    )

    result = []
    for order in orders:
        # Prepare basic Odoo state
        state_map = {
            'draft': 'Pending',
            'sent': 'Pending',
            'sale': 'Processing',
            'done': 'Delivered',
            'cancel': 'Cancelled',
        }
        status = state_map.get(order['state'], order['state'].capitalize())
        
        # 🔹 SMART STATUS DETECTION 🔹
        
        # 1. Check for Return Pickings
        return_pickings = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'stock.picking', 'search_read',
            [[('origin', '=', order['name']), ('picking_type_id.code', '=', 'incoming'), ('state', '!=', 'cancel')]],
            {'fields': ['state']}
        )
        if return_pickings:
            # If any return is done, mark as Returned
            if any(p['state'] == 'done' for p in return_pickings):
                status = 'Returned'
            else:
                status = 'Return In Progress'

        # 2. Check for Credit Notes (Refunds)
        # We only check if not already marked as Returned (or we can combine them)
        credit_notes = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'account.move', 'search_read',
            [[('invoice_origin', '=', order['name']), ('move_type', '=', 'out_refund'), ('state', '!=', 'cancel')]],
            {'fields': ['state']}
        )
        if credit_notes:
            if any(cn['state'] == 'posted' for cn in credit_notes):
                status = 'Refunded'

        # 3. Handle Tag Overrides (Customer Requests)
        # Requests should only override status if a real document (Return/Refund) doesn't exist yet
        if status in ['Delivered', 'Processing', 'Invoiced', 'Pending']:
            if order.get('tag_ids'):
                tags = models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'crm.tag', 'read', [order['tag_ids']], {'fields': ['name']})
                tag_names = [t['name'] for t in tags]
                # Prioritize latest request tag
                for requested in ['Replacement Requested', 'Return Requested', 'Cancel Requested']:
                    if requested in tag_names:
                        status = requested
                        break
        
        # 4. Refinement based on invoice (only if not returned/refunded)
        if status == 'Processing' and order.get('invoice_status') == 'invoiced':
            status = 'Invoiced'

        raw_date = order.get('date_order') or ''
        date_str = raw_date[:10] if raw_date else ''

        # Fetch lines to get product names
        lines = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'sale.order.line', 'read',
            [order['order_line']],
            {'fields': ['product_id', 'product_uom_qty', 'price_unit']}
        ) if order['order_line'] else []

        # Calculate summary fields for frontend
        summary_product = "No items"
        total_quantity = 0
        if lines:
            item_names = [line['product_id'][1] for line in lines if line['product_id']]
            total_quantity = sum(line.get('product_uom_qty', 0) for line in lines)
            summary_product = ", ".join(item_names) if item_names else "Unknown"

        result.append({
            'id': order['name'].replace('S', '').replace('O', '').lstrip('0'), # Friendly ID for dashboard
            'odoo_id': order['id'],
            'order_ref': order['name'],
            'customer_name': order['partner_id'][1] if order['partner_id'] else 'Unknown',
            'product': summary_product,
            'quantity': total_quantity,
            'date': date_str,
            'status': status,
            'amount_total': order['amount_total'],
            'order_type': 'Instant' if 'Instant Order' in (order.get('origin') or '') else 'Subscription',
            'items': [
                {
                    'name': line['product_id'][1] if line['product_id'] else 'Unknown',
                    'qty': line['product_uom_qty'],
                    'price': line['price_unit'],
                }
                for line in lines
            ],
            'total': order['amount_total'],
        })

    return result


# ----------------------------
# PAUSE SUBSCRIPTION (VACATION MODE)
# ----------------------------

@router.post("/subscriptions/pause")
def pause_subscription(pause_data: dict):
    """
    Store vacation dates either globally (partner level) or per-subscription (order level).
    Example: {"customer_email": "...", "start_date": "...", "end_date": "...", "subscription_id": 123}
    """
    customer_email = pause_data.get("customer_email")
    start_date = pause_data.get("start_date")
    end_date = pause_data.get("end_date")
    subscription_id = pause_data.get("subscription_id")

    if not customer_email or not start_date or not end_date:
        raise HTTPException(status_code=400, detail="Missing required fields")

    pause_str = f"VACATION:{start_date} to {end_date}"

    # OPTION A: Specific Subscription
    if subscription_id:
        # Read current note
        order = models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'sale.order', 'read', [int(subscription_id)], {'fields': ['note']})
        if not order:
            raise HTTPException(status_code=404, detail="Subscription not found")
        
        note = order[0].get('note') or ''
        # Remove any existing Vacation tag from note
        note = re.sub(r'\|?\s*VACATION:[^|]+', '', note).strip()
        # Append new one
        new_note = f"{note} | {pause_str}" if note else pause_str
        
        models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'sale.order', 'write', [[int(subscription_id)], {'note': new_note}])
        return {"message": f"Vacation mode set for subscription {subscription_id}", "pause_info": pause_str}

    # OPTION B: Global (Partner Level)
    partner_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY, 'res.partner', 'search',
        [[('email', '=', customer_email), ('is_company', '=', False), ('user_ids', '=', False)]]
    )
    if not partner_ids:
        partner_ids = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY, 'res.partner', 'search',
            [[('name', '=', customer_email), ('is_company', '=', False), ('user_ids', '=', False)]]
        )
    if not partner_ids:
        raise HTTPException(status_code=404, detail=f"Customer not found for '{customer_email}'")

    models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'res.partner', 'write', [[partner_ids[0]], {'comment': pause_str}])
    return {"message": "Global vacation mode set successfully", "pause_info": pause_str}


@router.post("/subscriptions/resume")
def resume_subscription(resume_data: dict):
    """
    Clear vacation dates either globally or for a specific subscription.
    """
    customer_email = resume_data.get("customer_email")
    subscription_id = resume_data.get("subscription_id")

    # OPTION A: Specific Subscription
    if subscription_id:
        order = models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'sale.order', 'read', [int(subscription_id)], {'fields': ['note']})
        if not order:
             raise HTTPException(status_code=404, detail="Subscription not found")
        
        note = order[0].get('note') or ''
        # Remove Vacation tag
        new_note = re.sub(r'\|?\s*VACATION:[^|]+', '', note).strip()
        # Cleanup leading/trailing pipes
        new_note = new_note.strip('|').strip()
        
        models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'sale.order', 'write', [[int(subscription_id)], {'note': new_note}])
        return {"message": f"Deliveries resumed for subscription {subscription_id}"}

    # OPTION B: Global
    if not customer_email:
        raise HTTPException(status_code=400, detail="Missing customer_email for global resume")

    partner_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY, 'res.partner', 'search',
        [[('email', '=', customer_email), ('is_company', '=', False), ('user_ids', '=', False)]]
    )
    if partner_ids:
        models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'res.partner', 'write', [[partner_ids[0]], {'comment': False}])
        return {"message": "Global deliveries resumed successfully"}
    
    raise HTTPException(status_code=404, detail="Customer not found")


# ----------------------------
# LIST CUSTOMERS
# ----------------------------

@router.get("/customers")
def list_customers():
    """Fetch all customer partners from Odoo."""
    partners = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'res.partner', 'search_read',
        [[('customer_rank', '>', 0), ('is_company', '=', False), ('user_ids', '=', False)]],
        {
            'fields': ['id', 'name', 'email', 'phone', 'street', 'city', 'customer_rank'],
            'order': 'name asc',
            'limit': 200,
        }
    )

    # Count orders per customer
    result = []
    for partner in partners:
        order_count = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'sale.order', 'search_count',
            [[('partner_id', '=', partner['id']), ('company_id', '=', TRUE_HARVEST_COMPANY_ID)]]
        )

        address_parts = [p for p in [partner.get('street'), partner.get('city')] if p]
        result.append({
            'id': partner['id'],
            'name': partner['name'],
            'email': partner.get('email') or '',
            'phone': partner.get('phone') or '',
            'address': ', '.join(address_parts),
            'orders': order_count,
        })

    return result


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

    # 🔹 Check or Create Customer (Partner)
    # Explicitly exclude partners linked to Odoo user accounts (user_ids=False).
    # The Odoo admin partner has user_ids=[2] and shares the admin email —
    # without this filter it gets matched and 'My Company India' appears on invoices.
    partner_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'res.partner', 'search',
        [[
            ('email', '=', customer_email),
            ('is_company', '=', False),
            ('user_ids', '=', False),   # exclude Odoo user accounts (admins, internal users)
        ]]
    )

    if partner_ids:
        partner_id = partner_ids[0]
    else:
        # Create as a standalone external customer.
        # Do NOT set company_id — that makes the partner an internal contact
        # of the company instead of an external customer.
        partner_id = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'res.partner', 'create',
            [{
                'name': customer_name,
                'email': customer_email,
                'customer_rank': 1,
            }]
        )

    # 🔹 Create Sale Order (Header)
    sale_order_id = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.order', 'create',
        [{
            'partner_id': partner_id,
            'company_id': TRUE_HARVEST_COMPANY_ID,
            'origin': f"{order_data.get('order_type', 'Instant Order')} - {order_data.get('frequency', 'One-time')}",
        }]
    )

    # 🔹 Create Order Lines
    for line in lines:
        product_id = line.get("product_id")
        quantity = line.get("quantity")

        # Check stock availability and company
        product_data = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'product.product', 'read',
            [[product_id]],
            {'fields': ['qty_available', 'lst_price', 'company_id']}
        )

        if not product_data:
            raise HTTPException(status_code=404, detail=f"Product ID {product_id} not found")

        product = product_data[0]
        
        # Verify product company
        if product['company_id'] and product['company_id'][0] != TRUE_HARVEST_COMPANY_ID:
             raise HTTPException(status_code=403, detail=f"Product ID {product_id} belongs to a different company.")

        if product['qty_available'] <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"Product ID {product_id} is out of stock"
            )

        # Create Line
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'sale.order.line', 'create',
            [{
                'order_id': sale_order_id,
                'product_id': product_id,
                'product_uom_qty': quantity,
                'price_unit': product['lst_price'],
                'company_id': TRUE_HARVEST_COMPANY_ID
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

    # 1️⃣ Get current state first and verify company
    sale = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.order', 'read',
        [[order_id], ['state', 'name', 'partner_id', 'company_id']]
    )[0]
    
    if sale['company_id'][0] != TRUE_HARVEST_COMPANY_ID:
        raise HTTPException(status_code=403, detail="Unauthorized: Order belongs to a different company.")

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
        [[
            ('origin', '=', sale['name']),
            ('company_id', '=', TRUE_HARVEST_COMPANY_ID)
        ]]
    )

    for picking_id in picking_ids:
        # 1️⃣ Assign stock
        models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'stock.picking', 'action_assign', [[picking_id]])

        # 2️⃣ Get stock moves
        moves = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'stock.move', 'search_read',
            [[('picking_id', '=', picking_id), ('company_id', '=', TRUE_HARVEST_COMPANY_ID)]],
            {'fields': ['id', 'product_uom_qty']}
        )

        for move in moves:
            # 3️⃣ Get move lines
            move_lines = models.execute_kw(
                ODOO_DB, uid, ODOO_API_KEY,
                'stock.move.line', 'search',
                [[('move_id', '=', move['id']), ('company_id', '=', TRUE_HARVEST_COMPANY_ID)]]
            )

            # 4️⃣ Set qty_done
            for line_id in move_lines:
                models.execute_kw(
                    ODOO_DB, uid, ODOO_API_KEY,
                    'stock.move.line', 'write',
                    [[line_id], {'qty_done': move['product_uom_qty']}]
                )

        # 5️⃣ Validate picking
        models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'stock.picking', 'button_validate', [[picking_id]])

    # 4️⃣ Create Invoice via Wizard
    wizard_id = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.advance.payment.inv', 'create',
        [{'advance_payment_method': 'delivered', 'company_id': TRUE_HARVEST_COMPANY_ID}],
        {'context': {'active_ids': [order_id], 'company_id': TRUE_HARVEST_COMPANY_ID}}
    )

    models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.advance.payment.inv', 'create_invoices',
        [[wizard_id]],
        {'context': {'active_ids': [order_id], 'company_id': TRUE_HARVEST_COMPANY_ID}}
    )

    # 5️⃣ Find Created Invoice
    invoice_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'account.move', 'search',
        [[('invoice_origin', '=', sale['name']), ('company_id', '=', TRUE_HARVEST_COMPANY_ID)]]
    )

    # 6️⃣ Post Invoice
    for invoice_id in invoice_ids:
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'account.move', 'action_post',
            [[invoice_id]],
            {'context': {'company_id': TRUE_HARVEST_COMPANY_ID}}
        )

    return {"message": "Payment confirmed. Delivery validated. Invoice generated."}


# ----------------------------
# RETURN ORDER (STOCK)
# ----------------------------

@router.post("/orders/{order_id}/return")
def return_order(order_id: int, return_data: dict = None):
    # return_data example: {"items": [{"product_id": 1, "quantity": 2}]}
    
    # 1️⃣ Get Sale Order details and verify company
    sale = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.order', 'read',
        [[order_id], ['name', 'company_id']]
    )[0]
    
    if sale['company_id'][0] != TRUE_HARVEST_COMPANY_ID:
        raise HTTPException(status_code=403, detail="Unauthorized: Order belongs to a different company.")

    # 2️⃣ Find the validated outgoing picking
    picking_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.picking', 'search',
        [[
            ('origin', '=', sale['name']),
            ('picking_type_id.code', '=', 'outgoing'),
            ('state', '=', 'done'),
            ('company_id', '=', TRUE_HARVEST_COMPANY_ID)
        ]]
    )

    if not picking_ids:
        raise HTTPException(status_code=400, detail="No validated delivery picking found for this order in True Harvest.")

    picking_id = picking_ids[0]

    # 3️⃣ Create Return Picking via Wizard
    # 🔹 Fetch moves
    moves = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.move', 'search_read',
        [[('picking_id', '=', picking_id), ('state', '=', 'done')]],
        {'fields': ['product_id', 'product_uom_qty']}
    )

    requested_items = return_data.get("items") if return_data else None
    return_moves = []
    
    for move in moves:
        product_id = move['product_id'][0]
        qty_to_return = move['product_uom_qty']
        
        # If partial return requested, find matching item
        if requested_items:
            match = next((i for i in requested_items if i['product_id'] == product_id), None)
            if not match:
                continue # Skip items not in the request
            qty_to_return = match['quantity']
            
            if qty_to_return > move['product_uom_qty']:
                raise HTTPException(status_code=400, detail=f"Cannot return {qty_to_return} for product {product_id}. Only {move['product_uom_qty']} delivered.")

        return_moves.append((0, 0, {
            'product_id': product_id,
            'quantity': qty_to_return,
            'move_id': move['id'],
        }))

    if not return_moves:
         raise HTTPException(status_code=400, detail="No products found to return based on your request.")

    return_wizard_id = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.return.picking', 'create',
        [{
            'picking_id': picking_id,
            'product_return_moves': return_moves
        }],
        {'context': {'active_id': picking_id, 'company_id': TRUE_HARVEST_COMPANY_ID}}
    )

    # Trigger the return creation
    res = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'stock.return.picking', 'create_returns',
        [[return_wizard_id]],
        {'context': {'active_id': picking_id, 'company_id': TRUE_HARVEST_COMPANY_ID}}
    )

    # 4️⃣ Find and Validate the Return Picking
    return_picking_id = res.get('res_id')
    if return_picking_id:
        models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'stock.picking', 'action_assign', [[return_picking_id]])
        
        # Set quantities for return
        moves_res = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'stock.move', 'search_read',
            [[('picking_id', '=', return_picking_id), ('company_id', '=', TRUE_HARVEST_COMPANY_ID)]],
            {'fields': ['id', 'product_uom_qty']}
        )
        for mov in moves_res:
            move_line_ids = models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'stock.move.line', 'search', [[('move_id', '=', mov['id']), ('company_id', '=', TRUE_HARVEST_COMPANY_ID)]])
            for ml_id in move_line_ids:
                models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'stock.move.line', 'write', [[ml_id], {'qty_done': mov['product_uom_qty']}])

        models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'stock.picking', 'button_validate', [[return_picking_id]])

    return {"message": "Order return processed successfully", "return_picking_id": return_picking_id}


# ----------------------------
# REFUND ORDER (FINANCIAL)
# ----------------------------

@router.post("/orders/{order_id}/refund")
def refund_order(order_id: int, refund_data: dict = None):
    # refund_data example: {"items": [{"product_id": 1, "quantity": 2}]}

    # 1️⃣ Get Sale Order details and verify company
    sale = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.order', 'read',
        [[order_id], ['name', 'company_id']]
    )[0]
    
    if sale['company_id'][0] != TRUE_HARVEST_COMPANY_ID:
        raise HTTPException(status_code=403, detail="Unauthorized: Order belongs to a different company.")

    # 2️⃣ Find the posted Invoice and its journal
    invoice_data = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'account.move', 'search_read',
        [[
            ('invoice_origin', '=', sale['name']),
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('company_id', '=', TRUE_HARVEST_COMPANY_ID)
        ]],
        {'fields': ['id', 'journal_id']}
    )

    if not invoice_data:
        raise HTTPException(status_code=400, detail="No posted invoice found for this order in True Harvest.")

    invoice_id = invoice_data[0]['id']
    journal_id = invoice_data[0]['journal_id'][0]

    # 3️⃣ Create Credit Note via Reversal Wizard
    reversal_wizard_id = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'account.move.reversal', 'create',
        [{
            'move_ids': [(6, 0, [invoice_id])],
            'reason': 'Customer Return',
            'refund_method': 'refund',
            'journal_id': journal_id,
            'company_id': TRUE_HARVEST_COMPANY_ID
        }],
        {'context': {'active_ids': [invoice_id], 'active_model': 'account.move', 'company_id': TRUE_HARVEST_COMPANY_ID}}
    )

    # Trigger the reversal (creates a draft credit note)
    reversal_res = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'account.move.reversal', 'reverse_moves',
        [[reversal_wizard_id]],
        {'context': {'active_ids': [invoice_id], 'active_model': 'account.move', 'company_id': TRUE_HARVEST_COMPANY_ID}}
    )

    # 4️⃣ Adjust Credit Note if partial refund
    credit_note_id = reversal_res.get('res_id')
    if credit_note_id and refund_data and refund_data.get("items"):
        requested_items = refund_data["items"]
        
        # Read credit note lines
        # Filtering only for lines with products to avoid ValueError in some Odoo versions
        cn_lines = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'account.move.line', 'search_read',
            [[('move_id', '=', credit_note_id)]],
            {'fields': ['id', 'product_id', 'quantity']}
        )
        
        lines_to_update = []
        for line in cn_lines:
            # Skip lines that don't have a product (e.g., taxes)
            if not line['product_id']:
                continue

            product_id = line['product_id'][0]
            match = next((item for item in requested_items if item['product_id'] == product_id), None)
            
            if match:
                requested_qty = match['quantity']
                if requested_qty < line['quantity']:
                    lines_to_update.append((1, line['id'], {'quantity': requested_qty}))
                elif requested_qty > line['quantity']:
                    raise HTTPException(status_code=400, detail=f"Cannot refund {requested_qty} for product {product_id}. Original invoice quantity was {line['quantity']}.")
            else:
                # If product not in requested items, remove the line
                # In Odoo, setting quantity to 0 or using unlink is possible. 
                # Unlinking is cleaner but let's use quantity 0 if we want to keep the line or unlink it properly.
                lines_to_update.append((2, line['id'], 0)) # 2 = Delete (unlink)

        if lines_to_update:
            models.execute_kw(
                ODOO_DB, uid, ODOO_API_KEY,
                'account.move', 'write',
                [[credit_note_id], {'invoice_line_ids': lines_to_update}]
            )

    # 5️⃣ Post the Credit Note
    if credit_note_id:
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'account.move', 'action_post',
            [[credit_note_id]],
            {'context': {'company_id': TRUE_HARVEST_COMPANY_ID}}
        )

    return {"message": "Order refund processed successfully", "credit_note_id": credit_note_id}


# ----------------------------
# REPLACE ORDER (RETURN + NEW SO)
# ----------------------------

@router.post("/orders/{order_id}/replace")
def replace_order(order_id: int, replacement_data: dict):
    # replacement_data should contain: 
    # {"return_items": [{"product_id": X, "quantity": Y}], "replacement_items": [{"product_id": A, "quantity": B}]}
    
    # 1️⃣ Process Partial Return
    return_items = replacement_data.get("return_items")
    return_res = return_order(order_id, {"items": return_items} if return_items else None)
    
    # 2️⃣ Create New Sale Order for Replacement
    sale = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.order', 'read',
        [[order_id], ['partner_id', 'company_id']]
    )[0]

    # Double check company again
    if sale['company_id'][0] != TRUE_HARVEST_COMPANY_ID:
        raise HTTPException(status_code=403, detail="Unauthorized.")

    new_sale_order_id = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.order', 'create',
        [{
            'partner_id': sale['partner_id'][0],
            'company_id': TRUE_HARVEST_COMPANY_ID,
            'origin': f"Replacement for {order_id}"
        }]
    )

    # 3️⃣ Add replacement lines
    replacement_items = replacement_data.get("replacement_items", [])
    for item in replacement_items:
        product_id = item.get("product_id")
        quantity = item.get("quantity", 1)

        product_data = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'product.product', 'read',
            [[product_id]],
            {'fields': ['lst_price', 'company_id']}
        )[0]
        
        # Verify new product company
        if product_data['company_id'] and product_data['company_id'][0] != TRUE_HARVEST_COMPANY_ID:
             raise HTTPException(status_code=403, detail="Unauthorized: Replacement product belongs to a different company.")

        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'sale.order.line', 'create',
            [{
                'order_id': new_sale_order_id,
                'product_id': product_id,
                'product_uom_qty': quantity,
                'price_unit': product_data['lst_price'],
                'company_id': TRUE_HARVEST_COMPANY_ID
            }]
        )

    # 4️⃣ Confirm the new Sale Order
    models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'sale.order', 'action_confirm', [[new_sale_order_id]])

    return {
        "message": "Order replacement processed successfully",
        "return_info": return_res,
        "new_order_id": new_sale_order_id
    }

# ----------------------------
# REQUEST ACTION (TAGGING)
# ----------------------------

@router.post("/orders/{order_id}/action-request")
def request_order_action(order_id: int, request_data: ActionRequest):
    """
    Logs a customer request (Cancel, Return, Replace) on an Odoo Sale Order
    using CRM Tags and an internal note, without executing the financial/stock moves immediately.
    """
    # 1️⃣ Get Sale Order details and verify company
    sale = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.order', 'read',
        [[order_id], ['name', 'company_id', 'state', 'tag_ids']]
    )
    
    if not sale:
        raise HTTPException(status_code=404, detail="Order not found")
        
    sale = sale[0]
    
    if sale['company_id'][0] != TRUE_HARVEST_COMPANY_ID:
        raise HTTPException(status_code=403, detail="Unauthorized: Order belongs to a different company.")

    # Validate state vs action
    action = request_data.action_type
    
    # 1.5️⃣ Fetch invoice status as well
    sale_detail = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.order', 'read',
        [[order_id], ['invoice_status']]
    )[0]
    invoice_status = sale_detail.get('invoice_status')

    if action == 'Cancel':
        if sale['state'] in ['done', 'cancel']:
             raise HTTPException(status_code=400, detail=f"Order is already {sale['state']}. Cannot request cancellation.")
        if invoice_status == 'invoiced':
             raise HTTPException(status_code=400, detail="Invoice already posted. Cannot request cancellation.")
    
    if action in ['Return', 'Replace']:
        if sale['state'] != 'done':
             raise HTTPException(status_code=400, detail="Order must be delivered before requesting return/replacement.")
    
    # 2️⃣ Find or Create Tag
    tag_name = f"{action} Requested"
    tag_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'crm.tag', 'search',
        [[('name', '=', tag_name)]]
    )
    
    if not tag_ids:
        # Create tag with a specific color (e.g. 2 for red/orange)
        tag_id = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'crm.tag', 'create',
            [{'name': tag_name, 'color': 2}]
        )
    else:
        tag_id = tag_ids[0]

    # 3️⃣ Add tag to Sale Order
    current_tags = sale.get('tag_ids', [])
    if tag_id not in current_tags:
        new_tags = current_tags + [tag_id]
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'sale.order', 'write',
            [[order_id], {'tag_ids': [[6, 0, new_tags]]}] # (6, 0, ids) command replaces the list of ids
        )

    # 4️⃣ Log Internal Note on chatter
    note_body = (
        f"<b>Customer Request: {action}</b><br/>"
        f"<b>Reason:</b> {request_data.reason}<br/>"
    )
    if request_data.comment:
        note_body += f"<b>Comments:</b> {request_data.comment}"
        
    models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'mail.message', 'create',
        [{
            'model': 'sale.order',
            'res_id': order_id,
            'body': note_body,
            'message_type': 'comment', # acts like an internal note
            'subtype_id': 2 # Usually 2 is mail.mt_note
        }]
    )

    return {"message": f"{action} request successfully logged for Review.", "tag_id": tag_id}


# ----------------------------
# SUBSCRIPTIONS (MASTER ORDERS)
# ----------------------------

@router.get("/subscriptions")
def list_subscriptions(customer_email: Optional[str] = Query(None, description="Filter by customer email")):
    """Fetch all 'Master' subscription orders from Odoo."""
    domain = [
        ('company_id', '=', TRUE_HARVEST_COMPANY_ID),
        ('origin', '=', '[SUBSCRIPTION_MASTER]')
    ]
    
    # Filter by specific customer if email is provided
    if customer_email:
        partner_ids = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'res.partner', 'search',
            [[('email', '=', customer_email)]]
        )
        if partner_ids:
            domain.append(('partner_id', 'in', partner_ids))
        else:
            return [] # No partner found for this email

    orders = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.order', 'search_read',
        [domain],
        {
            'fields': ['id', 'name', 'partner_id', 'date_order', 'amount_total', 'order_line', 'note'],
            'order': 'date_order desc',
        }
    )

    result = []
    for order in orders:
        # Fetch order lines to get product names
        line_ids = order.get('order_line', [])
        lines = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'sale.order.line', 'read',
            [line_ids],
            {'fields': ['product_id', 'product_uom_qty']}
        ) if line_ids else []

        # Parse frequency and next delivery from note if possible
        # Expected format in note: "Frequency: Weekly | Next Delivery: 2026-03-20"
        note = order.get('note') or ''
        # Strip HTML tags if present (e.g., from Odoo rich text)
        note = re.sub('<[^<]+?>', '', note)
        
        frequency = 'Weekly'
        next_delivery = ''
        
        if 'Frequency:' in note:
            parts = note.split('|')
            for p in parts:
                p_clean = p.strip()
                if 'Frequency:' in p_clean and ':' in p_clean:
                    frequency = p_clean.split(':', 1)[1].strip()
                if 'Next Delivery:' in p_clean and ':' in p_clean:
                    next_delivery = p_clean.split(':', 1)[1].strip()

        # Prepare products list
        all_products = []
        for line in lines:
            if line.get('product_id'):
                all_products.append({
                    'product_id': line['product_id'][0],
                    'product_name': line['product_id'][1],
                    'quantity': line['product_uom_qty'],
                    'is_extra': '[EXTRA ITEM]' in (line.get('name') or '')
                })

        # Keep product info (first regular product) for compatibility
        regular_products = [p for p in all_products if not p['is_extra']]
        primary_product = regular_products[0] if regular_products else (all_products[0] if all_products else {})

        result.append({
            'id': order['id'],
            'order_ref': order['name'],
            'customer_name': order['partner_id'][1] if (order.get('partner_id') and len(order['partner_id']) > 1) else 'Unknown',
            'product': primary_product.get('product_name', '—'),
            'product_id': primary_product.get('product_id'),
            'products': all_products, # All lines
            'frequency': frequency,
            'next_delivery': next_delivery,
            'status': 'Active',
            'amount_total': order.get('amount_total', 0.0),
            'partner_id': order['partner_id'][0] if (order.get('partner_id') and len(order['partner_id']) > 0) else None,
            'raw_note': order.get('note') or ''
        })

    # Fetch Partner comments to check for Vacation Mode overrides
    if result:
        partner_ids = list(set([r['partner_id'] for r in result if r['partner_id']]))
        if partner_ids:
            partners = models.execute_kw(
                ODOO_DB, uid, ODOO_API_KEY,
                'res.partner', 'read',
                [partner_ids],
                {'fields': ['id', 'comment']}
            )
            
            partner_comments = {p['id']: p.get('comment') or '' for p in partners}
            today = date.today()
            
            for r in result:
                pid = r.get('partner_id')
                if not pid: continue
                
                comment = partner_comments.get(pid) or ''
                # Strip HTML tags safely
                if comment:
                    comment = re.sub('<[^<]+?>', '', comment)
                
                # Priority: Check subscription Note first, then partner comment
                order_note = r.get('raw_note') or ''
                vacation_source = order_note if 'VACATION:' in order_note else comment
                
                if vacation_source and 'VACATION:' in vacation_source:
                    try:
                        # Parse "VACATION:YYYY-MM-DD to YYYY-MM-DD"
                        v_parts = vacation_source.split('VACATION:', 1)
                        if len(v_parts) > 1:
                            dates_part = v_parts[1].split('|')[0].strip().split(' to ')
                            if len(dates_part) == 2:
                                start_str = dates_part[0].strip()
                                end_str = dates_part[1].strip()
                                if start_str and end_str:
                                    start_date = date.fromisoformat(start_str)
                                    end_date = date.fromisoformat(end_str)
                                    
                                    # Update summary status to Paused
                                    r['status'] = 'Paused'
                                    r['vacation_range'] = f"{start_str} to {end_str}"
                                    
                                    # Check if the NEXT DELIVERY date falls within the vacation range
                                    delivery_str = r.get('next_delivery')
                                    check_date = today
                                    if delivery_str:
                                        try:
                                            check_date = date.fromisoformat(delivery_str)
                                        except:
                                            # If next_delivery date is malformed, we fall back to today
                                            pass
                                            
                                    if start_date <= check_date <= end_date:
                                        r['status'] = 'Paused'
                    except Exception as e:
                        print(f"Error parsing vacation comment for partner {pid}: {e}")
                        # Silently ignore format errors and keep status Active

    return result




@router.post("/subscriptions")
def create_subscription(sub_data: dict):
    """Create a Master Order representing a subscription."""
    customer_name = sub_data.get("customerName")
    product_id = sub_data.get("productId")
    frequency = sub_data.get("frequency", "Weekly")
    next_delivery = sub_data.get("nextDelivery", "")

    # Ensure product_id is an integer
    if product_id is not None:
        try:
            product_id = int(product_id)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid product ID format")

    # 1. Reuse existing customer lookup logic (simplified here)
    partner_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'res.partner', 'search',
        [[('name', '=', customer_name), ('is_company', '=', False)]]
    )
    if not partner_ids:
        partner_id = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'res.partner', 'create',
            [{'name': customer_name, 'customer_rank': 1}]
        )
    else:
        partner_id = partner_ids[0]

    # 2. Create Master Order
    # We store the subscription config in the 'note' field
    note_content = f"Frequency: {frequency} | Next Delivery: {next_delivery}"
    
    sale_order_id = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.order', 'create',
        [{
            'partner_id': partner_id,
            'company_id': TRUE_HARVEST_COMPANY_ID,
            'origin': '[SUBSCRIPTION_MASTER]',
            'note': note_content,
        }]
    )

    # 3. Add Product Line
    if product_id:
        product_data = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'product.product', 'read',
            [[product_id]],
            {'fields': ['lst_price']}
        )[0]
        
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'sale.order.line', 'create',
            [{
                'order_id': sale_order_id,
                'product_id': product_id,
                'product_uom_qty': 1,
                'price_unit': product_data['lst_price'],
                'company_id': TRUE_HARVEST_COMPANY_ID
            }]
        )

    return {"message": "Subscription master created", "id": sale_order_id}


@router.delete("/subscriptions/{subscription_id}")
def delete_subscription(subscription_id: int):
    """Archive or delete a subscription master order."""
    # We verify it's a subscription master before deleting
    order = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.order', 'read',
        [[subscription_id]],
        {'fields': ['origin', 'company_id']}
    )

    if not order:
        raise HTTPException(status_code=404, detail="Subscription not found")

    if order[0].get('origin') != '[SUBSCRIPTION_MASTER]':
        raise HTTPException(status_code=400, detail="Order is not a subscription master")

    if order[0]['company_id'][0] != TRUE_HARVEST_COMPANY_ID:
        raise HTTPException(status_code=403, detail="Unauthorized")

    # In Odoo, we can unlink (delete) draft/cancel orders, or just change the origin to hide it
    try:
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'sale.order', 'unlink',
            [[subscription_id]]
        )
        return {"message": "Subscription deleted successfully"}
    except Exception as e:
        # If delete fails (e.g. references exist), we archive it by changing origin
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'sale.order', 'write',
            [[subscription_id], {'origin': '[SUBSCRIPTION_MASTER_ARCHIVED]'}]
        )
        return {"message": "Subscription archived (could not delete due to history)"}


# ----------------------------
# RESUME SUBSCRIPTION (REMOVE VACATION)
# ----------------------------

@router.post("/subscriptions/resume")
def resume_subscription(resume_data: dict):
    """
    Remove the VACATION tag from a partner's comment to resume deliveries.
    Body: {"customer_email": "..."}
    """
    customer_email = resume_data.get("customer_email")
    if not customer_email:
        raise HTTPException(status_code=400, detail="customer_email is required")

    partner_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'res.partner', 'search',
        [[('email', '=', customer_email), ('is_company', '=', False), ('user_ids', '=', False)]]
    )
    if not partner_ids:
        raise HTTPException(status_code=404, detail="Customer not found")

    partner_id = partner_ids[0]
    partner = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'res.partner', 'read',
        [[partner_id]],
        {'fields': ['comment']}
    )[0]

    import re as _re
    comment = partner.get('comment') or ''
    # Strip HTML tags
    comment = _re.sub(r'<[^<]+?>', '', comment)
    # Remove VACATION: line
    lines = [l for l in comment.split('\n') if 'VACATION:' not in l]
    new_comment = '\n'.join(lines).strip()

    models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'res.partner', 'write',
        [[partner_id], {'comment': new_comment or False}]
    )
    return {"message": "Subscription resumed — vacation mode removed"}


# ----------------------------
# DELIVERY HISTORY FOR A SUBSCRIPTION CUSTOMER
# ----------------------------

@router.get("/subscriptions/delivery-history")
def get_delivery_history(customer_email: str = None):
    """
    Return the list of past subscription delivery orders for a customer.
    These are Sale Orders with origin starting with 'Subscription Delivery'.
    """
    domain = [
        ('company_id', '=', TRUE_HARVEST_COMPANY_ID),
        ('origin', 'like', 'Subscription Delivery'),
    ]

    if customer_email:
        partner_ids = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'res.partner', 'search',
            [[('email', '=', customer_email)]]
        )
        if partner_ids:
            domain.append(('partner_id', 'in', partner_ids))
        else:
            return []

    orders = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.order', 'search_read',
        [domain],
        {
            'fields': ['id', 'name', 'partner_id', 'date_order', 'state', 'amount_total', 'origin', 'order_line'],
            'order': 'date_order desc',
            'limit': 100,
        }
    )

    result = []
    for order in orders:
        lines = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'sale.order.line', 'read',
            [order['order_line']],
            {'fields': ['product_id', 'product_uom_qty', 'price_unit']}
        ) if order['order_line'] else []

        state_map = {'draft': 'Pending', 'sent': 'Pending', 'sale': 'Processing', 'done': 'Delivered', 'cancel': 'Cancelled'}
        result.append({
            'id': order['id'],
            'order_ref': order['name'],
            'date': (order.get('date_order') or '')[:10],
            'status': state_map.get(order['state'], order['state'].capitalize()),
            'amount_total': order['amount_total'],
            'origin': order.get('origin') or '',
            'lines': [
                {
                    'product_name': l['product_id'][1] if l['product_id'] else 'Unknown',
                    'quantity': l['product_uom_qty'],
                    'price_unit': l['price_unit'],
                }
                for l in lines
            ],
        })

    return result


# ----------------------------
# OUT-OF-STOCK SUBSCRIPTIONS (for admin view)
# ----------------------------

@router.get("/subscriptions/out-of-stock")
def get_out_of_stock_subscriptions():
    """
    Return subscription masters where at least one product has zero stock.
    Used by admin dashboard to flag subscriptions that will be skipped.
    """
    masters = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.order', 'search_read',
        [[
            ('origin', '=', '[SUBSCRIPTION_MASTER]'),
            ('state', '=', 'draft'),
            ('company_id', '=', TRUE_HARVEST_COMPANY_ID),
        ]],
        {'fields': ['id', 'name', 'partner_id', 'order_line']}
    )

    out_of_stock = []
    for master in masters:
        line_ids = master.get('order_line', [])
        if not line_ids:
            continue
        lines = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'sale.order.line', 'read',
            [line_ids],
            {'fields': ['product_id', 'product_uom_qty']}
        )
        for line in lines:
            if not line.get('product_id'):
                continue
            product = models.execute_kw(
                ODOO_DB, uid, ODOO_API_KEY,
                'product.product', 'read',
                [[line['product_id'][0]]],
                {'fields': ['qty_available']}
            )
            if product and product[0]['qty_available'] < line['product_uom_qty']:
                out_of_stock.append({
                    'subscription_ref': master['name'],
                    'customer': master['partner_id'][1] if master['partner_id'] else 'Unknown',
                    'product': line['product_id'][1],
                    'qty_available': product[0]['qty_available'],
                    'qty_needed': line['product_uom_qty'],
                })

    return out_of_stock


@router.post("/subscriptions/add-item")
def add_item_to_subscription(sub_data: dict):
    """Add an extra item to the next scheduled subscription delivery (Master Order)."""
    email = sub_data.get("customer_email")
    product_id = sub_data.get("product_id")
    quantity = sub_data.get("quantity", 1)
    subscription_id = sub_data.get("subscription_id") # New: specific target

    if not email or not product_id:
        raise HTTPException(status_code=400, detail="customer_email and product_id are required")

    order_id = None
    master_name = "subscription"

    # 1. If specific subscription_id is provided, use it
    if subscription_id:
        masters = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'sale.order', 'search_read',
            [[
                ('id', '=', int(subscription_id)),
                ('state', '=', 'draft'),
                ('origin', '=', '[SUBSCRIPTION_MASTER]'),
                ('company_id', '=', TRUE_HARVEST_COMPANY_ID)
            ]],
            {'fields': ['id', 'name'], 'limit': 1}
        )
        if masters:
            order_id = masters[0]['id']
            master_name = masters[0]['name']

    # 2. Fallback: Find any active master for the customer email
    if not order_id:
        partner_ids = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'res.partner', 'search',
            [[('email', '=', email), ('company_id', '=', False)]]
        )
        if not partner_ids:
            raise HTTPException(status_code=404, detail="Customer not found in Odoo")
        
        for p_id in partner_ids:
            masters = models.execute_kw(
                ODOO_DB, uid, ODOO_API_KEY,
                'sale.order', 'search_read',
                [[
                    ('partner_id', '=', p_id),
                    ('state', '=', 'draft'),
                    ('origin', '=', '[SUBSCRIPTION_MASTER]'),
                    ('company_id', '=', TRUE_HARVEST_COMPANY_ID)
                ]],
                {'fields': ['id', 'name'], 'order': 'date_order asc', 'limit': 1}
            )
            if masters:
                order_id = masters[0]['id']
                master_name = masters[0]['name']
                break
    
    if not order_id:
        raise HTTPException(
            status_code=404, 
            detail="No active subscription quotation found. Please ensure you have an active subscription."
        )

    # 3. Add Product Line
    product_data = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'product.product', 'read',
        [[product_id]],
        {'fields': ['lst_price', 'display_name']}
    )[0]
    
    models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.order.line', 'create',
        [{
            'order_id': order_id,
            'product_id': product_id,
            'product_uom_qty': quantity,
            'price_unit': product_data['lst_price'],
            'company_id': TRUE_HARVEST_COMPANY_ID,
            'name': f"[EXTRA ITEM] {product_data['display_name']}"
        }]
    )

    return {
        "message": f"Successfully added {quantity}x extra items to your next delivery ({masters[0]['name']})",
        "order_id": order_id
    }
