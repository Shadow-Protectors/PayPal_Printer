"""Background reconciliation worker for Achuppori Platform."""
import logging
import time

from app.config.settings import settings
from app.config.database import SessionLocal
import app.db.base  # noqa: F401 - ensure all models are registered with SQLAlchemy Base
from app.services.cleanup_service import cleanup_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("reconciliation")

def run_once():
    """Execute a single pass of reconciliation and maintenance."""
    with SessionLocal() as db:
        try:
            from app.services.notification_service import deliver_notifications
            deliver_notifications(db)
        except Exception:
            db.rollback()
            log.exception("Notification delivery pass failed")
        try:
            from app.services.refund_service import refund_service
            refund_service.reconcile_pending(db)
        except Exception as exc:
            db.rollback()
            log.warning("Refund reconciliation pass failed: %s", exc)
        try:
            cleanup_service.run_storage_cleanup(db)
        except Exception as exc:
            db.rollback()
            log.warning("Storage cleanup pass failed: %s", exc)

def main():
    log.info("Starting reconciliation worker...")
    interval = getattr(settings, "RECONCILE_INTERVAL_SECONDS", 15)
    while True:
        try:
            run_once()
        except Exception:
            log.exception("Unexpected error in reconciliation loop")
        time.sleep(interval)

if __name__ == "__main__":
    main()
