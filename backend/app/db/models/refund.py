import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Enum, ForeignKey, Numeric, Text
from app.config.database import Base

class RefundStatus(str, enum.Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class Refund(Base):
    __tablename__ = "refunds"

    id = Column(String(64), primary_key=True, default=lambda: f"ref_{uuid.uuid4().hex[:12]}", index=True)
    order_id = Column(String(64), ForeignKey("orders.id"), nullable=False, unique=True, index=True)
    payment_id = Column(String(64), ForeignKey("payments.id"), nullable=False, index=True)
    razorpay_refund_id = Column(String(128), unique=True, nullable=True, index=True)
    
    amount = Column(Numeric(10, 2), nullable=False)
    reason = Column(String(255), nullable=True)
    status = Column(Enum(RefundStatus), default=RefundStatus.PENDING, nullable=False, index=True)
    error_message = Column(Text, nullable=True)
    
    refund_requested_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    refund_completed_at = Column(DateTime, nullable=True)
