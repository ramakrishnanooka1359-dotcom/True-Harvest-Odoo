from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from odoo_client import models, uid
from config import ODOO_DB, ODOO_API_KEY, TRUE_HARVEST_COMPANY_ID
from orders import return_order, refund_order, replace_order

router = APIRouter(prefix="/admin", tags=["Admin Actions"])

@router.post("/orders/{order_id}/approve-cancel")
def approve_cancel(order_id: int):
    """Admin approves a cancellation request."""
    # 1. Cancel the order in Odoo
    try:
        models.execute_kw(ODOO_DB, uid, ODOO_API_KEY, 'sale.order', 'action_cancel', [[order_id]])
        
        # 2. Clear the "Cancel Requested" tag
        _clear_tag(order_id, "Cancel Requested")
        
        return {"message": "Order cancelled and tag cleared."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cancel order: {str(e)}")

@router.post("/orders/{order_id}/approve-return")
def approve_return(order_id: int, refund: bool = Query(True, description="Whether to also process refund")):
    """Admin approves a return request. Executes stock return and optional refund."""
    try:
        # 1. Execute Return (Stock)
        ret_res = return_order(order_id)
        
        # 2. Execute Refund (Financial) if requested
        ref_res = None
        if refund:
            ref_res = refund_order(order_id)
            
        # 3. Clear the "Return Requested" tag
        _clear_tag(order_id, "Return Requested")
        
        return {
            "message": "Return approved and processed.",
            "return": ret_res,
            "refund": ref_res
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/orders/{order_id}/approve-replacement")
def approve_replacement(order_id: int, replacement_data: dict):
    """
    Admin approves a replacement.
    Payload: {"return_items": [...], "replacement_items": [...]}
    """
    try:
        # 1. Execute Replacement logic
        res = replace_order(order_id, replacement_data)
        
        # 2. Clear the "Replacement Requested" tag
        _clear_tag(order_id, "Replacement Requested")
        
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/orders/{order_id}/reject-action")
def reject_action(order_id: int, action_type: str = Query(..., description="Cancel, Return, or Replace")):
    """Admin rejects a request and clears the tag."""
    tag_name = f"{action_type} Requested"
    _clear_tag(order_id, tag_name)
    
    # Log internal note about rejection
    models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'mail.message', 'create',
        [{
            'model': 'sale.order',
            'res_id': order_id,
            'body': f"<b>Admin Action:</b> {action_type} Request Rejected.",
            'message_type': 'comment',
            'subtype_id': 2
        }]
    )
    
    return {"message": f"{action_type} request rejected."}

def _clear_tag(order_id, tag_name):
    """Utility to remove a specific tag from a sale order."""
    sale = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'sale.order', 'read',
        [[order_id], ['tag_ids']]
    )[0]
    
    tag_ids = models.execute_kw(
        ODOO_DB, uid, ODOO_API_KEY,
        'crm.tag', 'search',
        [[('name', '=', tag_name)]]
    )
    
    if tag_ids and tag_ids[0] in sale['tag_ids']:
        new_tags = [t for t in sale['tag_ids'] if t != tag_ids[0]]
        models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'sale.order', 'write',
            [[order_id], {'tag_ids': [[6, 0, new_tags]]}]
        )
