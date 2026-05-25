from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from database import get_db
import models as db_models
from auth_utils import get_current_user
from odoo_client import models as odoo_models, uid as odoo_uid
from config import ODOO_DB, ODOO_API_KEY, TRUE_HARVEST_COMPANY_ID

router = APIRouter(prefix="/barcodes", tags=["Barcode Scanning System"])

# --- Request Schemas ---

class BarcodeVerifyRequest(BaseModel):
    barcode: str

# --- Endpoints ---

@router.get("/scan/{barcode}")
def scan_product(barcode: str, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Looks up a product in Odoo by scanning its barcode.
    Returns product info along with live stock level at the requesting Vendor's location.
    Authorized: Vendor or Admin.
    """
    role = current_user.get("role")
    user_id = current_user.get("user_id")
    
    if role not in ["admin", "vendor"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied. Only Admins or Vendors can perform barcode lookups."
        )
        
    # 1. Query Odoo product by barcode
    try:
        products = odoo_models.execute_kw(
            ODOO_DB, odoo_uid, ODOO_API_KEY,
            'product.product', 'search_read',
            [[
                ('barcode', '=', barcode),
                ('active', '=', True),
                '|',
                ('company_id', '=', TRUE_HARVEST_COMPANY_ID),
                ('company_id', '=', False)
            ]],
            {'fields': ['id', 'name', 'lst_price']}
        )
        if not products:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product with barcode '{barcode}' not found in Odoo."
            )
        product = products[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to query Odoo product registry: {str(e)}"
        )
        
    # 2. Find live quantity on hand at the vendor's stock location
    quantity_on_hand = 0.0
    vendor_location_id = None
    store_name = "Main Office"
    
    if role == "vendor":
        vendor = db.query(db_models.User).filter(db_models.User.id == user_id).first()
        if vendor and vendor.vendor_details and vendor.vendor_details.odoo_location_id:
            vendor_location_id = vendor.vendor_details.odoo_location_id
            store_name = vendor.vendor_details.store_name
            
    if vendor_location_id:
        try:
            quants = odoo_models.execute_kw(
                ODOO_DB, odoo_uid, ODOO_API_KEY,
                'stock.quant', 'search_read',
                [[
                    ('location_id', '=', vendor_location_id),
                    ('product_id', '=', product['id'])
                ]],
                {'fields': ['quantity']}
            )
            if quants:
                quantity_on_hand = quants[0]['quantity']
        except Exception as e:
            pass  # Silent fallback: quantity stays 0.0
            
    return {
        "product_id": product['id'],
        "product_name": product['name'],
        "barcode": barcode,
        "price": product['lst_price'],
        "store_name": store_name,
        "quantity_at_location": quantity_on_hand
    }

@router.post("/verify-scan/{picking_id}")
def verify_manifest_item(picking_id: int, request: BarcodeVerifyRequest, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Rider scans a package barcode to verify if it belongs in the assigned delivery picking manifest,
    preventing delivery errors on-site.
    Authorized: Delivery Boy.
    """
    role = current_user.get("role")
    user_id = current_user.get("user_id")
    
    if role != "delivery_boy":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied. Only active Delivery Boys can run package scans."
        )
        
    # 1. Fetch assignment to ensure authorization
    assignment = db.query(db_models.DeliveryAssignment).filter(
        db_models.DeliveryAssignment.odoo_picking_id == picking_id,
        db_models.DeliveryAssignment.delivery_boy_id == user_id
    ).first()
    
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The specified picking assignment was not found for this delivery boy."
        )
        
    # 2. Look up product by barcode
    try:
        products = odoo_models.execute_kw(
            ODOO_DB, odoo_uid, ODOO_API_KEY,
            'product.product', 'search_read',
            [[('barcode', '=', request.barcode), ('active', '=', True)]],
            {'fields': ['id', 'name']}
        )
        if not products:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Scanned barcode '{request.barcode}' matches no known registry entries."
            )
        scanned_product_id = products[0]['id']
        scanned_product_name = products[0]['name']
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to query Odoo product index: {str(e)}"
        )
        
    # 3. Read Odoo picking items
    try:
        picking = odoo_models.execute_kw(
            ODOO_DB, odoo_uid, ODOO_API_KEY,
            'stock.picking', 'read',
            [[picking_id]],
            {'fields': ['move_ids_without_package']}
        )[0]
        
        move_ids = picking.get('move_ids_without_package', [])
        if not move_ids:
            return {
                "verified": False,
                "error": "This picking order has no active manifest items to deliver."
            }
            
        moves = odoo_models.execute_kw(
            ODOO_DB, odoo_uid, ODOO_API_KEY,
            'stock.move', 'read',
            [move_ids],
            {'fields': ['product_id', 'product_uom_qty']}
        )
        
        # Verify scan against picking list
        matching_move = None
        for m in moves:
            if m['product_id'][0] == scanned_product_id:
                matching_move = m
                break
                
        if matching_move:
            return {
                "verified": True,
                "product_id": scanned_product_id,
                "product_name": scanned_product_name,
                "quantity_expected": matching_move['product_uom_qty'],
                "message": "Item verified! Part of the active order manifest."
            }
        else:
            return {
                "verified": False,
                "error": f"Incorrect item! '{scanned_product_name}' is not part of this order manifest."
            }
            
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to query Odoo stock moves: {str(e)}"
        )
