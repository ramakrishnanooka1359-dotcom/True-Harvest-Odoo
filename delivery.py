from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from sqlalchemy.orm import Session
from database import get_db
import models as db_models
from auth_utils import get_current_user
from odoo_client import models as odoo_models, uid as odoo_uid
from config import ODOO_DB, ODOO_API_KEY, TRUE_HARVEST_COMPANY_ID

router = APIRouter(prefix="/delivery", tags=["Delivery Boy Manifest"])

# --- Request Schemas ---

class AssignmentRequest(BaseModel):
    delivery_boy_id: int
    odoo_picking_id: int

class StatusUpdateRequest(BaseModel):
    status: str  # "in_transit", "failed"

# --- Endpoints ---

@router.post("/assign")
def assign_order(request: AssignmentRequest, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Assigns an Odoo picking/delivery order to a local Delivery Boy.
    Authorized: Admin or Vendor.
    Strict Rule: Vendors can ONLY assign delivery boys that are registered under their team.
    """
    role = current_user.get("role")
    user_id = current_user.get("user_id")
    
    if role not in ["admin", "vendor"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized. Only Admins or Vendors can assign delivery personnel."
        )
        
    # 1. Fetch the delivery boy
    rider = db.query(db_models.User).filter(
        db_models.User.id == request.delivery_boy_id,
        db_models.User.role == "delivery_boy"
    ).first()
    
    if not rider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The specified Delivery Boy was not found."
        )
        
    # 2. Strict Vendor-Rider Group Isolation
    if role == "vendor":
        if rider.vendor_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access Denied. You can only assign delivery boys that belong to your vendor team."
            )
            
    # 3. Check Odoo Picking existence (verify it belongs to Company 3)
    try:
        picking = odoo_models.execute_kw(
            ODOO_DB, odoo_uid, ODOO_API_KEY,
            'stock.picking', 'search_read',
            [[
                ('id', '=', request.odoo_picking_id),
                ('company_id', '=', TRUE_HARVEST_COMPANY_ID)
            ]],
            {'fields': ['name', 'state']}
        )
        if not picking:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Odoo stock picking order ID {request.odoo_picking_id} not found under Company 3."
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to query Odoo stock.picking record: {str(e)}"
        )
        
    # 4. Check if already assigned
    existing_assignment = db.query(db_models.DeliveryAssignment).filter(
        db_models.DeliveryAssignment.odoo_picking_id == request.odoo_picking_id
    ).first()
    if existing_assignment:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This picking order has already been assigned to a delivery boy."
        )
        
    # 5. Create local assignment
    assignment = db_models.DeliveryAssignment(
        delivery_boy_id=request.delivery_boy_id,
        odoo_picking_id=request.odoo_picking_id,
        status="assigned"
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    
    return {
        "message": "Successfully assigned order.",
        "assignment_id": assignment.id,
        "delivery_boy": rider.name,
        "odoo_picking_id": assignment.odoo_picking_id,
        "odoo_picking_name": picking[0]['name'],
        "status": assignment.status
    }

@router.get("/my-orders")
def get_my_orders(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Rider retrieves their live delivery manifest, merging local assignments
    with live Odoo picking items, customer names, and addresses.
    Authorized: Delivery Boy.
    """
    role = current_user.get("role")
    user_id = current_user.get("user_id")
    
    if role != "delivery_boy":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied. Only active Delivery Boys can access their manifest."
        )
        
    # 1. Fetch active assignments in database
    assignments = db.query(db_models.DeliveryAssignment).filter(
        db_models.DeliveryAssignment.delivery_boy_id == user_id,
        db_models.DeliveryAssignment.status.in_(["assigned", "in_transit"])
    ).all()
    
    if not assignments:
        return []
        
    # 2. Sync with Odoo and compile details
    manifest = []
    picking_ids = [a.odoo_picking_id for a in assignments]
    
    try:
        pickings = odoo_models.execute_kw(
            ODOO_DB, odoo_uid, ODOO_API_KEY,
            'stock.picking', 'search_read',
            [[('id', 'in', picking_ids)]],
            {'fields': ['id', 'name', 'partner_id', 'origin', 'state', 'move_ids_without_package']}
        )
        
        # Build mapping for lookup
        picking_map = {p['id']: p for p in pickings}
        
        for assignment in assignments:
            p_data = picking_map.get(assignment.odoo_picking_id)
            if not p_data:
                continue
                
            # If Odoo reports it as done/cancel, auto-align local status and skip
            if p_data['state'] in ['done', 'cancel']:
                assignment.status = "delivered" if p_data['state'] == 'done' else "failed"
                assignment.completed_at = datetime.utcnow()
                db.commit()
                continue
                
            # Query stock move lines to get names and quantities
            move_ids = p_data.get('move_ids_without_package', [])
            items = []
            if move_ids:
                moves = odoo_models.execute_kw(
                    ODOO_DB, odoo_uid, ODOO_API_KEY,
                    'stock.move', 'read',
                    [move_ids],
                    {'fields': ['product_id', 'product_uom_qty']}
                )
                items = [
                    {
                        "product_id": m['product_id'][0],
                        "product_name": m['product_id'][1],
                        "quantity": m['product_uom_qty']
                    }
                    for m in moves
                ]
                
            # Fetch partner/customer details
            partner_name = p_data['partner_id'][1] if p_data['partner_id'] else "Anonymous Customer"
            partner_address = "No Address Provided"
            if p_data['partner_id']:
                partner_id = p_data['partner_id'][0]
                partner = odoo_models.execute_kw(
                    ODOO_DB, odoo_uid, ODOO_API_KEY,
                    'res.partner', 'read',
                    [[partner_id]],
                    {'fields': ['street', 'street2', 'city', 'phone']}
                )[0]
                street = partner.get('street') or ""
                street2 = partner.get('street2') or ""
                city = partner.get('city') or ""
                partner_address = f"{street} {street2}, {city}".strip()
                
            manifest.append({
                "assignment_id": assignment.id,
                "odoo_picking_id": assignment.odoo_picking_id,
                "odoo_picking_name": p_data['name'],
                "origin": p_data['origin'] or "",
                "status": assignment.status,
                "customer_name": partner_name,
                "delivery_address": partner_address,
                "phone": partner.get('phone') or "",
                "items": items
            })
            
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to query manifest details from Odoo: {str(e)}"
        )
        
    return manifest

