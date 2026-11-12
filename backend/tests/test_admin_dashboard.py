import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import get_db
from app.db.models.user import User, UserRole
from app.db.models.department import Department
from app.config.security import hash_password

def test_admin_dashboard_requires_auth(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        res = client.get('/api/admin/dashboard')
        assert res.status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()

def test_admin_dashboard_rejects_regular_user(db_session):
    student = User(
        email='student_dash@example.com',
        password_hash=hash_password('Pass123!'),
        role=UserRole.USER,
        is_active=True
    )
    db_session.add(student)
    db_session.commit()
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        login_res = client.post('/api/auth/login', json={'email': 'student_dash@example.com', 'password': 'Pass123!'})
        assert login_res.status_code == 200
        token = login_res.json()['access_token']
        res = client.get('/api/admin/dashboard', headers={'Authorization': f'Bearer {token}'})
        assert res.status_code == 403
    finally:
        app.dependency_overrides.clear()

def test_admin_dashboard_success(db_session):
    admin = User(
        email='admin@printplatform.local',
        password_hash=hash_password('AdminPass123!'),
        role=UserRole.ADMIN,
        is_active=True
    )
    dept = Department(code="IT_TEST", name="IT Test Dept", description="Test")
    db_session.add(admin)
    db_session.add(dept)
    db_session.commit()

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        login_res = client.post('/api/auth/admin/login', json={'email': 'admin@printplatform.local', 'password': 'AdminPass123!'})
        assert login_res.status_code == 200
        token = login_res.json()['access_token']
        res = client.get('/api/admin/dashboard', headers={'Authorization': f'Bearer {token}'})
        assert res.status_code == 200
        data = res.json()
        assert 'total_departments' in data
        assert 'total_users' in data
        assert 'total_printers' in data
        assert 'total_print_jobs' in data
        assert 'total_pages_printed' in data
        assert 'successful_print_jobs' in data
        assert 'failed_print_jobs' in data
        assert 'color_pages' in data
        assert 'bw_pages' in data
        assert 'recent_activity' in data
        assert 'department_summary' in data
        assert data['total_departments'] >= 1
    finally:
        app.dependency_overrides.clear()
