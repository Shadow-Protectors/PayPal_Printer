from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, JSON
from app.config.database import Base

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, nullable=True, index=True)
    actor_type = Column(String(64), nullable=False) # e.g. USER, AGENT, SYSTEM, ADMIN
    action = Column(String(128), nullable=False, index=True) # e.g. LOGIN, DOCUMENT_UPLOAD, OTP_VERIFIED
    entity_type = Column(String(64), nullable=True) # e.g. Document, Order, Payment
    entity_id = Column(String(128), nullable=True, index=True)
    meta_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
