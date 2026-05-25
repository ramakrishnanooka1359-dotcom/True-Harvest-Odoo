from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    role = Column(String, nullable=False)  # "admin", "vendor", "delivery_boy"
    
    # Hierarchical fields
    warehouse_id = Column(Integer, nullable=True)  # maps to stock.warehouse
    admin_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    vendor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Odoo Master Data Mapping ID
    odoo_partner_id = Column(Integer, nullable=True, unique=True)  # maps to res.partner
    
    # Parent-child relational definitions
    admin = relationship("User", remote_side=[id], foreign_keys=[admin_id])
    vendor = relationship("User", remote_side=[id], foreign_keys=[vendor_id])
    
    vendor_details = relationship("VendorDetail", back_populates="user", uselist=False, cascade="all, delete-orphan")
    delivery_boy_details = relationship("DeliveryBoyDetail", back_populates="user", uselist=False, cascade="all, delete-orphan")
    
    # Relationships for logistics
    assignments = relationship("DeliveryAssignment", back_populates="delivery_boy")
    refills = relationship("RefillRequest", back_populates="vendor")

class VendorDetail(Base):
    __tablename__ = "vendor_details"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    store_name = Column(String, nullable=False)
    store_address = Column(String, nullable=True)
    odoo_location_id = Column(Integer, nullable=True)  # maps to stock.location
    
    user = relationship("User", back_populates="vendor_details")

class DeliveryBoyDetail(Base):
    __tablename__ = "delivery_boy_details"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    vehicle_type = Column(String, nullable=True)  # "bike", "car", "van"
    license_plate = Column(String, nullable=True)
    status = Column(String, default="inactive")  # "active", "inactive"
    
    user = relationship("User", back_populates="delivery_boy_details")

class DeliveryAssignment(Base):
    __tablename__ = "delivery_assignments"
    
    id = Column(Integer, primary_key=True, index=True)
    delivery_boy_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    odoo_picking_id = Column(Integer, nullable=False, unique=True, index=True)  # maps to stock.picking
    status = Column(String, default="assigned")  # "assigned", "in_transit", "delivered", "failed"
    
    assigned_at = Column(DateTime, default=func.now())
    completed_at = Column(DateTime, nullable=True)
    
    delivery_boy = relationship("User", back_populates="assignments")

class RefillRequest(Base):
    __tablename__ = "refill_requests"
    
    id = Column(Integer, primary_key=True, index=True)
    vendor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    odoo_product_id = Column(Integer, nullable=False)  # Odoo product.product ID
    requested_quantity = Column(Integer, nullable=False)
    status = Column(String, default="requested")  # "requested", "approved", "rejected"
    
    odoo_picking_id = Column(Integer, nullable=True)  # maps to created Odoo internal transfer picking
    
    requested_at = Column(DateTime, default=func.now())
    processed_at = Column(DateTime, nullable=True)
    
    vendor = relationship("User", back_populates="refills")
