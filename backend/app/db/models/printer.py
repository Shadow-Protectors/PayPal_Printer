from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean, Integer
from app.config.database import Base


class Printer(Base):
    __tablename__ = "printers"

    id = Column(String(64), primary_key=True, index=True)
    server_id = Column(
        String(64),
        ForeignKey("print_servers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    department_id = Column(
        Integer,
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Identity / CUPS / Network
    cups_printer_name = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=False)
    ip_address = Column(String(64), nullable=True)     # e.g. 192.168.1.100
    protocol = Column(String(32), default="Socket", nullable=False) # IPP, Socket, LPD
    device_uri = Column(String(512), nullable=True)    # e.g. socket://192.168.1.100:9100
    model = Column(String(255), nullable=True)         # e.g. HP LaserJet Pro M404dn
    location = Column(String(255), nullable=True)      # e.g. Ground Floor Lab
    description = Column(String(512), nullable=True)

    # Capabilities & Administrative Status
    supports_color = Column(Boolean, default=True, nullable=False)
    supports_duplex = Column(Boolean, default=True, nullable=False)
    is_enabled = Column(Boolean, default=True, nullable=False)   # Admin enable/disable toggle
    is_active = Column(Boolean, default=False, nullable=False)   # Only Active after successful Test Connection

    # Real-time health & Connection Validation
    printer_status = Column(String(64), nullable=True)   # READY, BUSY, OFFLINE, ERROR
    job_count = Column(Integer, default=0, nullable=False)
    last_seen = Column(DateTime, nullable=True)
    last_tested_at = Column(DateTime, nullable=True)
    test_status = Column(String(32), default="PENDING", nullable=False)  # PENDING, SUCCESS, FAILED
    test_message = Column(String(512), nullable=True)

    # Heartbeat Mismatch Diagnostics
    has_mismatch = Column(Boolean, default=False, nullable=False)
    mismatch_details = Column(String(512), nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

