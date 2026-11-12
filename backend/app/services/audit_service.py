import logging
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.db.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


class AuditService:
    @staticmethod
    def log(
        db: Session,
        action: str,
        actor_type: str = "ADMIN",
        user_id: Optional[int] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        meta_data: Optional[Dict[str, Any]] = None,
        commit: bool = False,
    ) -> Optional[AuditLog]:
        """
        Creates and persists an audit log entry.
        Never throws unhandled exceptions to avoid breaking primary workflows.
        """
        try:
            entry = AuditLog(
                user_id=user_id,
                actor_type=actor_type,
                action=action,
                entity_type=entity_type,
                entity_id=str(entity_id) if entity_id is not None else None,
                meta_data=meta_data or {},
            )
            db.add(entry)
            if commit:
                db.commit()
                db.refresh(entry)
            return entry
        except Exception as e:
            logger.warning("Failed to record audit log '%s' on %s:%s: %s", action, entity_type, entity_id, e)
            return None

    @staticmethod
    def get_logs(
        db: Session,
        limit: int = 50,
        offset: int = 0,
        action: Optional[str] = None,
        entity_type: Optional[str] = None,
    ) -> List[AuditLog]:
        """Returns paginated audit log entries."""
        query = db.query(AuditLog)
        if action:
            query = query.filter(AuditLog.action == action)
        if entity_type:
            query = query.filter(AuditLog.entity_type == entity_type)
        return query.order_by(desc(AuditLog.created_at)).offset(offset).limit(limit).all()


audit_service = AuditService()
