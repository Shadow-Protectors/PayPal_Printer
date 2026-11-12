import pytest
from unittest.mock import MagicMock
from app.config.settings import settings
from app.db.models.order import Order, OrderStatus
from app.db.models.print_job import PrintJob, PrintJobStatus
from app.db.models.user import User, UserRole
from app.db.models.document import Document, DocumentStatus
from app.services.email_service import email_service, EmailService
from app.services.notification_service import deliver_notifications
from app.schemas.agent import AgentJobStatusUpdate
from app.services.job_service import job_service
from tests.conftest import get_auth_token

def test_send_order_status_notification_mock(monkeypatch):
    """Test send_order_status_notification generates notifications for all statuses in mock mode."""
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "mock")
    for st in ["WAITING_FOR_OTP", "PRINTING", "COMPLETED", "FAILED", "CANCELLED", "REFUNDED"]:
        result = EmailService.send_order_status_notification(
            to_email="student@campus.edu",
            order_id="ORD-TEST-1234",
            status=st,
            recipient_name="Alex Student",
            otp_code="987654" if st == "WAITING_FOR_OTP" else None,
            station_name="Library Main Kiosk",
            printer_name="HP LaserJet",
            document_name="Project_Report.pdf",
            total_pages=5,
            copies=1,
            amount=10.0,
            currency="INR",
            error_message="Paper jam detected" if st == "FAILED" else None,
            refund_status="PROCESSED" if st in ("FAILED", "REFUNDED") else None,
        )
        assert result is True

def test_dispatch_smtp_success(monkeypatch):
    """Test that _dispatch_smtp sends email correctly via smtplib."""
    mock_smtp = MagicMock()
    mock_server_instance = MagicMock()
    mock_smtp.return_value.__enter__.return_value = mock_server_instance
    monkeypatch.setattr("smtplib.SMTP", mock_smtp)

    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "smtp")
    monkeypatch.setattr(settings, "SMTP_USER", "test@test.local")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "secret_pass")
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.test.local")
    monkeypatch.setattr(settings, "SMTP_PORT", 587)

    res = EmailService._dispatch_smtp("student@test.local", "Test Subject", "Text Content", "<p>Html Content</p>")
    assert res is True
    assert mock_server_instance.starttls.called
    assert mock_server_instance.login.called
    assert mock_server_instance.sendmail.called

def test_notify_order_status_resolution(db_session, test_print_server, test_user, monkeypatch):
    """Test notify_order_status resolves user email and metadata correctly."""
    doc = Document(
        id="doc_notif_01",
        user_id=test_user.id,
        original_filename="Assignment.pdf",
        stored_filename="test_doc.pdf",
        storage_key="test_doc.pdf",
        file_size=1024,
        sha256="dummy_sha256",
        mime_type="application/pdf",
        page_count=2,
        status=DocumentStatus.ACTIVE
    )
    db_session.add(doc)
    db_session.flush()

    order = Order(
        id="ORD-NOTIF-001",
        user_id=test_user.id,
        roll_number="CS2026",
        department="Computer Science",
        document_id=doc.id,
        print_server_id=test_print_server.id,
        print_settings={"printer_name": "Brother Laser", "copies": 1},
        total_pages=2,
        copies=1,
        amount=4.00,
        currency="INR",
        status=OrderStatus.PRINTING
    )
    db_session.add(order)
    db_session.commit()

    captured = []
    def fake_send(to_email, order_id, status, **kwargs):
        captured.append({"email": to_email, "order_id": order_id, "status": status, "kwargs": kwargs})
        return True

    monkeypatch.setattr(EmailService, "send_order_status_notification", staticmethod(fake_send))

    sent = email_service.notify_order_status(db_session, order, OrderStatus.PRINTING)
    assert sent is True
    assert captured == []
    deliver_notifications(db_session)
    assert len(captured) == 1
    assert captured[0]["email"] == test_user.email
    assert captured[0]["order_id"] == "ORD-NOTIF-001"
    assert captured[0]["status"] == "PRINTING"
    assert captured[0]["kwargs"]["station_name"] == test_print_server.name
    assert captured[0]["kwargs"]["document_name"] == "Assignment.pdf"

