# app/db/base.py
# Import Base and all models so SQLAlchemy metadata is aware of all models

from app.config.database import Base
from app.db.models.department import Department
from app.db.models.user import User, UserRole
from app.db.models.refresh_token import RefreshToken
from app.db.models.document import Document, DocumentStatus
from app.db.models.print_server import PrintServer, PrintServerStatus
from app.db.models.printer import Printer
from app.db.models.order import Order, OrderStatus
from app.db.models.payment import Payment, PaymentStatus
from app.db.models.print_job import PrintJob, PrintJobStatus
from app.db.models.otp import OTP
from app.db.models.refund import Refund, RefundStatus
from app.db.models.idempotency import IdempotencyKey
from app.db.models.audit_log import AuditLog
from app.db.models.discovered_printer import DiscoveredPrinter
from app.db.models.platform_setting import PlatformSetting
from app.db.models.revoked_session import RevokedSession
from app.db.models.email_notification import EmailNotification

__all__ = [
    "Base",
    "Department",
    "User",
    "UserRole",
    "RefreshToken",
    "Document",
    "DocumentStatus",
    "PrintServer",
    "PrintServerStatus",
    "Printer",
    "Order",
    "OrderStatus",
    "Payment",
    "PaymentStatus",
    "PrintJob",
    "PrintJobStatus",
    "OTP",
    "Refund",
    "RefundStatus",
    "IdempotencyKey",
    "AuditLog",
    "DiscoveredPrinter",
]
