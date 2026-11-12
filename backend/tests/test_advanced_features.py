from datetime import datetime, timezone, timedelta
from app.db.models.order import Order, OrderStatus
from app.db.models.print_job import PrintJob, PrintJobStatus
from app.db.models.otp import OTP
from app.db.models.document import Document, DocumentStatus
from app.db.models.user import UserRole
from tests.conftest import create_sample_pdf, get_auth_token

def test_otp_attempt_lockout(client, test_print_server, test_agent_token, db_session):
    # Upload & Order & Payment without login
    pdf_bytes = create_sample_pdf(1)
    up = client.post("/api/documents/upload", files={"file": ("doc.pdf", pdf_bytes, "application/pdf")}).json()
    order = client.post("/api/orders", json={"document_id": up["documentId"], "print_server_id": test_print_server.id, "settings": {"copies": 1}}).json()
    client.post("/api/payments/create", json={"order_id": order["id"]})

    # Webhook triggers OTP
    import json
    wh_payload = {"event": "payment.captured", "payload": {"payment": {"entity": {"order_id": f"dummy", "id": "pay_1", "amount": int(order["amount"]*100)}}}}
    # Trigger directly in DB or via mock
    from app.services.otp_service import otp_service
    otp_code = otp_service.generate_and_store_otp(db_session, order["id"])
    ord_rec = db_session.query(Order).filter(Order.id == order["id"]).first()
    ord_rec.status = OrderStatus.WAITING_FOR_OTP
    pj = PrintJob(id="job_lockout_test", order_id=order["id"], server_id=test_print_server.id, status=PrintJobStatus.QUEUED)
    db_session.add(pj)
    db_session.commit()

    # Submit 5 wrong OTPs
    for i in range(5):
        res = client.post("/api/agent/release", headers={"Authorization": f"Bearer {test_agent_token}"}, json={"otp": f"99999{i}"})
        if i < 4:
            assert res.status_code == 400
        else:
            assert res.status_code == 429
            assert res.json()["error"] == "TOO_MANY_ATTEMPTS"

def test_print_failure_retry_and_auto_refund(client, test_user, test_print_server, test_agent_token, db_session):
    from app.services.job_service import job_service
    from app.schemas.agent import AgentJobStatusUpdate
    from app.db.models.payment import Payment, PaymentStatus

    # Create dummy order in PRINTING status
    order = Order(
        id="ORD-TEST-FAIL-RETRY",
        user_id=test_user.id,
        document_id="doc_dummy",
        print_server_id=test_print_server.id,
        print_settings={"copies": 1},
        total_pages=1,
        copies=1,
        amount=10.0,
        currency="INR",
        status=OrderStatus.PRINTING
    )
    payment = Payment(
        id="pay_fail_test",
        order_id=order.id,
        user_id=test_user.id,
        razorpay_order_id="rzp_fail_test",
        razorpay_payment_id="pay_rzp_mock",
        amount=10.0,
        status=PaymentStatus.CAPTURED
    )
    job = PrintJob(
        id="job_fail_test",
        order_id=order.id,
        server_id=test_print_server.id,
        status=PrintJobStatus.PRINTING,
        retry_count=0
    )
    db_session.add_all([order, payment, job])
    db_session.commit()

    # Failure 1 -> retry count = 1, status = QUEUED
    res1 = client.post(
        f"/api/agent/jobs/{job.id}/status",
        headers={"Authorization": f"Bearer {test_agent_token}"},
        json={"status": "FAILED", "errorCode": "FILE_NOT_FOUND", "message": "Paper jammed"}
    )
    assert res1.status_code == 200
    db_session.refresh(job)
    assert job.status == PrintJobStatus.RELEASED
    assert job.retry_count == 1

    # Transition back to PRINTING for retry run
    job.status = PrintJobStatus.PRINTING
    db_session.commit()

    # Failure 2 -> retry count = 2, status = QUEUED
    client.post(
        f"/api/agent/jobs/{job.id}/status",
        headers={"Authorization": f"Bearer {test_agent_token}"},
        json={"status": "FAILED", "errorCode": "FILE_NOT_FOUND", "message": "Paper jammed again"}
    )
    db_session.refresh(job)
    assert job.retry_count == 2
    assert job.status == PrintJobStatus.RELEASED

    # Transition back to PRINTING
    job.status = PrintJobStatus.PRINTING
    db_session.commit()

    # Failure 3 -> exceeds MAX_PRINT_RETRIES (2) -> FINAL_FAILED & auto-refund!
    client.post(
        f"/api/agent/jobs/{job.id}/status",
        headers={"Authorization": f"Bearer {test_agent_token}"},
        json={"status": "FAILED", "errorCode": "FILE_NOT_FOUND", "message": "Hardware error"}
    )
    db_session.refresh(job)
    db_session.refresh(order)
    assert job.status == PrintJobStatus.FINAL_FAILED
    assert order.status in [OrderStatus.FAILED, OrderStatus.REFUNDED]

