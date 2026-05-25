from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session
from database import get_db
import models as db_models
from auth_utils import get_current_user
from odoo_client import models as odoo_models, uid as odoo_uid
from config import ODOO_DB, ODOO_API_KEY, TRUE_HARVEST_COMPANY_ID

router = APIRouter(prefix="/consignment", tags=["Consignment & Refills"])

# --- Request Schemas ---

class RefillCreationRequest(BaseModel):
    odoo_product_id: int
    requested_quantity: int

# --- Helper Functions ---

def _get_warehouse_stock_location() -> int:
    """Helper to query Odoo and resolve the main warehouse stock location ID (WH/Stock)."""
    try:
        # Search for WH/Stock or main internal stock location
        loc_ids = odoo_models.execute_kw(
            ODOO_DB, odoo_uid, ODOO_API_KEY,
            'stock.location', 'search',
            [[
                ('complete_name', '=', 'WH/Stock'),
                ('company_id', '=', TRUE_HARVEST_COMPANY_ID)
            ]]
        )
        if loc_ids:
            return loc_ids[0]
            
        # Fallback: search for first active internal Stock location under company 3
        fallback_ids = odoo_models.execute_kw(
            ODOO_DB, odoo_uid, ODOO_API_KEY,
            'stock.location', 'search',
            [[
                ('name', '=', 'Stock'),
                ('usage', '=', 'internal'),
                ('company_id', '=', TRUE_HARVEST_COMPANY_ID)
            ]]
        )
        if fallback_ids:
            return fallback_ids[0]
            
        # Hard fallback: first internal location
        any_internal = odoo_models.execute_kw(
            ODOO_DB, odoo_uid, ODOO_API_KEY,
            'stock.location', 'search',
            [[
                ('usage', '=', 'internal'),
                ('company_id', '=', TRUE_HARVEST_COMPANY_ID)
            ]]
        )
        if any_internal:
            return any_internal[0]
            
        raise Exception("No active internal stock locations found in Odoo for Company 3.")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to resolve main warehouse stock location in Odoo: {str(e)}"
        )

# --- Endpoints ---

