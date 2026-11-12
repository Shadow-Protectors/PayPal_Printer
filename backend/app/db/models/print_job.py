import enum
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Enum, ForeignKey, Text
from app.config.database import Base

class PrintJobStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RELEASED = "RELEASED"
    PRINTING = "PRINTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    FINAL_FAILED = "FINAL_FAILED"
    CANCELLED = "CANCELLED"

class PrintJob(Base):
    __tablename__ = "print_jobs"

    id = Column(String(64), primary_key=True, index=True) # e.g. job_001
    order_id = Column(String(64), ForeignKey("orders.id"), nullable=False, unique=True, index=True)
    server_id = Column(String(64), ForeignKey("print_servers.id"), nullable=False, index=True)
    printer_id = Column(String(64), ForeignKey("printers.id", ondelete="SET NULL"), nullable=True, index=True)
    
    cups_job_id = Column(String(128), nullable=True)
    last_status_event = Column(String(64), nullable=True)
    status = Column(Enum(PrintJobStatus), default=PrintJobStatus.QUEUED, nullable=False, index=True)
    retry_count = Column(Integer, default=0, nullable=False)
    error_code = Column(String(128), nullable=True)
    error_message = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