def test_notify_order_status_guest_notification_email(db_session, test_print_server, monkeypatch):
    """Test guest order with notification_email in settings."""
    order = Order(
        id="ORD-GUEST-002",
        user_id=None,
        document_id="doc_any",
        print_server_id=test_print_server.id,
        print_settings={"notification_email": "guest_user@example.com", "printer_name": "Epson"},
        total_pages=3,
        copies=2,
        amount=12.00,
        currency="INR",
        status=OrderStatus.COMPLETED
    )
    db_session.add(order)
    db_session.commit()

    captured = []
    monkeypatch.setattr(
        EmailService,
        "send_order_status_notification",
        staticmethod(lambda to_email, order_id, status, **kw: captured.append((to_email, order_id, status)) or True)
    )

    sent = email_service.notify_order_status(db_session, order, OrderStatus.COMPLETED)
    assert sent is True
    assert captured == []
    deliver_notifications(db_session)
    assert len(captured) == 1
    assert captured[0] == ("guest_user@example.com", "ORD-GUEST-002", "COMPLETED")

def test_notify_order_status_no_email_graceful(db_session):
    """Test order with no associated email returns False without error."""
    order = Order(
        id="ORD-NO-EMAIL",
        user_id=None,
        document_id="doc_missing",
        print_server_id="srv_any",
        print_settings={},
        total_pages=1,
        copies=1,
        amount=2.00,
        currency="INR",
        status=OrderStatus.COMPLETED
    )
    db_session.add(order)
    db_session.commit()

    assert email_service.notify_order_status(db_session, order, OrderStatus.COMPLETED) is False

def test_job_service_triggers_email_on_completion_and_failure(db_session, test_print_server, monkeypatch):
    """Test job_service status transitions trigger notification email."""
    order = Order(
        id="ORD-LIFECYCLE-01",
        user_id=None,
        document_id="doc_any",
        print_server_id=test_print_server.id,
        print_settings={"notification_email": "lifecycle@example.com"},
        total_pages=1,
        copies=1,
        amount=2.00,
        currency="INR",
        status=OrderStatus.RELEASED
    )
    db_session.add(order)
    db_session.flush()

    job = PrintJob(
        id="job_lifecycle_01",
        order_id=order.id,
        server_id=test_print_server.id,
        status=PrintJobStatus.RELEASED,
        retry_count=0
    )
    db_session.add(job)
    db_session.commit()

    captured_events = []
    monkeypatch.setattr(
        email_service,
        "notify_order_status",
        lambda db, ord_obj, st, extra_info=None: captured_events.append((ord_obj.id, str(st), extra_info)) or True
    )

    # 1. Update status to PRINTING
    job_service.update_job_status(
        db=db_session,
        server_id=test_print_server.id,
        job_id=job.id,
        update=AgentJobStatusUpdate(status=PrintJobStatus.PRINTING, eventId="evt_01")
    )
    assert len(captured_events) == 1
    assert captured_events[-1][0] == "ORD-LIFECYCLE-01"
    assert "PRINTING" in captured_events[-1][1]

    # 2. Update status to COMPLETED
    job_service.update_job_status(
        db=db_session,
        server_id=test_print_server.id,
        job_id=job.id,
        update=AgentJobStatusUpdate(status=PrintJobStatus.COMPLETED, eventId="evt_02")
    )
    assert len(captured_events) == 2
    assert "COMPLETED" in captured_events[-1][1]

def test_resend_order_email_endpoint(client, test_user, test_print_server, db_session, monkeypatch):
    """Test the resend-email endpoint calls notify_order_status with authenticated user."""
    token = get_auth_token(client, test_user)
    order = Order(
        id="ORD-RESEND-01",
        user_id=test_user.id,
        document_id="doc_resend",
        print_server_id=test_print_server.id,
        print_settings={},
        total_pages=1,
        copies=1,
        amount=2.00,
        currency="INR",
        status=OrderStatus.WAITING_FOR_OTP
    )
    db_session.add(order)
    db_session.commit()

    called = []
    monkeypatch.setattr(
        email_service,
        "notify_order_status",
        lambda db, ord_obj, st, extra_info=None: called.append(ord_obj.id) or True
    )

    res = client.post(
        f"/api/orders/{order.id}/resend-email",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 200
    assert res.json()["status"] == "SUCCESS"
    assert res.json()["sent"] is True
    assert called == ["ORD-RESEND-01"]
    repeated = client.post(f"/api/orders/{order.id}/resend-email",
                           headers={"Authorization": f"Bearer {token}"})
    assert repeated.status_code == 429
    assert called == ["ORD-RESEND-01"]
