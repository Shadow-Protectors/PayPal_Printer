"""
DiscoveredPrinter model.
Stores printers reported by a Print Agent heartbeat that do not match
any administratively registered Printer record.
The backend never creates Printer records automatically; it only logs
the discovery here so an admin can act on it.
"""
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey
from app.config.database import Base


class DiscoveredPrinter(Base):
    __tablename__ = "discovered_printers"

    # Composite ID: server_id + cups_printer_name acts as logical key
    id = Column(String(128), primary_key=True, index=True)
    """Format: '{server_id}::{cups_printer_name}'"""

    server_id = Column(
        String(64),
        ForeignKey("print_servers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cups_printer_name = Column(String(255), nullable=False)
    ip_address = Column(String(64), nullable=True)
    device_uri = Column(String(512), nullable=True)
    reported_status = Column(String(64), nullable=True)   # e.g. READY, BUSY, ERROR
    reported_jobs = Column(String(16), nullable=True)     # queue depth as string
    first_seen = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    last_seen = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                       onupdate=lambda: datetime.now(timezone.utc), nullable=False)

