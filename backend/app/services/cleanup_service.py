from datetime import datetime, timezone
from typing import Dict, Any, List
from sqlalchemy.orm import Session

from app.db.models.document import Document, DocumentStatus
from app.db.models.order import Order, OrderStatus
from app.services.storage_service import storage_service

ACTIVE_ORDER_STATUSES = [
    OrderStatus.CREATED,
    OrderStatus.PAID,
    OrderStatus.JOB_QUEUED,
    OrderStatus.WAITING_FOR_OTP,
    OrderStatus.RELEASED,
    OrderStatus.PRINTING,
]

class CleanupService:
    @staticmethod
    def run_storage_cleanup(db: Session) -> Dict[str, Any]:
        """
        Scans for documents in CLEANUP_PENDING status, verifies no active orders reference them,
        and safely removes the physical file from the storage directory.
        """
        pending_docs = db.query(Document).filter(
            Document.status == DocumentStatus.CLEANUP_PENDING
        ).all()

        deleted_count = 0
        skipped_count = 0
        failed_count = 0

        for doc in pending_docs:
            # Check for any active orders referencing this document
            active_orders = db.query(Order).filter(
                Order.document_id == doc.id,
                Order.status.in_(ACTIVE_ORDER_STATUSES)
            ).count()

            if active_orders > 0:
                skipped_count += 1
                continue

            # Delete physical file
            try:
                storage_service.delete_file(doc.storage_key)
                doc.status = DocumentStatus.DELETED
                doc.deleted_at = datetime.now(timezone.utc)
                deleted_count += 1
            except Exception:
                failed_count += 1

        db.commit()
        return {
            "deleted_documents": deleted_count,
            "skipped_active": skipped_count,
            "failed_deletions": failed_count
        }

cleanup_service = CleanupService()
