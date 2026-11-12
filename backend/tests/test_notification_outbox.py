import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from app.db.models.email_notification import EmailNotification
from app.db.models.order import Order, OrderStatus
from app.db.models.print_job import PrintJob, PrintJobStatus
from app.services.job_service import job_service
from app.services.email_service import EmailService
from app.services.notification_service import deliver_notifications, enqueue_notification
from app.config.settings import settings
from app.utils.crypto import decrypt_value


def test_claim_enqueues_without_smtp(db_session, test_print_server, monkeypatch):
    send = Mock(side_effect=AssertionError('SMTP must never run inside a job claim'))
    monkeypatch.setattr(EmailService, 'send_order_status_notification', send)
    order = Order(id='queued-order', document_id='doc', print_server_id=test_print_server.id,
                  print_settings={'notification_email': 'user@example.invalid'}, total_pages=1,
                  copies=1, amount=2, currency='INR', status=OrderStatus.RELEASED)
    db_session.add(order)
    db_session.flush()
    job = PrintJob(id='queued-job', order_id=order.id, server_id=test_print_server.id,
                   status=PrintJobStatus.RELEASED)
    db_session.add(job)
    db_session.commit()
    assert job_service.claim_job(db_session, test_print_server.id, job.id)
    send.assert_not_called()
    queued = db_session.query(EmailNotification).one()
    assert 'user@example.invalid' not in queued.payload
    assert json.loads(decrypt_value(queued.payload))['status'] == 'PRINTING'


def test_failed_delivery_retries_and_success_removes_payload(db_session, monkeypatch):
    send = Mock(side_effect=[False, True])
    monkeypatch.setattr(EmailService, 'send_order_status_notification', send)
    enqueue_notification(db_session, {'to_email': 'user@example.invalid', 'order_id': 'order', 'status': 'COMPLETED'})
    deliver_notifications(db_session)
    item = db_session.query(EmailNotification).one()
    assert item.attempts == 1
    deliver_notifications(db_session)
    assert send.call_count == 1
    item.available_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    db_session.commit()
    deliver_notifications(db_session)
    assert send.call_count == 2
    assert db_session.query(EmailNotification).count() == 0


def test_worker_respects_active_lease(db_session, monkeypatch):
    send = Mock(return_value=True)
    monkeypatch.setattr(EmailService, 'send_order_status_notification', send)
    enqueue_notification(db_session, {'to_email': 'user@example.invalid', 'order_id': 'order', 'status': 'COMPLETED'})
    item = db_session.query(EmailNotification).one()
    item.lease_token = 'another-worker'
    item.available_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5)
    db_session.commit()
    deliver_notifications(db_session)
    send.assert_not_called()


def test_notification_escapes_html_preserves_plain_text(monkeypatch):
    monkeypatch.setattr(settings, 'EMAIL_PROVIDER', 'smtp')
    send = Mock(return_value=True)
    monkeypatch.setattr(EmailService, '_dispatch_smtp', send)
    filename = '<a href="https://example.invalid">report</a>'
    assert EmailService.send_order_status_notification('user@example.invalid', 'order', 'COMPLETED', document_name=filename)
    assert filename in send.call_args.args[2]
    assert filename not in send.call_args.args[3]
    assert '&lt;a href=' in send.call_args.args[3]
