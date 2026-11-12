import pytest
import jwt
from app.config.settings import settings, Settings
from app.services.auth_service import auth_service
from app.services.email_service import email_service


def test_password_login_is_throttled(client):
    for _ in range(10):
        assert client.post('/api/auth/admin/login', json={'email': 'guess@example.com', 'password': 'wrong'}).status_code == 401
    assert client.post('/api/auth/admin/login', json={'email': 'guess@example.com', 'password': 'wrong'}).status_code == 429


def test_no_fixed_email_code_bypass(monkeypatch):
    monkeypatch.setattr(settings, 'ENVIRONMENT', 'test')
    auth_service._email_otps.clear()
    with pytest.raises(Exception) as error:
        auth_service.verify_email_otp('unrequested@example.com', '123456')
    assert error.value.error_code == 'OTP_NOT_FOUND'


def test_administrator_cannot_use_student_email_login(client, test_user, db_session, monkeypatch):
    from app.db.models.user import UserRole
    test_user.role = UserRole.ADMIN
    db_session.commit()
    monkeypatch.setattr(email_service, 'send_otp', lambda *a: True)
    response = client.post('/api/auth/send-otp', json={'email': test_user.email, 'purpose': 'login'})
    assert response.status_code == 403
    assert response.json()['error'] == 'ADMIN_PASSWORD_REQUIRED'


def test_invalid_purpose_and_unverified_password_signup(client):
    assert client.post('/api/auth/send-otp', json={'email': 'new@example.com', 'purpose': 'anything'}).status_code == 422
    assert client.post('/api/auth/register', json={'email': 'new@example.com', 'password': 'secure-password'}).status_code == 422


def test_validation_does_not_echo_secrets(client):
    secret = 'private-password-do-not-echo'
    response = client.post('/api/auth/admin/login', json={'email': 'invalid', 'password': secret})
    assert response.status_code == 422 and secret not in response.text
    assert '"input"' not in response.text


def test_jwt_requires_expiry_and_handles_invalid_subject(client, test_user):
    missing_exp = jwt.encode({'sub': str(test_user.id), 'type': 'access'}, settings.JWT_SECRET_KEY, algorithm='HS256')
    assert client.get('/api/auth/me', headers={'Authorization': f'Bearer {missing_exp}'}).status_code == 401
    from app.config.security import create_access_token
    malformed = create_access_token({'sub': 'invalid-number'})
    assert client.get('/api/auth/me', headers={'Authorization': f'Bearer {malformed}'}).status_code == 401


def test_profile_email_requires_verification(client, test_user):
    from app.config.security import create_access_token
    token = create_access_token({'sub': str(test_user.id)})
    response = client.put('/api/auth/me', headers={'Authorization': f'Bearer {token}'}, json={'email': 'unverified@example.com'})
    assert response.status_code == 400
    assert test_user.email != 'unverified@example.com'


def test_weak_guest_capability_is_rejected(client):
    assert client.get('/api/orders', headers={'X-Customer-Session': 'x'}).status_code == 422


def test_production_rejects_mock_email():
    with pytest.raises(RuntimeError):
        Settings(ENVIRONMENT='production', EMAIL_PROVIDER='mock')


def test_signup_code_cannot_authenticate_existing_user(client, test_user):
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    auth_service._email_otps[test_user.email] = {'otp': '654321', 'purpose': 'signup', 'attempts': 0,
        'window_start': now, 'expires_at': now + timedelta(minutes=5)}
    response = client.post('/api/auth/student/login', json={'email': test_user.email, 'otp': '654321'})
    assert response.status_code == 400


def test_mock_agent_is_rejected_in_production(client, test_print_server, test_agent_token, monkeypatch):
    monkeypatch.setattr(settings, 'ENVIRONMENT', 'production')
    response = client.get('/api/agent/jobs', headers={'Authorization': f'Bearer {test_agent_token}', 'X-Print-Simulation': 'true'})
    assert response.status_code == 403 and response.json()['error'] == 'SIMULATION_FORBIDDEN'


def test_station_id_must_match_device_token(client, test_print_server, test_agent_token):
    response = client.get('/api/agent/jobs', headers={'Authorization': f'Bearer {test_agent_token}', 'X-Station-ID': 'wrong-station'})
    assert response.status_code == 403


def test_ended_guest_capability_cannot_be_reused(client):
    session = client.post('/api/sessions').json()['token']
    headers = {'X-Customer-Session': session}
    assert client.delete('/api/sessions/current', headers=headers).status_code == 200
    response = client.get('/api/orders', headers=headers)
    assert response.status_code == 401 and response.json()['error'] == 'SESSION_REVOKED'


def test_orders_cannot_expand_to_unbounded_copies(client, test_print_server):
    from tests.conftest import create_sample_pdf
    uploaded = client.post('/api/documents/upload', files={'file': ('pages.pdf', create_sample_pdf(11), 'application/pdf')})
    assert uploaded.status_code == 201
    response = client.post('/api/orders', json={'document_id': uploaded.json()['documentId'],
        'print_server_id': test_print_server.id, 'settings': {'copies': 100}})
    assert response.status_code == 413


def test_oversized_pdf_preview_does_not_allocate_bitmap(client):
    from pypdf import PdfWriter
    import io
    writer = PdfWriter()
    writer.add_blank_page(width=100000, height=100000)
    data = io.BytesIO()
    writer.write(data)
    uploaded = client.post('/api/documents/upload', files={'file': ('large-page.pdf', data.getvalue(), 'application/pdf')})
    assert uploaded.status_code == 201
    response = client.get('/api/documents/' + uploaded.json()['documentId'] + '/preview')
    assert response.status_code == 413


def test_old_customer_token_does_not_gain_admin_after_promotion(client, test_user, db_session):
    from app.config.security import create_access_token
    from app.db.models.user import UserRole
    old_token = create_access_token({'sub': str(test_user.id), 'role': 'USER'})
    test_user.role = UserRole.ADMIN
    db_session.commit()
    response = client.get('/api/admin/dashboard', headers={'Authorization': f'Bearer {old_token}'})
    assert response.status_code == 403
