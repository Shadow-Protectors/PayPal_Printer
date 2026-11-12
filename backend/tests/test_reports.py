import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import get_db
from app.db.models.user import User, UserRole
from app.db.models.department import Department
from app.config.security import hash_password

def test_reports_requires_admin_auth(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        res = client.get('/api/reports/department')
        assert res.status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()

def test_reports_rejects_regular_user(db_session):
    student = User(
        email='student_rep@example.com',
        password_hash=hash_password('Pass123!'),
        role=UserRole.USER,
        is_active=True
    )
    db_session.add(student)
    db_session.commit()

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        login_res = client.post('/api/auth/login', json={'email': 'student_rep@example.com', 'password': 'Pass123!'})
        assert login_res.status_code == 200
        token = login_res.json()['access_token']
        res = client.get('/api/reports/department', headers={'Authorization': f'Bearer {token}'})
        assert res.status_code == 403
    finally:
        app.dependency_overrides.clear()

def test_generate_department_report_success(db_session):
    admin = User(
        email='admin@printplatform.local',
        password_hash=hash_password('AdminPass123!'),
        role=UserRole.ADMIN,
        is_active=True
    )
    dept = Department(code="HR_REP", name="Human Resources Rep", description="HR Rep Desc")
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

        # 1. Global report across all departments
        res = client.get('/api/reports/department', headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert 'summary' in data
        assert 'user_stats' in data
        assert 'printer_stats' in data
        summary = data['summary']
        assert 'total_jobs' in summary
        assert 'total_pages' in summary
        assert 'successful_jobs' in summary
        assert 'failed_jobs' in summary
        assert 'color_pages' in summary
        assert 'bw_pages' in summary
        assert 'avg_pages_per_job' in summary

        # 2. Specific department report query
        dept_res = client.get(f'/api/reports/department?department_id={dept.id}', headers=headers)
        assert dept_res.status_code == 200
        dept_data = dept_res.json()
        assert dept_data['summary']['department_id'] == dept.id
        assert dept_data['summary']['department_code'] == 'HR_REP'

        # 3. Specific department report via nested endpoint
        nested_res = client.get(f'/api/departments/{dept.id}/report', headers=headers)
        assert nested_res.status_code == 200
        assert nested_res.json()['summary']['department_id'] == dept.id

        # 4. Filter by color
        color_res = client.get('/api/reports/department?is_color=true', headers=headers)
        assert color_res.status_code == 200
    finally:
        app.dependency_overrides.clear()

def test_generate_printer_level_and_specific_reports(db_session):
    from app.db.models.print_server import PrintServer, PrintServerStatus
    from app.db.models.printer import Printer
    from app.db.models.order import Order, OrderStatus
    from app.db.models.print_job import PrintJob, PrintJobStatus
    from app.db.models.document import Document

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        admin = User(
            email='admin_printer_rep@printplatform.local',
            password_hash=hash_password('AdminPass123!'),
            role=UserRole.ADMIN,
            is_active=True
        )
        dept = Department(code="CSE_REP", name="Computer Science Rep", description="CSE Desc")
        db_session.add(admin)
        db_session.add(dept)
        db_session.commit()

        server = PrintServer(
            id="AGENT_REP_001",
            name="CSE Lab Agent",
            device_token_hash="hash_rep_123",
            department_id=dept.id,
            status=PrintServerStatus.ONLINE,
        )
        db_session.add(server)
        db_session.commit()

        printer = Printer(
            id="printer_rep_test_1",
            server_id=server.id,
            department_id=dept.id,
            cups_printer_name="HP_LaserJet_Pro_M404",
            display_name="HP LaserJet Pro M404 - Lab 1",
            printer_status="READY",
            is_active=True,
            is_enabled=True,
            location="Room 101",
        )
        db_session.add(printer)
        db_session.commit()

        # Add a test completed job
        doc = Document(
            id="doc_rep_1",
            original_filename="sample.pdf",
            stored_filename="stored_sample.pdf",
            storage_key="docs/sample.pdf",
            file_size=1024,
            sha256="dummy_sha256_hash",
            page_count=5,
            mime_type="application/pdf",
        )
        db_session.add(doc)
        db_session.commit()

        order = Order(
            id="order_rep_1",
            user_id=admin.id,
            document_id=doc.id,
            print_server_id=server.id,
            department=dept.name,
            total_pages=5,
            copies=2,
            amount=20.0,
            status=OrderStatus.COMPLETED,
            print_settings={"color": False, "sides": "two-sided"},
        )
        db_session.add(order)
        db_session.commit()

        job = PrintJob(
            id="job_rep_1",
            order_id=order.id,
            server_id=server.id,
            printer_id=printer.id,
            status=PrintJobStatus.COMPLETED,
        )
        db_session.add(job)
        db_session.commit()

        login_res = client.post('/api/auth/admin/login', json={'email': 'admin_printer_rep@printplatform.local', 'password': 'AdminPass123!'})
        assert login_res.status_code == 200
        headers = {'Authorization': f"Bearer {login_res.json()['access_token']}"}

        # 1. Printer-level reports listing
        printers_res = client.get('/api/reports/printers', headers=headers)
        assert printers_res.status_code == 200
        printers_data = printers_res.json()
        assert isinstance(printers_data, list)
        found = [p for p in printers_data if p['printer_id'] == printer.id]
        assert len(found) == 1
        p_stat = found[0]
        assert p_stat['printer_name'] == "HP LaserJet Pro M404 - Lab 1"
        assert p_stat['total_jobs'] == 1
        assert p_stat['successful_jobs'] == 1
        assert p_stat['total_pages'] == 10  # 5 pages * 2 copies
        assert p_stat['bw_pages'] == 10
        assert p_stat['success_rate'] == 100.0

        # 2. Printer-specific report endpoint
        spec_res = client.get(f'/api/reports/printers/{printer.id}', headers=headers)
        assert spec_res.status_code == 200
        spec_data = spec_res.json()
        assert 'printer' in spec_data
        assert 'summary' in spec_data
        assert 'user_stats' in spec_data
        assert 'recent_jobs' in spec_data
        assert spec_data['summary']['printer_id'] == printer.id
        assert spec_data['summary']['total_jobs'] == 1
        assert len(spec_data['user_stats']) == 1
        assert len(spec_data['recent_jobs']) == 1

        # 3. Printer-specific report via query parameter
        query_res = client.get(f'/api/reports/printer?printer_id={printer.id}', headers=headers)
        assert query_res.status_code == 200
        assert query_res.json()['summary']['printer_id'] == printer.id

        # 4. Admin printer report route
        admin_p_res = client.get(f'/api/admin/printers/{printer.id}/report', headers=headers)
        assert admin_p_res.status_code == 200
        assert admin_p_res.json()['summary']['printer_id'] == printer.id

        # 5. Non-existent printer returns 404
        not_found_res = client.get('/api/reports/printers/non_existent_9999', headers=headers)
        assert not_found_res.status_code == 404
    finally:
        app.dependency_overrides.clear()

