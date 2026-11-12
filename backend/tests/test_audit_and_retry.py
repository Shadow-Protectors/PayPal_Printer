import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models.user import User, UserRole
from app.db.models.order import Order, OrderStatus
from app.db.models.payment import Payment, PaymentStatus
from app.db.models.print_job import PrintJob, PrintJobStatus
from app.db.models.document import Document, DocumentStatus
from app.db.models.printer import Printer
from app.db.models.department import Department
from app.db.models.audit_log import AuditLog
from app.config.security import create_access_token, hash_password


@pytest.fixture
def admin_user(db_session: Session) -> User:
    admin = User(
        email="superadmin@example.com",
        full_name="Super Administrator",
        password_hash=hash_password("adminsecret123"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin


@pytest.fixture
def admin_token(admin_user: User) -> str:
    return create_access_token({"sub": str(admin_user.id), "role": "ADMIN"})


def test_audit_logs_recorded_on_admin_actions(client: TestClient, admin_token: str, db_session: Session):
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. Create Department -> verifies audit log
    dept_res = client.post(
        "/api/departments",
        headers=headers,
        json={"name": "Aerospace Engineering", "code": "AERO", "description": "Aero dept"}
    )
    assert dept_res.status_code == 201
    dept_id = dept_res.json()["id"]

    # Verify audit log in DB
    log = db_session.query(AuditLog).filter(
        AuditLog.action == "DEPARTMENT_CREATED",
        AuditLog.entity_id == str(dept_id)
    ).first()
    assert log is not None
    assert log.actor_type == "ADMIN"
    assert log.meta_data.get("code") == "AERO"

    # 2. Update Department -> verifies audit log
    update_res = client.put(
        f"/api/departments/{dept_id}",
        headers=headers,
        json={"name": "Aerospace & Avionics", "description": "Updated"}
    )
    assert update_res.status_code == 200

    log_up = db_session.query(AuditLog).filter(
        AuditLog.action == "DEPARTMENT_UPDATED",
        AuditLog.entity_id == str(dept_id)
    ).first()
    assert log_up is not None

    # 3. Query audit logs API
    audit_api_res = client.get("/api/admin/audit-logs", headers=headers)
    assert audit_api_res.status_code == 200
    items = audit_api_res.json()
    assert len(items) >= 2
    actions = [i["action"] for i in items]
    assert "DEPARTMENT_CREATED" in actions
    assert "DEPARTMENT_UPDATED" in actions


def test_admin_manual_failed_job_retry(client: TestClient, admin_user: User, admin_token: str, test_agent_token: str, test_print_server, db_session: Session):
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    agent_headers = {"Authorization": f"Bearer {test_agent_token}"}

    # Setup Department & Printer
    dept = Department(name="Mechatronics", code="MTRX")
    db_session.add(dept)
    db_session.commit()
    db_session.refresh(dept)

    printer = Printer(
        id="MTRX-PRINTER-01",
        server_id=test_print_server.id,
        department_id=dept.id,
        cups_printer_name="MTRX_Laser",
        display_name="Mechatronics Laser",
        is_enabled=True,
        is_active=True,
    )
    db_session.add(printer)

    # Setup Document, Order, Job in FAILED state
    doc = Document(
        id="doc_retry_test_001",
        user_id=admin_user.id,
        original_filename="project.pdf",
        stored_filename="project_stored.pdf",
        storage_key="documents/project.pdf",
        mime_type="application/pdf",
        sha256="dummyhash",
        file_size=1024,
        page_count=2,
        status=DocumentStatus.ACTIVE,
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    order = Order(
        id="ORD-RETRY-TEST-001",
        user_id=admin_user.id,
        document_id=doc.id,
        print_server_id=test_print_server.id,
        total_pages=2,
        copies=1,
        amount=4.00,
        status=OrderStatus.FAILED,
        print_settings={"printer_name": "MTRX_Laser", "cups_printer_name": "MTRX_Laser"},
    )
    db_session.add(order)

    payment = Payment(
        id="PAY-RETRY-TEST-001",
        order_id=order.id,
        user_id=admin_user.id,
        razorpay_order_id="order_dummy_retry",
        razorpay_payment_id="pay_dummy_retry",
        amount=4.00,
        currency="INR",
        status=PaymentStatus.CAPTURED,
    )
    db_session.add(payment)
    db_session.commit()

    job = PrintJob(
        id="JOB-RETRY-TEST-001",
        order_id=order.id,
        server_id=test_print_server.id,
        printer_id=printer.id,
        status=PrintJobStatus.FINAL_FAILED,
        retry_count=3,
        error_code="PAPER_JAM",
        error_message="Paper feed tray jammed",
    )
    db_session.add(job)
    db_session.commit()

    # 1. Admin retries the failed job
    retry_res = client.post(f"/api/admin/jobs/{job.id}/retry", headers=admin_headers)
    assert retry_res.status_code == 200
    res_data = retry_res.json()
    assert res_data["success"] is True
    assert res_data["status"] == "QUEUED"
    assert res_data["order_status"] == "WAITING_FOR_OTP"
    new_release_code = res_data["release_code"]
    assert len(new_release_code) == 6

    # Verify state in DB
    db_session.refresh(job)
    db_session.refresh(order)
    assert job.status == PrintJobStatus.QUEUED
    assert job.retry_count == 0
    assert job.error_code is None
    assert order.status == OrderStatus.WAITING_FOR_OTP

    # Verify audit log
    audit_log = db_session.query(AuditLog).filter(
        AuditLog.action == "JOB_RETRIED",
        AuditLog.entity_id == job.id
    ).first()
    assert audit_log is not None
    assert "release_code" not in audit_log.meta_data
    assert audit_log.meta_data["release_code_rotated"] is True

    # 2. Agent claims the newly issued OTP release code at station
    release_res = client.post("/api/agent/release", headers=agent_headers, json={"otp": new_release_code})
    assert release_res.status_code == 200
    assert release_res.json()["status"] == "RELEASED"

    # 3. Retrying an already completed job should be rejected
    job.status = PrintJobStatus.COMPLETED
    db_session.commit()
    bad_retry = client.post(f"/api/admin/jobs/{job.id}/retry", headers=admin_headers)
    assert bad_retry.status_code == 400

    # 4. Retrying without captured payment should be rejected
    job.status = PrintJobStatus.FAILED
    payment.status = PaymentStatus.PENDING
    db_session.commit()
    unpaid_retry = client.post(f"/api/admin/jobs/{job.id}/retry", headers=admin_headers)
    assert unpaid_retry.status_code == 400
    assert "payment has not been captured" in unpaid_retry.json()["message"]

    # 5. Retrying with already completed refund should be rejected
    payment.status = PaymentStatus.CAPTURED
    from app.db.models.refund import Refund, RefundStatus
    refund = Refund(
        id="REF-TEST-001",
        order_id=order.id,
        payment_id=payment.id,
        amount=4.00,
        status=RefundStatus.COMPLETED,
    )
    db_session.add(refund)
    db_session.commit()
    refunded_retry = client.post(f"/api/admin/jobs/{job.id}/retry", headers=admin_headers)
    assert refunded_retry.status_code == 400
    assert "already been refunded" in refunded_retry.json()["message"]

    for uncertain_status in (RefundStatus.PROCESSING, RefundStatus.FAILED):
        refund.status = uncertain_status
        db_session.commit()
        uncertain_retry = client.post(f"/api/admin/jobs/{job.id}/retry", headers=admin_headers)
        assert uncertain_retry.status_code == 409
        assert uncertain_retry.json()["error"] == "REFUND_REVIEW_REQUIRED"
