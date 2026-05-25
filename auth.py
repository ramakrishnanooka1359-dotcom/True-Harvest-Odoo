from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from typing import Optional
from datetime import timedelta
from sqlalchemy.orm import Session
from database import get_db
import models as db_models
from auth_utils import create_access_token, verify_password, get_password_hash
from odoo_client import models as odoo_models, uid as odoo_uid
from config import ODOO_DB, ODOO_API_KEY, TRUE_HARVEST_COMPANY_ID, ACCESS_TOKEN_EXPIRE_MINUTES

router = APIRouter(prefix="/auth", tags=["auth"])

# --- Request Schemas ---

class LoginRequest(BaseModel):
    username: str  # Email is used as username
    password: str

class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str

    phone: Optional[str] = None
    role: str  # "admin", "vendor", "delivery_boy"
    
    # Hierarchy mappings
    warehouse_id: Optional[int] = None
    admin_id: Optional[int] = None
    vendor_id: Optional[int] = None
    
    # Role-specific fields
    store_name: Optional[str] = None
    store_address: Optional[str] = None
    odoo_location_id: Optional[int] = None  # maps to stock.location in Odoo
    
    # Delivery Boy specific
    vehicle_type: Optional[str] = None
    license_plate: Optional[str] = None

# --- Helper Functions ---

def _provision_odoo_partner(request: RegisterRequest) -> int:
    """Helper to programmatically create a res.partner in Odoo under Company 3."""
    try:
        partner_vals = {
            'name': request.name,
            'email': request.email,
            'phone': request.phone,
            'mobile': request.phone,
            'company_id': TRUE_HARVEST_COMPANY_ID,
            'customer_rank': 0,
            'supplier_rank': 1 if request.role == 'vendor' else 0,
        }
        
        # Tag delivery boys as "Delivery Personnel"
        if request.role == 'delivery_boy':
            # Check if "Delivery Personnel" tag exists, create if not
            tag_ids = odoo_models.execute_kw(
                ODOO_DB, odoo_uid, ODOO_API_KEY,
                'res.partner.category', 'search',
                [[('name', '=', 'Delivery Personnel')]]
            )
            if not tag_ids:
                tag_id = odoo_models.execute_kw(
                    ODOO_DB, odoo_uid, ODOO_API_KEY,
                    'res.partner.category', 'create',
                    [{'name': 'Delivery Personnel'}]
                )
            else:
                tag_id = tag_ids[0]
            
            # Map the many-to-many relationship
            partner_vals['category_id'] = [[6, 0, [tag_id]]]
            
        # Create partner record in Odoo
        partner_id = odoo_models.execute_kw(
            ODOO_DB, odoo_uid, ODOO_API_KEY,
            'res.partner', 'create',
            [partner_vals]
        )
        return partner_id
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to auto-provision partner in Odoo: {str(e)}"
        )

# --- Router Endpoints ---

@router.post("/register")
def register(request: RegisterRequest, db: Session = Depends(get_db)):

    """
    Registers a new platform user locally (Admin, Vendor, or Delivery Boy),
    hashes their credentials, auto-provisions their Partner record in Odoo (Company 3),
    and sets up their local hierarchical details.
    """
    # 1. Check if user already exists
    existing_user = db.query(db_models.User).filter(db_models.User.email == request.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email address already exists."
        )
        
    # 2. Provision partner in Odoo (strict Company ID 3 isolation)
    odoo_partner_id = _provision_odoo_partner(request)
    
    # 3. Create local user record
    hashed_password = get_password_hash(request.password)
    new_user = db_models.User(
        name=request.name,
        email=request.email,
        password_hash=hashed_password,
        phone=request.phone,
        role=request.role,
        warehouse_id=request.warehouse_id,
        admin_id=request.admin_id,
        vendor_id=request.vendor_id,
        odoo_partner_id=odoo_partner_id
    )
    db.add(new_user)
    db.flush()  # Flushes to DB to populate new_user.id
    
    # 4. Handle role-specific details
    if request.role == 'vendor':
        if not request.store_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="store_name is required for vendor registration."
            )
        vendor_detail = db_models.VendorDetail(
            user_id=new_user.id,
            store_name=request.store_name,
            store_address=request.store_address,
            odoo_location_id=request.odoo_location_id
        )
        db.add(vendor_detail)
        
    elif request.role == 'delivery_boy':
        delivery_detail = db_models.DeliveryBoyDetail(
            user_id=new_user.id,
            vehicle_type=request.vehicle_type,
            license_plate=request.license_plate,
            status="inactive"
        )
        db.add(delivery_detail)
        
    # 5. Save changes to DB
    db.commit()
    db.refresh(new_user)
    
    return {
        "message": f"Successfully registered user with role '{request.role}'",
        "user_id": new_user.id,
        "name": new_user.name,
        "email": new_user.email,
        "role": new_user.role,
        "odoo_partner_id": new_user.odoo_partner_id
    }

@router.post("/login")
def login(request: LoginRequest, db: Session = Depends(get_db)):
    """
    Authenticates a user locally and returns a JWT access token.
    Decoupled from direct Odoo password lookups for speed and security.
    """
    # 1. Fetch user by email
    user = db.query(db_models.User).filter(db_models.User.email == request.username).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    # 2. Verify password hash
    if not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    # 3. Retrieve detail information
    mobile = user.phone
    phone = user.phone
    
    # 4. Generate local JWT access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": user.email, 
            "odoo_uid": odoo_uid,  # Master API Odoo system uid
            "user_id": user.id,
            "odoo_partner_id": user.odoo_partner_id,
            "name": user.name,
            "role": user.role,
            "email": user.email
        },
        expires_delta=access_token_expires
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user.id,
        "username": user.email,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "odoo_partner_id": user.odoo_partner_id,
        "mobile": mobile,
        "phone": phone
    }
