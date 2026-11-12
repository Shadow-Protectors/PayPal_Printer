from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean
from app.config.database import Base

class OTP(Base):
    __tablename__ = "otps"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    order_id = Column(String(64), ForeignKey("orders.id"), nullable=False, unique=True, index=True)
    otp_hash = Column(String(255), nullable=False, index=True)
    encrypted_value = Column(String(255), nullable=True)
    # Legacy schema field retained for compatibility; order codes do not expire.
    expires_at = Column(DateTime, nullable=False, index=True)
    attempt_count = Column(Integer, default=0, nullable=False)
    used_at = Column(DateTime, nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