def test_maintenance_cleanup(client, test_user, db_session):
    from app.config.security import create_access_token
    # Elevate test user to ADMIN
    test_user.role = UserRole.ADMIN
    db_session.commit()

    admin_token = create_access_token({"sub": str(test_user.id), "role": "ADMIN"})

    # Insert a document in CLEANUP_PENDING
    doc = Document(
        id="doc_cleanup_target",
        user_id=test_user.id,
        original_filename="old.pdf",
        stored_filename="old.pdf",
        storage_key="documents/old.pdf",
        mime_type="application/pdf",
        file_size=100,
        sha256="abc",
        page_count=1,
        status=DocumentStatus.CLEANUP_PENDING
    )
    db_session.add(doc)
    db_session.commit()

    res = client.post("/api/maintenance/cleanup", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    data = res.json()
    assert "deleted_documents" in data
    db_session.refresh(doc)
    assert doc.status == DocumentStatus.DELETED

def test_dual_printer_otps_and_one_time_switch_lock(client, test_print_server, test_agent_token, db_session, gateway):
    pdf_bytes = create_sample_pdf(1)
    up = client.post("/api/documents/upload", files={"file": ("doc_dual.pdf", pdf_bytes, "application/pdf")}).json()
    order = client.post("/api/orders", json={"document_id": up["documentId"], "print_server_id": test_print_server.id, "settings": {"copies": 1}}).json()

    from tests.conftest import checkout_payload
    assert client.post("/api/payments/verify", json=checkout_payload(client, gateway, order["id"])).status_code == 200

    # Get OTP info
    res = client.get(f"/api/orders/{order['id']}/otp")
    assert res.status_code == 200
    otp_data = res.json()
    assert "printerOtps" in otp_data
    potps = otp_data["printerOtps"]
    assert "HP_LaserJet_400_M401dn_F36EC0" in potps
    assert "HP_LaserJet_400_M401dn_E9A0F4" in potps
    otp1 = potps["HP_LaserJet_400_M401dn_F36EC0"]["otp"]
    otp2 = potps["HP_LaserJet_400_M401dn_E9A0F4"]["otp"]
    assert otp1 != otp2

    # Switch printer allowed once
    switch_res = client.post(f"/api/orders/{order['id']}/printer", json={"cups_printer_name": "HP_LaserJet_400_M401dn_E9A0F4"})
    assert switch_res.status_code == 200
    assert switch_res.json()["printerSelectionLocked"] == True

    # Switching a second time must be BLOCKED
    switch_res2 = client.post(f"/api/orders/{order['id']}/printer", json={"cups_printer_name": "HP_LaserJet_400_M401dn_F36EC0"})
    assert switch_res2.status_code == 400
    assert switch_res2.json()["error"] == "PRINTER_LOCKED"

    # Release using OTP 2
    rel_res = client.post("/api/agent/release-kiosk", headers={"Authorization": "Bearer test-agent-device-token-secret"}, json={"otp": otp2})
    assert rel_res.status_code == 200
    assert rel_res.json()["status"] == "RELEASED"

    # Crucial: Using OTP 1 now MUST FAIL with ALREADY_PRINTED because both OTPs are expired
    rel_res2 = client.post("/api/agent/release-kiosk", headers={"Authorization": "Bearer test-agent-device-token-secret"}, json={"otp": otp1})
    assert rel_res2.status_code == 400
    assert rel_res2.json()["error"] == "ALREADY_PRINTED"