@router.get("/stock")
def get_vendor_stock(vendor_user_id: Optional[int] = None, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Queries current stock quantities sitting at the vendor's physical Odoo stock.location.
    Authorized: Admin or Vendor.
    """
    role = current_user.get("role")
    user_id = current_user.get("user_id")
    
    # 1. Access Control
    if role == "vendor":
        target_user_id = user_id
    elif role == "admin":
        if not vendor_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admin must specify vendor_user_id query parameter."
            )
        target_user_id = vendor_user_id
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied. Only Admins or Vendors can check consignment stock."
        )
        
    # 2. Fetch vendor details
    vendor = db.query(db_models.User).filter(db_models.User.id == target_user_id).first()
    if not vendor or not vendor.vendor_details:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vendor details not found in database."
        )
        
    odoo_location_id = vendor.vendor_details.odoo_location_id
    if not odoo_location_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This vendor does not have an Odoo stock.location assigned."
        )
        
    # 3. Query stock.quant in Odoo
    try:
        quants = odoo_models.execute_kw(
            ODOO_DB, odoo_uid, ODOO_API_KEY,
            'stock.quant', 'search_read',
            [[
                ('location_id', '=', odoo_location_id),
                ('quantity', '>', 0),
                ('product_id.active', '=', True)
            ]],
            {'fields': ['product_id', 'quantity']}
        )
        
        stock_list = []
        for q in quants:
            product_id = q['product_id'][0]
            product_name = q['product_id'][1]
            quantity = q['quantity']
            
            # Fetch barcode for display
            product_details = odoo_models.execute_kw(
                ODOO_DB, odoo_uid, ODOO_API_KEY,
                'product.product', 'read',
                [[product_id]],
                {'fields': ['barcode']}
            )
            barcode = product_details[0].get('barcode') or "No Barcode"
            
            stock_list.append({
                "product_id": product_id,
                "product_name": product_name,
                "barcode": barcode,
                "quantity": quantity
            })
            
        return {
            "vendor_name": vendor.name,
            "store_name": vendor.vendor_details.store_name,
            "odoo_location_id": odoo_location_id,
            "stock": stock_list
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to query stock from Odoo: {str(e)}"
        )

@router.post("/refill-request")
def create_refill_request(request: RefillCreationRequest, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Vendor requests a stock refill.
    Authorized: Vendor.
    """
    role = current_user.get("role")
    user_id = current_user.get("user_id")
    
    if role != "vendor":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied. Only active Vendors can request consignment refills."
        )
        
    # 1. Verify product exists in Odoo and belongs to True Harvest (Company 3)
    try:
        product = odoo_models.execute_kw(
            ODOO_DB, odoo_uid, ODOO_API_KEY,
            'product.product', 'search_read',
            [[
                ('id', '=', request.odoo_product_id),
                ('active', '=', True),
                '|',
                ('company_id', '=', TRUE_HARVEST_COMPANY_ID),
                ('company_id', '=', False)
            ]],
            {'fields': ['name']}
        )
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product with Odoo ID {request.odoo_product_id} not found."
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to verify product in Odoo: {str(e)}"
        )
        
    # 2. Save local refill request
    refill = db_models.RefillRequest(
        vendor_id=user_id,
        odoo_product_id=request.odoo_product_id,
        requested_quantity=request.requested_quantity,
        status="requested"
    )
    db.add(refill)
    db.commit()
    db.refresh(refill)
    
    return {
        "message": "Stock refill request submitted successfully.",
        "request_id": refill.id,
        "product_name": product[0]['name'],
        "requested_quantity": refill.requested_quantity,
        "status": refill.status
    }

