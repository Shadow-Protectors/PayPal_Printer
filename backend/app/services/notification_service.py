"""Durable, encrypted outbox; SMTP is performed only by the reconciliation worker."""
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import update, delete
from app.db.models.email_notification import EmailNotification
from app.utils.crypto import encrypt_value, decrypt_value

log = logging.getLogger(__name__)


def enqueue_notification(db, payload):
    db.add(EmailNotification(id=str(uuid.uuid4()),
                            payload=encrypt_value(json.dumps(payload)),
                            available_at=datetime.now(timezone.utc).replace(tzinfo=None)))
    db.commit()
    return True


def deliver_notifications(db, limit=20):
    from app.services.email_service import EmailService
    from app.config.settings import settings
    if not settings.ENABLE_EMAIL_STATUS_NOTIFICATIONS:
        return
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.execute(delete(EmailNotification).where(EmailNotification.created_at < now - timedelta(days=7)))
    db.commit()
    ids = db.query(EmailNotification.id).filter(
        EmailNotification.available_at <= now, EmailNotification.attempts < 5
    ).order_by(EmailNotification.available_at).limit(limit).all()
    for (notification_id,) in ids:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        token = str(uuid.uuid4())
        claimed = db.execute(update(EmailNotification).where(
            EmailNotification.id == notification_id,
            EmailNotification.available_at <= now,
            EmailNotification.attempts < 5,
        ).values(available_at=now + timedelta(minutes=5), lease_token=token,
                 attempts=EmailNotification.attempts + 1))
        db.commit()
        if claimed.rowcount != 1:
            continue
        item = db.get(EmailNotification, notification_id)
        try:
            sent = EmailService.send_order_status_notification(**json.loads(decrypt_value(item.payload)))
        except Exception:
            log.exception('Notification delivery failed: %s', notification_id)
            sent = False
        owned = (EmailNotification.id == notification_id, EmailNotification.lease_token == token)
        if sent:
            db.execute(delete(EmailNotification).where(*owned))
        else:
            db.execute(update(EmailNotification).where(*owned).values(
                available_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=30 * 2 ** item.attempts),
                lease_token=None))
            log.warning('Notification %s delivery attempt %s failed', notification_id, item.attempts)
        db.commit()
