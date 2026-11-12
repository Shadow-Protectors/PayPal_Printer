import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import get_db
from app.db.models.user import User, UserRole
from app.db.models.department import Department
from app.db.models.printer import Printer
from app.db.models.print_server import PrintServer, PrintServerStatus
from app.config.security import hash_password

def test_printers_users_settings_requires_admin(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        assert client.get('/api/admin/printers').status_code in (401, 403)
        assert client.get('/api/admin/users').status_code in (401, 403)
        assert client.get('/api/admin/settings').status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()

def test_printers_users_settings_endpoints(db_session):
    admin = User(
        email='admin@printplatform.local',
        password_hash=hash_password('AdminPass123!'),
        role=UserRole.ADMIN,
        is_active=True
    )
    dept = Department(code='CSE_SYS', name='Computer Science', description='CSE Dept')
    student = User(
        email='student_sys@example.com',
        roll_number='2026CSE099',
        full_name='Test Student Sys',
        password_hash=hash_password('Pass123!'),
        role=UserRole.USER,
        is_active=True
    )
    server = PrintServer(
        id='SERVER-TEST-01',
        name='Main Library Station',
        location='Library Ground Floor',
        device_token_hash=hash_password('secret_token'),
        status=PrintServerStatus.ONLINE,
        printer_state='IDLE',
        paper_state='AVAILABLE'
    )
    printer = Printer(
        id='PRINTER-TEST-01',
        server_id='SERVER-TEST-01',
        cups_printer_name='HP_LaserJet_Test',
        display_name='HP LaserJet Pro 400',
        supports_color=True,
        supports_duplex=True,
        is_active=True
    )
    db_session.add_all([admin, dept, student, server, printer])
    db_session.commit()

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        login_res = client.post('/api/auth/admin/login', json={'email': 'admin@printplatform.local', 'password': 'AdminPass123!'})
        assert login_res.status_code == 200
        token = login_res.json()['access_token']
        headers = {'Authorization': f'Bearer {token}'}

        # 1. Test Printers API
        res_printers = client.get('/api/admin/printers', headers=headers)
        assert res_printers.status_code == 200
        printers_data = res_printers.json()
        assert len(printers_data) >= 1
        found_p = next(p for p in printers_data if p['id'] == 'PRINTER-TEST-01')
        assert found_p['display_name'] == 'HP LaserJet Pro 400'
        assert found_p['server_id'] == 'SERVER-TEST-01'

        # Test Update Printer
        patch_p = client.patch(
            '/api/admin/printers/PRINTER-TEST-01',
            json={'display_name': 'Renamed HP Printer', 'department_id': dept.id},
            headers=headers
        )
        assert patch_p.status_code == 200
        assert patch_p.json()['display_name'] == 'Renamed HP Printer'
        assert patch_p.json()['department_id'] == dept.id

        # 2. Test Users API
        res_users = client.get('/api/admin/users?search=student_sys', headers=headers)
        assert res_users.status_code == 200
        users_data = res_users.json()
        assert users_data['total'] >= 1
        found_u = next(u for u in users_data['users'] if u['email'] == 'student_sys@example.com')
        assert found_u['roll_number'] == '2026CSE099'
        assert found_u['role'] == 'USER'

        # Test Update User
        patch_u = client.patch(
            f'/api/admin/users/{student.id}',
            json={'department_id': dept.id, 'is_active': False},
            headers=headers
        )
        assert patch_u.status_code == 200
        assert patch_u.json()['department_id'] == dept.id
        assert patch_u.json()['is_active'] is False

        # Test Create User (CRUD - Create)
        create_u = client.post(
            '/api/admin/users',
            json={
                'email': 'new_student@example.com',
                'full_name': 'New Student',
                'roll_number': '2026CSE100',
                'department_id': dept.id,
                'role': 'USER',
                'is_active': True
            },
            headers=headers
        )
        assert create_u.status_code == 201
        created_user_id = create_u.json()['id']
        assert create_u.json()['email'] == 'new_student@example.com'
        assert create_u.json()['department_id'] == dept.id

        # Test Delete User (CRUD - Delete)
        del_u = client.delete(
            f'/api/admin/users/{created_user_id}',
            headers=headers
        )
        assert del_u.status_code == 200

        # Verify User is deleted
        res_after_del = client.get(f'/api/admin/users?search=new_student@example.com', headers=headers)
        assert res_after_del.status_code == 200
        assert res_after_del.json()['total'] == 0


        # 3. Test Settings API
        res_settings = client.get('/api/admin/settings', headers=headers)
        assert res_settings.status_code == 200
        cfg = res_settings.json()
        assert 'per_page_rate' in cfg
        assert 'heartbeat_timeout_seconds' in cfg

        # Test Update Settings
        patch_s = client.patch(
            '/api/admin/settings',
            json={'per_page_rate': 2.50, 'max_upload_mb': 100},
            headers=headers
        )
        assert patch_s.status_code == 200
        updated_cfg = patch_s.json()
        assert updated_cfg['per_page_rate'] == 2.50
        assert updated_cfg['max_upload_mb'] == 100

    finally:
        app.dependency_overrides.clear()
