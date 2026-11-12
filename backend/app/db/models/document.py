import enum
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Enum, ForeignKey, BigInteger
from app.config.database import Base

class DocumentStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    CLEANUP_PENDING = "CLEANUP_PENDING"
    DELETED = "DELETED"
    EXPIRED = "EXPIRED"

class Document(Base):
    __tablename__ = "documents"

    id = Column(String(64), primary_key=True, index=True) # e.g. doc_01JXYZ
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    session_token = Column(String(512), nullable=True)
    original_filename = Column(String(255), nullable=False)
    stored_filename = Column(String(255), nullable=False)
    storage_key = Column(String(512), nullable=False, unique=True, index=True)
    mime_type = Column(String(128), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    sha256 = Column(String(64), nullable=False)
    page_count = Column(Integer, nullable=False, default=1)
    status = Column(Enum(DocumentStatus), default=DocumentStatus.ACTIVE, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)
