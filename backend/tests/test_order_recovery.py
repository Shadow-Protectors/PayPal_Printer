import pytest
from app.db.models.order import Order, OrderStatus
from app.db.models.otp import OTP
from app.db.models.print_job import PrintJob, PrintJobStatus
from tests.conftest import create_sample_pdf, checkout_payload


@pytest.mark.parametrize("existing_status", ["CREATED", "WAITING_FOR_OTP", "PRINTING", "COMPLETED"])
def test_new_order_preserves_existing_order(client, test_print_server, db_session, gateway, existing_status):
    headers = {"Authorization": "Bearer sess_customer_multiple_orders"}

    def upload_and_order(filename):
        uploaded = client.post("/api/documents/upload", files={
            "file": (filename, create_sample_pdf(1), "application/pdf")
        })
        assert uploaded.status_code == 201
        response = client.post("/api/orders", headers=headers, json={
            "document_id": uploaded.json()["documentId"],
            "print_server_id": test_print_server.id,
            "settings": {"copies": 1, "colour": False},
        })
        assert response.status_code == 201
        return response.json()

    existing = upload_and_order("existing.pdf")
    if existing_status != "CREATED":
        assert client.post("/api/payments/verify", json=checkout_payload(client, gateway, existing["id"])).status_code == 200
    db_order = db_session.get(Order, existing["id"])
    db_order.status = OrderStatus(existing_status)
    db_session.commit()
    initial = client.get(f'/api/orders/active?order_id={existing["id"]}', headers=headers).json()
    assert initial["canUploadNew"] is True

    new = upload_and_order("new.pdf")
    assert new["id"] != existing["id"]
    assert new["documentId"] != existing["documentId"]
    assert new["status"] == "CREATED"
    db_session.refresh(db_order)
    assert db_order.status == OrderStatus(existing_status)
    after = client.get(f'/api/orders/active?order_id={existing["id"]}', headers=headers).json()
    assert after["stage"] == initial["stage"]
    if "otp" in initial:
        assert after["otp"]["otp"] == initial["otp"]["otp"]

def test_order_recovery_lifecycle(client, test_print_server, db_session, gateway):
    # 1. Create a document and order
    pdf_bytes = create_sample_pdf(2)
    doc_resp = client.post(
        "/api/documents/upload",
        files={"file": ("recovery_test.pdf", pdf_bytes, "application/pdf")}
    ).json()
    doc_id = doc_resp["documentId"]

    sess_token = "sess_customer_test_recovery_123"
    headers = {"Authorization": f"Bearer {sess_token}"}

    create_resp = client.post(
        "/api/orders",
        json={
            "document_id": doc_id,
            "print_server_id": test_print_server.id,
            "settings": {"copies": 1, "colour": False}
        },
        headers=headers
    )
    assert create_resp.status_code == 201
    order_data = create_resp.json()
    order_id = order_data["id"]

    # 2. Check active order recovery when UNPAID
    rec_unpaid = client.get(f"/api/orders/active?order_id={order_id}", headers=headers).json()
    assert rec_unpaid["hasActiveOrder"] is True
    assert rec_unpaid["stage"] == "UNPAID"
    assert rec_unpaid["canUploadNew"] is True
    assert rec_unpaid["order"]["id"] == order_id

    # 3. Pay for the order
    pay_resp = client.post(
        "/api/payments/verify",
        json=checkout_payload(client, gateway, order_id)
    )
    assert pay_resp.status_code == 200

    # 4. Check active order recovery when WAITING_FOR_OTP
    # Must return same order, selected printer, and existing OTP without generating new OTP
    rec_paid = client.get(f"/api/orders/active?order_id={order_id}", headers=headers).json()
    assert rec_paid["hasActiveOrder"] is True
    assert rec_paid["stage"] == "WAITING_FOR_OTP"
    assert rec_paid["canUploadNew"] is True
    initial_otp = rec_paid["otp"]["otp"]
    assert len(initial_otp) == 6

    # Refresh/Reload multiple times: OTP MUST NOT change or invalidate
    for _ in range(3):
        rec_reload = client.get(f"/api/orders/active?order_id={order_id}", headers=headers).json()
        assert rec_reload["otp"]["otp"] == initial_otp

    # Direct get OTP endpoint must also return identical OTP
    otp_call = client.get(f"/api/orders/{order_id}/otp").json()
    assert otp_call["otp"] == initial_otp

    # 5. Printer accepts OTP and releases job -> begins printing
    release_resp = client.post("/api/agent/release-kiosk", headers={"Authorization": "Bearer test-agent-device-token-secret"}, json={"otp": initial_otp})
    assert release_resp.status_code == 200

    # From that moment onward, reopening must restore Printing screen, OTP permanently invalid
    rec_printing = client.get(f"/api/orders/active?order_id={order_id}", headers=headers).json()
    assert rec_printing["hasActiveOrder"] is True
    assert rec_printing["stage"] == "PRINTING"
    assert rec_printing["canUploadNew"] is True
    assert "otp" not in rec_printing

    # Direct OTP view attempt MUST fail with 400
    otp_blocked = client.get(f"/api/orders/{order_id}/otp")
    assert otp_blocked.status_code == 400
    assert otp_blocked.json()["error"] == "OTP_INVALIDATED"

    # 6. Complete print job
    job = db_session.query(PrintJob).filter(PrintJob.order_id == order_id).first()
    update_resp = client.post(
        f"/api/agent/jobs/{job.id}/status",
        headers={"Authorization": "Bearer test-agent-device-token-secret"},
        json={"status": "COMPLETED"}
    )
    assert update_resp.status_code == 200

    # 7. Reload after completion: opens order summary / receipt, never displays OTP, read-only
    rec_completed = client.get(f"/api/orders/active?order_id={order_id}", headers=headers).json()
    assert rec_completed["hasActiveOrder"] is False
    assert rec_completed["stage"] == "COMPLETED"
    assert rec_completed["isCompletedReceipt"] is True
    assert rec_completed["canUploadNew"] is True
    assert "otp" not in rec_completed

    # Calling OTP on completed order must fail
    assert client.get(f"/api/orders/{order_id}/otp").status_code == 400

    # 8. Reconcile payment endpoint test
    reconcile = client.post("/api/payments/reconcile", json={"orderId": order_id}).json()
    assert reconcile["status"] == "SUCCESS"
    assert reconcile["paid"] is True


