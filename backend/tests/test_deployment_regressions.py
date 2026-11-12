import pytest
from app.config.settings import settings
from app.schemas.auth import validate_email_address


def test_production_rejects_fixture_email_domains(monkeypatch):
    monkeypatch.setattr(settings, 'ENVIRONMENT', 'production')
    monkeypatch.setattr(settings, 'ADMIN_EMAIL', 'admin@nec.edu.in')
    monkeypatch.setattr(settings, 'ALLOWED_STUDENT_EMAIL_DOMAINS', ['nec.edu.in'])
    with pytest.raises(ValueError):
        validate_email_address('someone@university.edu')
    assert validate_email_address('student@nec.edu.in') == 'student@nec.edu.in'


def test_station_bootstrap_preserves_disable_and_token(db_session, test_print_server, monkeypatch):
    from app.main import _ensure_default_station
    from app.config import database
    test_print_server.is_enabled = False
    original_token = test_print_server.device_token_hash
    db_session.commit()
    monkeypatch.setattr(settings, 'DEFAULT_PRINT_SERVER_ID', test_print_server.id)
    monkeypatch.setattr(settings, 'INTERNAL_AGENT_TOKEN', 'replacement-token-must-not-be-installed')
    monkeypatch.setattr(database, 'SessionLocal', lambda: db_session)
    monkeypatch.setattr(db_session, 'close', lambda: None)
    _ensure_default_station()
    db_session.refresh(test_print_server)
    assert not test_print_server.is_enabled
    assert test_print_server.device_token_hash == original_token


def test_report_delivery_failure_is_not_success(db_session, monkeypatch):
    from app.services.schedule_service import schedule_service
    from app.services.export_service import export_service
    monkeypatch.setattr(export_service, 'generate_pdf_report', lambda **kw: b'pdf')
    monkeypatch.setattr(export_service, 'generate_excel_report', lambda **kw: b'xlsx')
    monkeypatch.setattr(schedule_service, '_send_email_with_attachment', lambda **kw: False)
    result = schedule_service.trigger_scheduled_reports(db_session)
    assert not result.success
    assert result.dispatched_count == 0
    assert all(r['status'] == 'FAILED' for r in result.recipients)


def test_missing_report_smtp_is_not_simulated_success(monkeypatch):
    from app.services.schedule_service import ScheduleService, settings as report_settings
    monkeypatch.setattr(report_settings, 'EMAIL_PROVIDER', 'smtp')
    monkeypatch.setattr(report_settings, 'SMTP_PASSWORD', '')
    assert not ScheduleService._send_email_with_attachment(
        'configured@nec.edu.in', 'report', 'body', b'pdf', 'report.pdf')


def test_csv_formula_injection_is_escaped():
    import io
    from app.services.export_service import SafeCsvWriter
    output = io.StringIO()
    SafeCsvWriter(output).writerow(['=HYPERLINK("bad")', ' @SUM(1)', 12, 'normal'])
    assert "'=HYPERLINK" in output.getvalue()
    assert "' @SUM" in output.getvalue()
    assert ',12,normal' in output.getvalue()


def test_bad_report_date_is_rejected():
    from app.services.report_service import report_service
    from app.utils.errors import AppException
    with pytest.raises(AppException):
        report_service.resolve_period_dates(start_date='not-a-date')


def test_upload_works_with_proxy_root_path(client):
    from fastapi.testclient import TestClient
    from app.main import app
    from tests.conftest import create_sample_pdf
    with TestClient(app, root_path='/achuppori') as mounted:
        response = mounted.post('/api/documents/upload',
            headers={'X-Customer-Session': 'sess_subpath_upload_regression_123456'},
            files={'file': ('test.pdf', create_sample_pdf(1), 'application/pdf')})
    assert response.status_code == 201, response.text


@pytest.mark.parametrize('role', ['USER', 'ADMIN', 'SUPER_ADMIN'])
def test_role_specific_token_lifetimes(db_session, monkeypatch, role):
    from app.db.models.user import User, UserRole
    from app.services.auth_service import auth_service
    from app.config.security import decode_token
    monkeypatch.setattr(settings, 'JWT_ACCESS_TOKEN_EXPIRE_MINUTES', 3)
    monkeypatch.setattr(settings, 'JWT_ADMIN_ACCESS_TOKEN_EXPIRE_MINUTES', 7)
    monkeypatch.setattr(settings, 'JWT_ADMIN_REFRESH_TOKEN_EXPIRE_DAYS', 1)
    monkeypatch.setattr(settings, 'JWT_REFRESH_TOKEN_EXPIRE_DAYS', 30)
    user = User(email=f'{role.lower()}@nec.edu.in', role=UserRole(role), is_active=True)
    db_session.add(user)
    db_session.commit()
    _, access, refresh, expires = auth_service._issue_tokens(db_session, user)
    assert expires == (180 if role == 'USER' else 420)
    refreshed, refreshed_expires = auth_service.refresh_access_token(db_session, refresh)
    assert refreshed_expires == expires
    assert decode_token(refreshed)['role'] == role
    from datetime import datetime, timezone
    seconds = decode_token(refresh)['exp'] - datetime.now(timezone.utc).timestamp()
    expected = (30 if role == 'USER' else 1) * 86400
    assert expected - 10 < seconds <= expected


def test_cancelled_unsubmitted_refund_can_be_retried_after_new_failure(db_session, test_print_server):
    from app.db.models.order import Order, OrderStatus
    from app.db.models.payment import Payment, PaymentStatus
    from app.db.models.refund import Refund, RefundStatus
    from app.services.refund_service import refund_service
    order = Order(id='retry-refund-order', document_id='doc', print_server_id=test_print_server.id,
                  print_settings={}, total_pages=1, copies=1, amount=2, status=OrderStatus.FAILED)
    db_session.add(order)
    db_session.flush()
    payment = Payment(id='retry-refund-payment', order_id=order.id, razorpay_order_id='order_retry_refund',
                      razorpay_payment_id='pay_retry_refund', amount=2, status=PaymentStatus.CAPTURED)
    db_session.add(payment)
    db_session.flush()
    db_session.add(Refund(id='retry-refund', order_id=order.id, payment_id=payment.id,
                         amount=2, status=RefundStatus.NOT_REQUIRED))
    db_session.commit()
    result = refund_service.process_refund(db_session, order.id)
    assert result.status == RefundStatus.COMPLETED
    assert order.status == OrderStatus.REFUNDED
