import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import get_db
from app.db.models.user import User, UserRole
from app.db.models.department import Department
from app.db.models.document import Document
from app.db.models.print_server import PrintServer, PrintServerStatus
from app.db.models.printer import Printer
from app.db.models.order import Order, OrderStatus
from app.db.models.print_job import PrintJob, PrintJobStatus
from app.config.settings import Settings
from app.config.security import hash_password

def test_analytics_and_scheduled_reports_flow(db_session, monkeypatch):
    from app.services.schedule_service import schedule_service
    monkeypatch.setattr(schedule_service, "_send_email_with_attachment", lambda *args, **kwargs: True)

    admin = User(
        email='admin_analytics@nec.edu.in',
        password_hash=hash_password('AdminPass123!'),
        role=UserRole.ADMIN,
        is_active=True,
    )
    dept_cse = Department(code='CSE', name='Computer Science and Engineering', description='CSE Dept')
    dept_ece = Department(code='ECE', name='Electronics and Communication Engineering', description='ECE Dept')
    db_session.add(admin)
    db_session.add(dept_cse)
    db_session.add(dept_ece)
    db_session.flush()

    student = User(
        email='student_cse@nec.edu.in',
        full_name='CSE Student',
        roll_number='2012001',
        role=UserRole.USER,
        department_id=dept_cse.id,
        department=dept_cse.name,
        is_active=True,
    )
    faculty = User(
        email='prof_ece@nec.edu.in',
        full_name='ECE Professor',
        roll_number=None,
        role=UserRole.USER,
        department_id=dept_ece.id,
        department=dept_ece.name,
        is_active=True,
    )
    server = PrintServer(
        id='srv_test_01',
        name='Main Server',
        device_token_hash='token_hash',
        status=PrintServerStatus.ONLINE,
    )
    db_session.add(student)
    db_session.add(faculty)
    db_session.add(server)
    db_session.flush()

    printer = Printer(
        id='prt_cse_kiosk',
        server_id=server.id,
        department_id=dept_cse.id,
        cups_printer_name='CSE_LaserJet_01',
        display_name='CSE Department Kiosk',
        supports_color=True,
        supports_duplex=True,
        is_active=True,
        printer_status='ONLINE',
    )
    doc = Document(
        id='doc_analytics_01',
        user_id=student.id,
        original_filename='Project_Report_CSE.pdf',
        stored_filename='doc_analytics_01.pdf',
        storage_key='docs/doc_analytics_01.pdf',
        sha256='e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
        file_size=20480,
        page_count=10,
        mime_type='application/pdf',
    )
    db_session.add(printer)
    db_session.add(doc)
    db_session.flush()

    order = Order(
        id='ord_analytics_01',
        user_id=student.id,
        roll_number=student.roll_number,
        department=dept_cse.name,
        document_id=doc.id,
        print_server_id=server.id,
        print_settings={'colour': False, 'sides': 'two-sided', 'copies': 1},
        total_pages=10,
        copies=1,
        amount=20.00,
        status=OrderStatus.COMPLETED,
    )
    db_session.add(order)
    db_session.flush()

    job = PrintJob(
        id='job_analytics_01',
        order_id=order.id,
        server_id=server.id,
        printer_id=printer.id,
        status=PrintJobStatus.COMPLETED,
    )
    db_session.add(job)
    db_session.commit()

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        login_res = client.post('/api/auth/admin/login', json={
            'email': 'admin_analytics@nec.edu.in',
            'password': 'AdminPass123!'
        })
        assert login_res.status_code == 200
        token = login_res.json()['access_token']
        headers = {'Authorization': f'Bearer {token}'}

        # 1. Test Analytics API
        analytics_res = client.get('/api/reports/analytics?period=this_month', headers=headers)
        assert analytics_res.status_code == 200
        data = analytics_res.json()

        assert 'summary' in data
        assert data['summary']['total_jobs'] >= 1
        assert data['summary']['total_pages'] >= 10
        assert data['summary']['total_amount'] >= 20.0

        assert 'monthly_trends' in data
        assert 'daily_trends' in data
        assert 'department_performance' in data
        assert len(data['department_performance']) >= 2

        assert 'printer_stats' in data
        assert 'user_demographics' in data
        assert data['user_demographics']['student_count'] >= 1

        assert 'remarks' in data
        assert len(data['remarks']['key_recommendations']) >= 1

        # 2. Test CSV Export (Department)
        csv_res = client.get('/api/reports/export/csv?report_type=department', headers=headers)
        assert csv_res.status_code == 200
        assert 'text/csv' in csv_res.headers['content-type']
        assert b'Department Code' in csv_res.content

        # 3. Test Scheduled Reports Manual Trigger
        trigger_res = client.post('/api/reports/scheduled/trigger?period=last_month', headers=headers)
        assert trigger_res.status_code == 200
        trigger_data = trigger_res.json()
        assert trigger_data['success'] is True
        assert trigger_data['dispatched_count'] >= 4  # Principal, HODs, Accounts, SysAdmin
    finally:
        app.dependency_overrides.clear()
