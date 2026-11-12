import enum
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Enum, ForeignKey, Numeric, JSON
from app.config.database import Base

class OrderStatus(str, enum.Enum):
    CREATED = "CREATED"
    PAID = "PAID"
    JOB_QUEUED = "JOB_QUEUED"
    WAITING_FOR_OTP = "WAITING_FOR_OTP"
    RELEASED = "RELEASED"
    PRINTING = "PRINTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"

class Order(Base):
    __tablename__ = "orders"

    id = Column(String(64), primary_key=True, index=True) # e.g. ORD-20260929-0001
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    roll_number = Column(String(50), nullable=True, index=True)
    department = Column(String(100), nullable=True, index=True)
    document_id = Column(String(64), ForeignKey("documents.id"), nullable=False, index=True)
    print_server_id = Column(String(64), ForeignKey("print_servers.id"), nullable=False, index=True)
    
    # Print settings (JSON object containing copies, page_range, colour, sides, paper_size, orientation)
    print_settings = Column(JSON, nullable=False)
    
    total_pages = Column(Integer, nullable=False)
    copies = Column(Integer, nullable=False, default=1)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(10), default="INR", nullable=False)
    
    status = Column(Enum(OrderStatus), default=OrderStatus.CREATED, nullable=False, index=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
