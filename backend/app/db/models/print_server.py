import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Enum, Text, Boolean, Integer, ForeignKey
from app.config.database import Base


class PrintServerStatus(str, enum.Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    DISABLED = "DISABLED"
    MAINTENANCE = "MAINTENANCE"


class PrintServer(Base):
    __tablename__ = "print_servers"

    id = Column(String(64), primary_key=True, index=True)  # e.g. PRINT-SERVER-001
    name = Column(String(255), nullable=False)
    location = Column(String(255), nullable=True)
    device_token_hash = Column(String(255), nullable=False, unique=True)

    # Extended agent registration info
    department_id = Column(
        Integer,
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    hostname = Column(String(255), nullable=True)     # e.g. cse-pi-01.local
    ip_address = Column(String(64), nullable=True)    # e.g. 192.168.1.101
    software_version = Column(String(64), nullable=True)  # e.g. 1.4.2
    is_enabled = Column(Boolean, default=True, nullable=False)

    # Runtime state
    status = Column(Enum(PrintServerStatus), default=PrintServerStatus.OFFLINE, nullable=False)
    last_heartbeat = Column(DateTime, nullable=True)
    last_seen = Column(DateTime, nullable=True)
    printer_state = Column(String(64), nullable=True)   # e.g. READY, BUSY, ERROR
    paper_state = Column(String(64), nullable=True)     # e.g. AVAILABLE, LOW, EMPTY

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