@router.post("/{picking_id}/status")
def update_delivery_status(picking_id: int, request: StatusUpdateRequest, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Updates the local manifest status of an assigned delivery picking.
    Authorized: The specific assigned Delivery Boy.
    """
    role = current_user.get("role")
    user_id = current_user.get("user_id")
    
    if role != "delivery_boy":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied. Only active Delivery Boys can update delivery status."
        )
        
    # 1. Fetch assignment
    assignment = db.query(db_models.DeliveryAssignment).filter(
        db_models.DeliveryAssignment.odoo_picking_id == picking_id,
        db_models.DeliveryAssignment.delivery_boy_id == user_id
    ).first()
    
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The specified picking assignment was not found for this delivery boy."
        )
        
    if request.status not in ["in_transit", "failed"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid status. Must be 'in_transit' or 'failed'."
        )
        
    # 2. Update local state
    assignment.status = request.status
    if request.status == "failed":
        assignment.completed_at = datetime.utcnow()
        
    db.commit()
    return {
        "message": f"Successfully updated status to {request.status}",
        "odoo_picking_id": picking_id,
        "status": assignment.status
    }

@router.post("/{picking_id}/complete")
def complete_delivery(picking_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Completes a delivery. Programmatically triggers the button_validate action in Odoo,
    moving the physical stock to the customer, and logs the completion.
    Authorized: The specific assigned Delivery Boy.
    """
    role = current_user.get("role")
    user_id = current_user.get("user_id")
    
    if role != "delivery_boy":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied. Only active Delivery Boys can validate order completions."
        )
        
    # 1. Fetch assignment
    assignment = db.query(db_models.DeliveryAssignment).filter(
        db_models.DeliveryAssignment.odoo_picking_id == picking_id,
        db_models.DeliveryAssignment.delivery_boy_id == user_id
    ).first()
    
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The specified picking assignment was not found for this delivery boy."
        )
        
    if assignment.status == "delivered":
        return {"message": "This delivery has already been validated and completed.", "status": "delivered"}
        
    # 2. Connect to Odoo and programmatically validate the picking
    try:
        # Step A: Assign stock to ensure inventory reserves
        odoo_models.execute_kw(ODOO_DB, odoo_uid, ODOO_API_KEY, "stock.picking", "action_assign", [[picking_id]])
        
        # Step B: Read moves to populate finished quantities
        moves = odoo_models.execute_kw(
            ODOO_DB, odoo_uid, ODOO_API_KEY,
            "stock.move", "search_read",
            [[("picking_id", "=", picking_id), ("company_id", "=", TRUE_HARVEST_COMPANY_ID)]],
            {"fields": ["id", "product_uom_qty"]}
        )
        
        for move in moves:
            # Set qty_done on each move line to match ordered quantities
            move_lines = odoo_models.execute_kw(
                ODOO_DB, odoo_uid, ODOO_API_KEY,
                "stock.move.line", "search",
                [[("move_id", "=", move["id"]), ("company_id", "=", TRUE_HARVEST_COMPANY_ID)]]
            )
            for line_id in move_lines:
                odoo_models.execute_kw(
                    ODOO_DB, odoo_uid, ODOO_API_KEY,
                    "stock.move.line", "write",
                    [[line_id], {"qty_done": move["product_uom_qty"]}]
                )
                
        # Step C: Execute Odoo Validation
        odoo_models.execute_kw(ODOO_DB, odoo_uid, ODOO_API_KEY, "stock.picking", "button_validate", [[picking_id]])
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Odoo Validation Failed: {str(e)}. Check that there is sufficient stock at the Vendor Location to deliver this order."
        )
        
    # 3. Update local assignment state
    assignment.status = "delivered"
    assignment.completed_at = datetime.utcnow()
    db.commit()
    
    return {
        "message": "Delivery completed and validated in Odoo successfully.",
        "odoo_picking_id": picking_id,
        "status": "delivered"
    }