def test_cancel_unpaid_order(client, test_print_server, db_session):
    pdf_bytes = create_sample_pdf(1)
    doc_resp = client.post(
        "/api/documents/upload",
        files={"file": ("cancel_test.pdf", pdf_bytes, "application/pdf")}
    ).json()
    doc_id = doc_resp["documentId"]

    sess_token = "sess_customer_cancel_unpaid"
    headers = {"Authorization": f"Bearer {sess_token}"}

    create_resp = client.post(
        "/api/orders",
        json={
            "document_id": doc_id,
            "print_server_id": test_print_server.id,
            "settings": {"copies": 1, "colour": False}
        },
        headers=headers
    )
    assert create_resp.status_code == 201
    order_id = create_resp.json()["id"]

    # Cancel unpaid order
    cancel_resp = client.post(f"/api/orders/{order_id}/cancel", headers=headers)
    assert cancel_resp.status_code == 200
    cancel_data = cancel_resp.json()
    assert cancel_data["status"] == "SUCCESS"
    assert cancel_data["orderStatus"] == "CANCELLED"
    assert cancel_data["refundRequired"] is False

    # Check active order lookup returns no active order
    rec = client.get(f"/api/orders/active?order_id={order_id}", headers=headers).json()
    assert rec["hasActiveOrder"] is False
    assert rec["canUploadNew"] is True


def test_cancel_paid_order_triggers_refund(client, test_print_server, db_session, gateway):
    pdf_bytes = create_sample_pdf(1)
    doc_resp = client.post(
        "/api/documents/upload",
        files={"file": ("cancel_paid_test.pdf", pdf_bytes, "application/pdf")}
    ).json()
    doc_id = doc_resp["documentId"]

    sess_token = "sess_customer_cancel_paid"
    headers = {"Authorization": f"Bearer {sess_token}"}

    create_resp = client.post(
        "/api/orders",
        json={
            "document_id": doc_id,
            "print_server_id": test_print_server.id,
            "settings": {"copies": 1, "colour": False}
        },
        headers=headers
    )
    order_id = create_resp.json()["id"]

    # Pay
    client.post(
        "/api/payments/verify",
        json=checkout_payload(client, gateway, order_id)
    )

    rec_paid = client.get(f"/api/orders/active?order_id={order_id}", headers=headers).json()
    assert rec_paid["stage"] == "WAITING_FOR_OTP"
    otp_code = rec_paid["otp"]["otp"]

    # Cancel paid order
    cancel_resp = client.post(f"/api/orders/{order_id}/cancel", headers=headers)
    assert cancel_resp.status_code == 200
    cancel_data = cancel_resp.json()
    assert cancel_data["status"] == "SUCCESS"
    assert cancel_data["refundRequired"] is True
    assert "refundId" in cancel_data

    # Releasing at kiosk must now fail because OTP was invalidated
    kiosk_resp = client.post("/api/agent/release-kiosk", headers={"Authorization": "Bearer test-agent-device-token-secret"}, json={"otp": otp_code})
    assert kiosk_resp.status_code == 400

    # Once cancelled and refunded, attempting to cancel again returns idempotent success
    repeat_cancel = client.post(f"/api/orders/{order_id}/cancel", headers=headers)
    assert repeat_cancel.status_code == 200
