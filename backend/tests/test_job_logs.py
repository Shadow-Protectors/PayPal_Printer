import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import get_db
from app.db.models.user import User, UserRole
from app.db.models.department import Department
from app.db.models.print_job import PrintJob, PrintJobStatus
from app.db.models.order import Order, OrderStatus
from app.db.models.document import Document
from app.config.security import hash_password

def test_job_logs_requires_admin_auth(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        res = client.get('/api/reports/jobs')
        assert res.status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()

def test_job_logs_rejects_regular_user(db_session):
    student = User(
        email='student_jobs@example.com',
        password_hash=hash_password('Pass123!'),
        role=UserRole.USER,
        is_active=True
    )
    db_session.add(student)
    db_session.commit()

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        login_res = client.post('/api/auth/login', json={'email': 'student_jobs@example.com', 'password': 'Pass123!'})
        assert login_res.status_code == 200
        token = login_res.json()['access_token']
        res = client.get('/api/reports/jobs', headers={'Authorization': f'Bearer {token}'})
        assert res.status_code == 403
    finally:
        app.dependency_overrides.clear()

def test_get_detailed_print_jobs_pagination_and_search(db_session):
    admin = User(
        email='admin@printplatform.local',
        password_hash=hash_password('AdminPass123!'),
        role=UserRole.ADMIN,
        is_active=True
    )
    dept = Department(code="CSE_JOBS", name="Computer Science Jobs", description="CS Jobs")
    db_session.add(admin)
    db_session.add(dept)
    db_session.commit()

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        login_res = client.post('/api/auth/admin/login', json={'email': 'admin@printplatform.local', 'password': 'AdminPass123!'})
        assert login_res.status_code == 200
        token = login_res.json()['access_token']
        headers = {'Authorization': f'Bearer {token}'}

        # 1. Fetch paginated jobs
        res = client.get('/api/reports/jobs?page=1&page_size=10', headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert 'total' in data
        assert 'page' in data
        assert 'page_size' in data
        assert 'total_pages' in data
        assert 'jobs' in data
        assert data['page'] == 1
        assert data['page_size'] == 10

        # 2. Search filter
        search_res = client.get('/api/reports/jobs?search=nonexistent_xyz123', headers=headers)
        assert search_res.status_code == 200
        assert search_res.json()['total'] == 0

        # 3. Status filter
        status_res = client.get('/api/reports/jobs?status=COMPLETED', headers=headers)
        assert status_res.status_code == 200

        # 4. Color filter
        color_res = client.get('/api/reports/jobs?is_color=false', headers=headers)
        assert color_res.status_code == 200

        # 5. Non-existent job detail 404
        detail_res = client.get('/api/reports/jobs/invalid_job_99999', headers=headers)
        assert detail_res.status_code == 404
    finally:
        app.dependency_overrides.clear()
