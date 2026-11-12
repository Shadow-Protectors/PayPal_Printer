import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import get_db
from app.db.models.user import User, UserRole
from app.config.security import hash_password
from app.db.models.refresh_token import RefreshToken

@pytest.mark.parametrize('role', [UserRole.ADMIN, UserRole.SUPER_ADMIN])
def test_admin_login_and_logout(db_session, role):
    user = User(email='admin@printplatform.local', password_hash=hash_password('AdminPass123!'), role=role, is_active=True)
    db_session.add(user)
    db_session.commit()
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        response = client.post('/api/auth/admin/login', json={'email': user.email, 'password': 'AdminPass123!'})
        assert response.status_code == 200, response.text
        tokens = response.json()
        headers = {'Authorization': 'Bearer ' + tokens['access_token']}
        assert client.get('/api/auth/admin/me', headers=headers).json()['role'] == role.value
        assert client.post('/api/auth/logout', json={'refresh_token': tokens['refresh_token']}).status_code == 200
        assert client.post('/api/auth/refresh', json={'refresh_token': tokens['refresh_token']}).status_code == 401
    finally:
        app.dependency_overrides.clear()

@pytest.mark.parametrize('role,active,password,expected', [
    (UserRole.USER, True, 'correct', 403),
    (UserRole.ADMIN, False, 'correct', 403),
    (UserRole.ADMIN, True, 'wrong', 401),
])
def test_admin_login_rejects_without_issuing_tokens(db_session, role, active, password, expected):
    user = User(email='login@example.com', password_hash=hash_password('correct'), role=role, is_active=active)
    db_session.add(user)
    db_session.commit()
    before = db_session.query(RefreshToken).count()
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        assert client.post('/api/auth/admin/login', json={'email': user.email, 'password': password}).status_code == expected
        assert db_session.query(RefreshToken).count() == before
        assert client.get('/api/auth/admin/me').status_code == 401
    finally:
        app.dependency_overrides.clear()