@router.get("/refill-requests")
def list_refill_requests(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Lists all consignment refill requests (pending and historical).
    Authorized: Admin.
    """
    role = current_user.get("role")
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied. Only Administrators can view the refill master log."
        )
        
    requests = db.query(db_models.RefillRequest).order_by(db_models.RefillRequest.requested_at.desc()).all()
    
    log_list = []
    for r in requests:
        # Retrieve product name from Odoo
        try:
            p_data = odoo_models.execute_kw(
                ODOO_DB, odoo_uid, ODOO_API_KEY,
                'product.product', 'read',
                [[r.odoo_product_id]],
                {'fields': ['name']}
            )
            product_name = p_data[0]['name'] if p_data else "Unknown Product"
        except:
            product_name = "Unknown Product"
            
        log_list.append({
            "id": r.id,
            "vendor_name": r.vendor.name,
            "store_name": r.vendor.vendor_details.store_name if r.vendor.vendor_details else "No Store Name",
            "odoo_product_id": r.odoo_product_id,
            "product_name": product_name,
            "requested_quantity": r.requested_quantity,
            "status": r.status,
            "odoo_picking_id": r.odoo_picking_id,
            "requested_at": r.requested_at.isoformat() if r.requested_at else None,
            "processed_at": r.processed_at.isoformat() if r.processed_at else None
        })
        
    return log_list

@router.post("/refill-requests/{request_id}/approve")
def approve_refill_request(request_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Approves a consignment refill request. Programmatically executes a validated 
    Odoo Internal Transfer, moving stock from the main warehouse to the vendor's location.
    Authorized: Admin.
    """
    role = current_user.get("role")
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied. Only Administrators can approve refill requests."
        )
        
    # 1. Fetch Request
    request = db.query(db_models.RefillRequest).filter(db_models.RefillRequest.id == request_id).first()
    if not request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The specified refill request was not found."
        )
        
    if request.status != "requested":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Refill request cannot be approved because its current status is: '{request.status}'."
        )
        
    # 2. Fetch target vendor details
    vendor = request.vendor
    if not vendor or not vendor.vendor_details or not vendor.vendor_details.odoo_location_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The requesting vendor does not have a configured Odoo stock.location."
        )
        
    dest_location_id = vendor.vendor_details.odoo_location_id
    src_location_id = _get_warehouse_stock_location()
    
    if src_location_id == dest_location_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source and destination locations are identical. Cannot refill."
        )
        
    # 3. Connect to Odoo and execute Internal Transfer
    try:
        # Step A: Find the internal transfer picking type
        picking_types = odoo_models.execute_kw(
            ODOO_DB, odoo_uid, ODOO_API_KEY,
            'stock.picking.type', 'search',
            [[
                ('code', '=', 'internal'),
                ('company_id', '=', TRUE_HARVEST_COMPANY_ID)
            ]]
        )
        if not picking_types:
            raise Exception("Odoo 'internal' picking type not found for Company 3.")
        picking_type_id = picking_types[0]
        
        # Step B: Create picking header (internal transfer)
        picking_id = odoo_models.execute_kw(
            ODOO_DB, odoo_uid, ODOO_API_KEY,
            'stock.picking', 'create',
            [{
                'picking_type_id': picking_type_id,
                'location_id': src_location_id,
                'location_dest_id': dest_location_id,
                'company_id': TRUE_HARVEST_COMPANY_ID,
                'origin': f"Consignment Refill Request #{request.id}"
            }]
        )
        
        # Step C: Get unit of measure (UOM) ID for the product
        product = odoo_models.execute_kw(
            ODOO_DB, odoo_uid, ODOO_API_KEY,
            'product.product', 'read',
            [[request.odoo_product_id]],
            {'fields': ['uom_id']}
        )[0]
        uom_id = product['uom_id'][0]
        
        # Step D: Create stock move line
        move_id = odoo_models.execute_kw(
            ODOO_DB, odoo_uid, ODOO_API_KEY,
            'stock.move', 'create',
            [{
                'name': f"Refill: {product['uom_id'][1]}",
                'picking_id': picking_id,
                'product_id': request.odoo_product_id,
                'product_uom_qty': request.requested_quantity,
                'product_uom': uom_id,
                'location_id': src_location_id,
                'location_dest_id': dest_location_id,
                'company_id': TRUE_HARVEST_COMPANY_ID
            }]
        )
        
        # Step E: Trigger Odoo Confirm and Reserve
        odoo_models.execute_kw(ODOO_DB, odoo_uid, ODOO_API_KEY, "stock.picking", "action_confirm", [[picking_id]])
        odoo_models.execute_kw(ODOO_DB, odoo_uid, ODOO_API_KEY, "stock.picking", "action_assign", [[picking_id]])
        
        # Step F: Set finished quantities on move lines
        moves = odoo_models.execute_kw(
            ODOO_DB, odoo_uid, ODOO_API_KEY,
            "stock.move", "search_read",
            [[("picking_id", "=", picking_id), ("company_id", "=", TRUE_HARVEST_COMPANY_ID)]],
            {"fields": ["id", "product_uom_qty"]}
        )
        for move in moves:
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
                
        # Step G: Programmatically validate transfer
        odoo_models.execute_kw(ODOO_DB, odoo_uid, ODOO_API_KEY, "stock.picking", "button_validate", [[picking_id]])
        
    except Exception as e:
        # If Odoo validation failed, log why (typically out of stock in main WH)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Refill Transfer Failed in Odoo: {str(e)}. Please check that there is sufficient stock in the main warehouse to fulfill this refill."
        )
        
    # 4. Save local approved state
    request.status = "approved"
    request.odoo_picking_id = picking_id
    request.processed_at = datetime.utcnow()
    db.commit()
    
    return {
        "message": "Consignment refill approved and validated in Odoo successfully.",
        "request_id": request.id,
        "odoo_picking_id": picking_id,
        "status": "approved"
    }
